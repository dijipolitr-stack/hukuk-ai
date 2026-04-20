"""
engine.py — Dilekçe üretim motoru
Avukattan gelen talebi alır → kararnameleri arar → Claude ile dilekçe yazar.

Kullanım:
  engine = PetitionEngine(db_conn)

  # Streaming (mobil için)
  async for chunk in engine.generate_stream(request):
      send_to_client(chunk)

  # Tam sonuç
  result = engine.generate(request)
"""

import os
import sys
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Generator
from datetime import datetime

import anthropic
import psycopg as psycopg2
from dotenv import load_dotenv

# Üst dizini path'e ekle (scraper modüllerini import için)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
from embedder import semantic_search, format_context_for_claude
from prompts import get_prompt, build_user_message

load_dotenv()
log = logging.getLogger(__name__)

CLAUDE_MODEL   = "claude-sonnet-4-5"   # Dilekçe kalitesi için Sonnet
CLAUDE_HAIKU   = "claude-haiku-4-5-20251001"  # Hız/maliyet için Haiku
MAX_TOKENS     = 4096
TOP_K_CHUNKS   = 8    # Kaç kararname chunk'ı gönderilsin
MIN_SIMILARITY = 0.35 # Bu eşiğin altındaki chunk'lar kullanılmaz


@dataclass
class PetitionRequest:
    """Dilekçe üretim isteği."""
    lawyer_id:      int
    petition_type:  str          # mahkeme | ihtarname | idari | icra
    talep:          str          # Avukatın talebi (ses transkripsiyonu veya yazı)
    avukat_adi:     str
    baro:           str = ""
    sicil:          str = ""
    category_hint:  Optional[str] = None   # Arama filtresi (örn: "İş Hukuku")
    date_from:      Optional[str] = None   # Kararname tarih filtresi
    use_haiku:      bool = False            # Maliyet tasarrufu için Haiku kullan
    extra_context:  str = ""               # Avukatın ek notları


@dataclass
class PetitionResult:
    """Dilekçe üretim sonucu."""
    petition_text:   str
    petition_type:   str
    used_decrees:    list[dict]   # Kullanılan kararname bilgileri
    input_tokens:    int
    output_tokens:   int
    model:           str
    cost_usd:        float
    duration_sec:    float
    warning:         str = ""     # Kararname bulunamadı uyarısı vb.


# Token başına USD fiyatları (2025)
PRICING = {
    "claude-sonnet-4-5":           {"in": 3.0 / 1e6,  "out": 15.0 / 1e6},
    "claude-haiku-4-5-20251001":   {"in": 0.25 / 1e6, "out": 1.25 / 1e6},
}


