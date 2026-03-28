"""
document_analyzer.py — Belge yükleme ve hukuki analiz servisi
Karşı dilekçe, sözleşme, mahkeme kararı, fatura analizi yapar
ve Claude ile otomatik itiraz/yanıt dilekçesi üretir.
"""

import os
import io
import base64
import logging
import tempfile
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-5"
MAX_TOKENS   = 4096

# ── Belge türlerine göre analiz promptları ────────────────────────────────────

ANALYSIS_PROMPTS = {
    "karsi_dilekce": {
        "system": """Sen deneyimli bir Türk avukatısın. Sana karşı tarafın dilekçesi
verilecek. Bu dilekçeyi analiz et ve güçlü bir itiraz/cevap dilekçesi hazırla.

ANALIZ AŞAMASI:
1. Karşı tarafın ana argümanlarını tespit et
2. Hukuki dayanakların zayıf noktalarını bul
3. Çelişen iddialar ve kanıt eksikliklerini işaretle

DİLEKÇE AŞAMASI:
- Her argümana karşı güçlü bir karşı argüman üret
- İlgili kanun maddeleriyle destekle
- NETİCE-İ TALEP bölümüyle bitir""",
        "user": """KARŞI TARAFIN DİLEKÇESİ:\n{belge_metni}

AVUKAT BİLGİSİ: {avukat_bilgisi}
EK TALİMAT: {talep}

Önce dilekçeyi analiz et, sonra güçlü bir itiraz dilekçesi yaz.""",
        "label": "Karşı Dilekçe Analizi ve İtiraz",
    },

    "sozlesme": {
        "system": """Sen deneyimli bir Türk sözleşme hukuku avukatısın.
Sözleşmeleri hukuki açıdan analiz eder, risk ve ihlalleri tespit edersin.

ANALİZ ÇIKTISI:
1. GENEL DEĞERLENDİRME — Sözleşme türü ve temel koşullar
2. RİSKLİ MADDELER — Müvekkil aleyhine hükümler
3. EKSİK HÜKÜMLER — Olması gereken ama bulunmayan maddeler
4. İHLAL TESPİTİ — Karşı tarafın ihlal ettiği maddeler (varsa)
5. ÖNERİLEN EYLEM — Dilekçe/ihtarname/dava önerisi""",
        "user": """SÖZLEŞME METNİ:\n{belge_metni}

AVUKAT BİLGİSİ: {avukat_bilgisi}
ÖZEL SORU/TALİMAT: {talep}

Sözleşmeyi analiz et ve hukuki değerlendirme raporunu yaz.""",
        "label": "Sözleşme Analizi",
    },

    "mahkeme_karari": {
        "system": """Sen deneyimli bir Türk avukatısın. Mahkeme kararlarını analiz
eder ve istinaf/temyiz dilekçeleri hazırlarsın.

ANALİZ AŞAMASI:
1. Kararın özeti ve gerekçesi
2. Hukuka aykırılık varsa tespit et
3. Usul hatalarını belirle
4. Emsal kararlarla çelişme var mı?

İSTİNAF/TEMYİZ DİLEKÇESİ:
- Bölge Adliye Mahkemesi veya Yargıtay'a hitaben
- Her bozma sebebini ayrı başlık altında
- Hukuki dayanaklarla destekli
- NETİCE-İ TALEP""",
        "user": """MAHKEME KARARI:\n{belge_metni}

AVUKAT BİLGİSİ: {avukat_bilgisi}
TALEP (istinaf/temyiz): {talep}

Kararı analiz et ve itiraz dilekçesini yaz.""",
        "label": "Mahkeme Kararı Analizi ve İtiraz",
    },

    "fatura_belge": {
        "system": """Sen deneyimli bir Türk icra hukuku avukatısın.
Fatura, senet ve ticari belgelerden icra takibi dilekçesi hazırlarsın.

BELGE ANALİZİ:
1. Alacak miktarı ve vadesi
2. Borcun hukuki niteliği (fatura/senet/sözleşme)
3. Faiz hesabı (ticari/yasal)

İCRA DİLEKÇESİ:
- İcra Müdürlüğüne hitaben
- Alacak miktarı (rakam+yazı)
- Faiz türü ve başlangıcı
- Ekler listesi
- NETİCE-İ TALEP""",
        "user": """BELGE İÇERİĞİ:\n{belge_metni}

AVUKAT BİLGİSİ: {avukat_bilgisi}
EK BİLGİ: {talep}

Belgeyi analiz et ve icra takip dilekçesini yaz.""",
        "label": "Fatura/Belge Analizi ve İcra Dilekçesi",
    },
}


def extract_text_from_upload(file_bytes: bytes, filename: str) -> str:
    """
    Yüklenen dosyadan metin çıkarır.
    PDF, DOCX ve TXT desteklenir.
    """
    ext = filename.lower().split(".")[-1]

    if ext == "txt":
        return file_bytes.decode("utf-8", errors="ignore")

    if ext == "pdf":
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                return "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
        except Exception as e:
            log.error(f"PDF okuma hatası: {e}")
            return ""

    if ext in ("docx", "doc"):
        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            log.error(f"DOCX okuma hatası: {e}")
            return ""

    return ""


def analyze_document(
    file_bytes:    bytes,
    filename:      str,
    analysis_type: str,
    avukat_adi:    str,
    baro:          str = "",
    talep:         str = "",
) -> dict:
    """
    Belgeyi analiz eder ve Claude ile yanıt dilekçesi üretir.
    Döner: {analysis_text, document_text, analysis_type, char_count}
    """
    if analysis_type not in ANALYSIS_PROMPTS:
        raise ValueError(f"Geçersiz analiz türü: {analysis_type}")

    prompt_cfg = ANALYSIS_PROMPTS[analysis_type]

    # Metni çıkar
    doc_text = extract_text_from_upload(file_bytes, filename)
    if not doc_text.strip():
        return {
            "error": "Dosyadan metin çıkarılamadı. PDF taranmış görüntü olabilir.",
            "analysis_text": "",
            "document_text": "",
        }

    # 8000 karakter ile sınırla (token limiti)
    doc_text_trimmed = doc_text[:8000]
    if len(doc_text) > 8000:
        doc_text_trimmed += "\n\n[... belge kısaltıldı ...]"

    # Avukat bilgisi
    avukat_bilgisi = f"Av. {avukat_adi}"
    if baro:
        avukat_bilgisi += f" — {baro} Barosu"

    user_message = prompt_cfg["user"].format(
        belge_metni    = doc_text_trimmed,
        avukat_bilgisi = avukat_bilgisi,
        talep          = talep or "Standart analiz ve dilekçe hazırla.",
    )

    client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = MAX_TOKENS,
        system     = prompt_cfg["system"],
        messages   = [{"role": "user", "content": user_message}],
    )

    analysis_text = response.content[0].text
    cost = (
        response.usage.input_tokens  * 3.0  / 1e6 +
        response.usage.output_tokens * 15.0 / 1e6
    )

    log.info(
        f"Belge analizi: {analysis_type} | "
        f"{response.usage.input_tokens}→{response.usage.output_tokens} token | "
        f"${cost:.4f}"
    )

    return {
        "analysis_text": analysis_text,
        "document_text": doc_text[:500] + "..." if len(doc_text) > 500 else doc_text,
        "analysis_type": analysis_type,
        "label":         prompt_cfg["label"],
        "char_count":    len(doc_text),
        "cost_usd":      round(cost, 5),
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