class PetitionEngine:

    def __init__(self, db_conn):
        self.conn   = db_conn
        # httpx proxies uyumsuzluğunu önlemek için custom client
        import httpx
        http_client = httpx.Client(timeout=120.0)
        self.client = anthropic.Anthropic(
            api_key     = os.getenv("ANTHROPIC_API_KEY"),
            http_client = http_client,
        )

    # ── Ana üretim metodu (tam sonuç) ────────────────────────────────────────

    def generate(self, req: PetitionRequest) -> PetitionResult:
        t0 = time.time()
        model = CLAUDE_HAIKU if req.use_haiku else CLAUDE_MODEL

        # 1. Kararname ara
        chunks, warning = self._search_decrees(req)
        context = format_context_for_claude(chunks)

        # 2. Prompt inşa et
        system_prompt = get_prompt(req.petition_type).system
        user_message  = build_user_message(
            petition_type   = req.petition_type,
            talep           = req.talep + (f"\n\nEK NOT: {req.extra_context}" if req.extra_context else ""),
            kararname_metni = context,
            avukat_adi      = req.avukat_adi,
            baro            = req.baro,
            sicil           = req.sicil,
        )

        log.info(
            f"Dilekçe üretiliyor | tür={req.petition_type} "
            f"model={model} chunks={len(chunks)}"
        )

        # 3. Claude API çağrısı
        response = self.client.messages.create(
            model      = model,
            max_tokens = MAX_TOKENS,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_message}],
        )

        petition_text = response.content[0].text
        in_tok  = response.usage.input_tokens
        out_tok = response.usage.output_tokens
        cost    = in_tok * PRICING[model]["in"] + out_tok * PRICING[model]["out"]

        # 4. Veritabanına kaydet
        petition_id = self._save_petition(req, petition_text, chunks, model)
        log.info(
            f"Dilekçe kaydedildi [#{petition_id}] | "
            f"{in_tok}→{out_tok} token | ${cost:.4f} | {time.time()-t0:.1f}s"
        )

        return PetitionResult(
            petition_text  = petition_text,
            petition_type  = req.petition_type,
            used_decrees   = chunks,
            input_tokens   = in_tok,
            output_tokens  = out_tok,
            model          = model,
            cost_usd       = round(cost, 5),
            duration_sec   = round(time.time() - t0, 2),
            warning        = warning,
        )

    # ── Streaming üretim (mobil için gerçek zamanlı) ─────────────────────────

    def generate_stream(
        self, req: PetitionRequest
    ) -> Generator[dict, None, None]:
        """
        Server-Sent Events formatında chunk'lar döner.
        Her yield: {"type": "chunk"|"meta"|"error", "data": ...}
        """
        model = CLAUDE_HAIKU if req.use_haiku else CLAUDE_MODEL

        # Kararname ara
        chunks, warning = self._search_decrees(req)
        context = format_context_for_claude(chunks)

        if warning:
            yield {"type": "warning", "data": warning}

        # Kullanılan kararname bilgisini önceden gönder
        yield {
            "type": "meta",
            "data": {
                "used_decrees": [
                    {
                        "title":          c["decree_title"],
                        "gazette_number": c["gazette_number"],
                        "gazette_date":   c["gazette_date"],
                        "madde_no":       c["madde_no"],
                        "similarity":     c["similarity"],
                    }
                    for c in chunks
                ],
                "model": model,
            }
        }

        system_prompt = get_prompt(req.petition_type).system
        user_message  = build_user_message(
            petition_type   = req.petition_type,
            talep           = req.talep,
            kararname_metni = context,
            avukat_adi      = req.avukat_adi,
            baro            = req.baro,
            sicil           = req.sicil,
        )

        full_text = ""
        in_tok = out_tok = 0

        with self.client.messages.stream(
            model      = model,
            max_tokens = MAX_TOKENS,
            system     = system_prompt,
            messages   = [{"role": "user", "content": user_message}],
        ) as stream:
            for text_chunk in stream.text_stream:
                full_text += text_chunk
                yield {"type": "chunk", "data": text_chunk}

            usage  = stream.get_final_message().usage
            in_tok  = usage.input_tokens
            out_tok = usage.output_tokens

        cost = in_tok * PRICING[model]["in"] + out_tok * PRICING[model]["out"]

        # Kaydet
        petition_id = self._save_petition(req, full_text, chunks, model)

        yield {
            "type": "done",
            "data": {
                "petition_id": petition_id,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": round(cost, 5),
                "model": model,
            }
        }

    # ── Yardımcı metotlar ────────────────────────────────────────────────────

    def _search_decrees(
        self, req: PetitionRequest
    ) -> tuple[list[dict], str]:
        """
        Avukat talebine göre kararname arar.
        (chunks, uyarı_mesajı) döner.
        """
        results = semantic_search(
            conn            = self.conn,
            query           = req.talep,
            top_k           = TOP_K_CHUNKS,
            category_filter = req.category_hint,
            date_from       = req.date_from,
        )

        # Düşük benzerlik filtresi
        filtered = [r for r in results if r["similarity"] >= MIN_SIMILARITY]
        warning  = ""

        if not filtered:
            warning = (
                "Sağlanan kararname veritabanında bu talebe uygun "
                "madde bulunamadı. Dilekçe genel hukuk bilgisiyle "
                "oluşturuldu — avukatın kontrolü önerilir."
            )
            log.warning(f"Kararname bulunamadı: {req.talep[:80]}")
            # Filtresiz en iyi 3'ü yine de gönder
            filtered = results[:3]

        return filtered, warning

    def _save_petition(
        self,
        req: PetitionRequest,
        text: str,
        chunks: list[dict],
        model: str,
    ) -> int:
        """Dilekçeyi veritabanına kaydeder, ID döner."""
        decree_ids = list({c["decree_id"] for c in chunks})
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO petitions
                    (lawyer_id, petition_type, subject, user_input,
                     generated_text, used_decree_ids, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'draft')
                RETURNING id
            """, (
                req.lawyer_id,
                req.petition_type,
                req.talep[:200],
                req.talep,
                text,
                decree_ids,
            ))
            petition_id = cur.fetchone()[0]
            self.conn.commit()
        return petition_id

    # ── Ses transkripsiyonu (Whisper) ────────────────────────────────────────

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.m4a") -> str:
        """
        Sesli talebi metne çevirir.
        Mobil uygulamadan gelen ham ses verisi için.
        """
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            import openai as oai
            oai_client = oai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            with open(tmp_path, "rb") as f:
                transcript = oai_client.audio.transcriptions.create(
                    model    = "whisper-1",
                    file     = f,
                    language = "tr",
                )
            log.info(f"Transkripsiyon: {transcript.text[:100]}...")
            return transcript.text
        finally:
            os.unlink(tmp_path)

    # ── Dilekçe revizyonu ─────────────────────────────────────────────────────

    def revise(
        self,
        original_text: str,
        revision_note: str,
        petition_type: str,
        use_haiku: bool = False,
    ) -> str:
        """
        Avukatın notuna göre dilekçeyi revize eder.
        Kararname araması yapmaz, sadece metni düzenler.
        """
        model = CLAUDE_HAIKU if use_haiku else CLAUDE_MODEL
        response = self.client.messages.create(
            model      = model,
            max_tokens = MAX_TOKENS,
            system     = (
                "Sen bir Türk hukuk avukatısın. "
                "Sana orijinal bir dilekçe ve revizyon notu verilecek. "
                "Dilekçeyi nota göre düzenle, hukuki bütünlüğü koru."
            ),
            messages   = [{
                "role": "user",
                "content": (
                    f"ORİJİNAL DİLEKÇE:\n{original_text}\n\n"
                    f"REVİZYON NOTU:\n{revision_note}\n\n"
                    "Dilekçeyi revizyon notuna göre düzenle ve tam metni döndür."
                ),
            }],
        )
        return response.content[0].text
