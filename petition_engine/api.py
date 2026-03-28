"""
api.py — FastAPI REST API
Mobil uygulamanın bağlandığı dilekçe endpoint'leri.

Çalıştırma:
  uvicorn api:app --host 0.0.0.0 --port 8000 --reload
"""

import os
import logging
from contextlib import asynccontextmanager
from typing import Optional, AsyncGenerator

import psycopg as psycopg2
from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import jwt as pyjwt
import json

from engine import PetitionEngine, PetitionRequest
from auth import router as auth_router

load_dotenv()
log = logging.getLogger(__name__)

JWT_SECRET = os.getenv("JWT_SECRET", "degistir-bunu-production-da")


# ── Veritabanı bağlantısı ────────────────────────────────────────────────────

def get_db():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    try:
        yield conn
    finally:
        conn.close()


# ── JWT doğrulama ─────────────────────────────────────────────────────────────

def get_current_lawyer(authorization: str = Header(...)):
    try:
        token   = authorization.replace("Bearer ", "")
        payload = pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload   # {"lawyer_id": X, "email": "...", "name": "..."}
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token süresi dolmuş")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Geçersiz token")


# ── Pydantic modelleri ────────────────────────────────────────────────────────

class PetitionCreateRequest(BaseModel):
    petition_type: str = Field(
        ...,
        description="mahkeme | ihtarname | idari | icra"
    )
    talep: str = Field(..., min_length=20, max_length=5000)
    category_hint: Optional[str] = None
    date_from: Optional[str] = None          # "2023-01-01" formatı
    use_haiku: bool = False
    extra_context: str = ""


class ReviseRequest(BaseModel):
    petition_id: int
    revision_note: str = Field(..., min_length=5, max_length=2000)


class PetitionResponse(BaseModel):
    petition_id: int
    petition_text: str
    petition_type: str
    used_decrees: list[dict]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_sec: float
    warning: str


# ── FastAPI uygulaması ────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Dilekçe API başlatıldı")
    yield
    log.info("Dilekçe API kapatıldı")


app = FastAPI(
    title     = "Hukuk AI — Dilekçe Motoru",
    version   = "1.0.0",
    lifespan  = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],   # Production'da domain kısıtla
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

app.include_router(auth_router)


# ── Endpoint'ler ──────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "petition-engine"}


@app.post("/petition/generate", response_model=PetitionResponse)
def generate_petition(
    body:   PetitionCreateRequest,
    lawyer: dict = Depends(get_current_lawyer),
    conn         = Depends(get_db),
):
    """
    Dilekçe üret (tam yanıt — streaming değil).
    Basit istemciler için.
    """
    req = PetitionRequest(
        lawyer_id      = lawyer["lawyer_id"],
        petition_type  = body.petition_type,
        talep          = body.talep,
        avukat_adi     = lawyer.get("name", "Avukat"),
        baro           = lawyer.get("baro", ""),
        sicil          = lawyer.get("sicil", ""),
        category_hint  = body.category_hint,
        date_from      = body.date_from,
        use_haiku      = body.use_haiku,
        extra_context  = body.extra_context,
    )

    engine = PetitionEngine(conn)
    try:
        result = engine.generate(req)
    except Exception as e:
        log.exception("Dilekçe üretim hatası")
        raise HTTPException(status_code=500, detail=str(e))

    # DB'den petition_id'yi al
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM petitions WHERE lawyer_id=%s ORDER BY created_at DESC LIMIT 1",
            (lawyer["lawyer_id"],)
        )
        row = cur.fetchone()
        petition_id = row[0] if row else 0

    return PetitionResponse(
        petition_id   = petition_id,
        petition_text = result.petition_text,
        petition_type = result.petition_type,
        used_decrees  = result.used_decrees,
        input_tokens  = result.input_tokens,
        output_tokens = result.output_tokens,
        cost_usd      = result.cost_usd,
        duration_sec  = result.duration_sec,
        warning       = result.warning,
    )


@app.post("/petition/stream")
async def stream_petition(
    body:   PetitionCreateRequest,
    lawyer: dict = Depends(get_current_lawyer),
    conn         = Depends(get_db),
):
    """
    Dilekçeyi Server-Sent Events ile stream eder.
    Mobil uygulama gerçek zamanlı akışı buradan alır.
    """
    req = PetitionRequest(
        lawyer_id      = lawyer["lawyer_id"],
        petition_type  = body.petition_type,
        talep          = body.talep,
        avukat_adi     = lawyer.get("name", "Avukat"),
        baro           = lawyer.get("baro", ""),
        sicil          = lawyer.get("sicil", ""),
        category_hint  = body.category_hint,
        date_from      = body.date_from,
        use_haiku      = body.use_haiku,
        extra_context  = body.extra_context,
    )

    engine = PetitionEngine(conn)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            for event in engine.generate_stream(req):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            log.exception("Stream hatası")
            yield f"data: {json.dumps({'type':'error','data':str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type = "text/event-stream",
        headers    = {
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",
            "Access-Control-Allow-Origin": "*",
        }
    )


@app.post("/petition/transcribe")
async def transcribe_audio(
    audio:  UploadFile = File(...),
    lawyer: dict       = Depends(get_current_lawyer),
    conn               = Depends(get_db),
):
    """
    Sesli talebi metne çevirir.
    Mobil'den WAV/M4A/MP3 yüklenir, Türkçe transkripsiyon döner.
    """
    audio_bytes = await audio.read()
    if len(audio_bytes) > 25 * 1024 * 1024:  # 25MB limit
        raise HTTPException(status_code=413, detail="Ses dosyası çok büyük (max 25MB)")

    engine = PetitionEngine(conn)
    try:
        text = engine.transcribe_audio(audio_bytes, audio.filename)
    except Exception as e:
        log.exception("Transkripsiyon hatası")
        raise HTTPException(status_code=500, detail=str(e))

    return {"transcription": text, "char_count": len(text)}


@app.post("/petition/revise")
def revise_petition(
    body:   ReviseRequest,
    lawyer: dict = Depends(get_current_lawyer),
    conn         = Depends(get_db),
):
    """
    Mevcut dilekçeyi revize eder.
    Avukat notlarına göre Claude metni düzenler.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT generated_text, petition_type, lawyer_id FROM petitions WHERE id=%s",
            (body.petition_id,)
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Dilekçe bulunamadı")
    if row[2] != lawyer["lawyer_id"]:
        raise HTTPException(status_code=403, detail="Bu dilekçeye erişim yetkiniz yok")

    engine = PetitionEngine(conn)
    try:
        revised = engine.revise(
            original_text  = row[0],
            revision_note  = body.revision_note,
            petition_type  = row[1],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Güncellenmiş metni kaydet
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE petitions SET generated_text=%s, status='revised' WHERE id=%s",
            (revised, body.petition_id)
        )
        conn.commit()

    return {"petition_id": body.petition_id, "revised_text": revised}


@app.get("/petition/history")
def petition_history(
    limit:  int  = 20,
    offset: int  = 0,
    lawyer: dict = Depends(get_current_lawyer),
    conn         = Depends(get_db),
):
    """Avukatın geçmiş dilekçelerini listeler."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, petition_type, subject, status, created_at
            FROM petitions
            WHERE lawyer_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, (lawyer["lawyer_id"], limit, offset))
        rows = cur.fetchall()

    return [
        {
            "id":             r[0],
            "petition_type":  r[1],
            "subject":        r[2],
            "status":         r[3],
            "created_at":     str(r[4]),
        }
        for r in rows
    ]


@app.get("/petition/types")
def get_petition_types():
    """Mevcut tüm dilekçe türlerini döner."""
    from prompts import PETITION_PROMPTS
    types = {
        "mahkeme":   {"label": "Mahkemeye Dilekçe",      "icon": "⚖️",  "category": "temel"},
        "ihtarname": {"label": "İhtarname",               "icon": "📋", "category": "temel"},
        "idari":     {"label": "İdari Başvuru",           "icon": "🏛️", "category": "temel"},
        "icra":      {"label": "İcra Takibi",             "icon": "📑", "category": "temel"},
        "bosanma":   {"label": "Boşanma ve Aile Hukuku",  "icon": "👨‍👩‍👧", "category": "ozel"},
        "tazminat":  {"label": "Tazminat Davası",         "icon": "⚡", "category": "ozel"},
        "kira":      {"label": "Kira Tespit ve Tahliye",  "icon": "🏠", "category": "ozel"},
        "ceza":      {"label": "Ceza Davası Savunma",     "icon": "🛡️", "category": "ozel"},
        "miras":     {"label": "Miras İtirazı",           "icon": "📜", "category": "ozel"},
        "sigorta":   {"label": "Sigorta Tazminatı",       "icon": "🔒", "category": "ozel"},
        "tuketici":  {"label": "Tüketici Şikayeti",       "icon": "🛒", "category": "ozel"},
        "iskaza":    {"label": "İş Kazası",               "icon": "⛑️", "category": "ozel"},
    }
    return {k: v for k, v in types.items() if k in PETITION_PROMPTS}


@app.get("/petition/{petition_id}")
def get_petition(
    petition_id: int,
    lawyer: dict = Depends(get_current_lawyer),
    conn         = Depends(get_db),
):
    """Tek bir dilekçenin tam metnini döner."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, petition_type, subject, user_input,
                      generated_text, used_decree_ids, status, created_at
               FROM petitions WHERE id=%s AND lawyer_id=%s""",
            (petition_id, lawyer["lawyer_id"])
        )
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Dilekçe bulunamadı")

    return {
        "id":              row[0],
        "petition_type":   row[1],
        "subject":         row[2],
        "user_input":      row[3],
        "generated_text":  row[4],
        "used_decree_ids": row[5],
        "status":          row[6],
        "created_at":      str(row[7]),
    }


@app.post("/document/analyze")
async def analyze_document(
    file:          UploadFile = File(...),
    analysis_type: str        = "karsi_dilekce",
    talep:         str        = "",
    lawyer: dict              = Depends(get_current_lawyer),
    conn                      = Depends(get_db),
):
    """
    Yüklenen belgeyi (PDF/DOCX/TXT) analiz eder ve dilekçe üretir.
    analysis_type: karsi_dilekce | sozlesme | mahkeme_karari | fatura_belge
    """
    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Dosya çok büyük (max 10MB)")

    from document_analyzer import analyze_document as _analyze
    try:
        result = _analyze(
            file_bytes    = file_bytes,
            filename      = file.filename,
            analysis_type = analysis_type,
            avukat_adi    = lawyer.get("name", "Avukat"),
            baro          = lawyer.get("baro", ""),
            talep         = talep,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("Belge analizi hatası")
        raise HTTPException(status_code=500, detail=str(e))

    if "error" in result:
        raise HTTPException(status_code=422, detail=result["error"])

    # Dilekçe olarak kaydet
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO petitions
                (lawyer_id, petition_type, subject, user_input, generated_text, status)
            VALUES (%s, %s, %s, %s, %s, 'draft')
            RETURNING id
        """, (
            lawyer["lawyer_id"],
            analysis_type,
            f"{result['label']} — {file.filename}",
            talep or f"Belge analizi: {file.filename}",
            result["analysis_text"],
        ))
        petition_id = cur.fetchone()[0]
        conn.commit()

    result["petition_id"] = petition_id
    return result


# ── Dava yönetimi endpoint'leri ───────────────────────────────────────────────

@app.get("/cases")
def list_cases(status: str = "active", lawyer: dict = Depends(get_current_lawyer), conn = Depends(get_db)):
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "case_tools"))
    from case_manager import get_cases
    return get_cases(conn, lawyer["lawyer_id"], status)


@app.post("/cases")
def create_case(body: dict, lawyer: dict = Depends(get_current_lawyer), conn = Depends(get_db)):
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "case_tools"))
    from case_manager import create_case as _create
    if not body.get("title"): raise HTTPException(status_code=400, detail="Dava başlığı zorunludur")
    return {"case_id": _create(conn, lawyer["lawyer_id"], body), "status": "created"}


@app.get("/cases/deadline_types")
def get_deadline_types():
    return {"hearing":{"label":"Duruşma Tarihi","color":"#2D4A8A"},"appeal":{"label":"Temyiz Süresi","color":"#7B3FA0"},"objection":{"label":"İtiraz Süresi","color":"#C0392B"},"statute":{"label":"Dava Açma Zamanaşımı","color":"#B87333"},"payment":{"label":"Ödeme Vadesi","color":"#1D7A4F"},"contract":{"label":"Sözleşme Bitiş","color":"#888780"}}


@app.get("/cases/deadlines")
def get_deadlines(days: int = 30, lawyer: dict = Depends(get_current_lawyer), conn = Depends(get_db)):
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "case_tools"))
    from case_manager import get_upcoming_deadlines, get_overdue_deadlines
    return {"upcoming": get_upcoming_deadlines(conn, lawyer["lawyer_id"], days), "overdue": get_overdue_deadlines(conn, lawyer["lawyer_id"])}


@app.post("/cases/{case_id}/deadlines")
def add_deadline(case_id: int, body: dict, lawyer: dict = Depends(get_current_lawyer), conn = Depends(get_db)):
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "case_tools"))
    from case_manager import add_deadline as _add
    return {"deadline_id": _add(conn, case_id, lawyer["lawyer_id"], body), "status": "created"}


@app.post("/cases/deadlines/{deadline_id}/done")
def complete_deadline(deadline_id: int, lawyer: dict = Depends(get_current_lawyer), conn = Depends(get_db)):
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "case_tools"))
    from case_manager import mark_deadline_done
    mark_deadline_done(conn, deadline_id, lawyer["lawyer_id"])
    return {"status": "done"}


@app.post("/cases/strategy")
def analyze_strategy(body: dict, lawyer: dict = Depends(get_current_lawyer), conn = Depends(get_db)):
    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "case_tools"))
    from case_manager import analyze_strategy as _analyze
    if not body.get("case_summary"): raise HTTPException(status_code=400, detail="Dava özeti zorunludur")
    try:
        return _analyze(conn=conn, lawyer_id=lawyer["lawyer_id"], case_summary=body["case_summary"], case_id=body.get("case_id"), category=body.get("category",""))
    except Exception as e:
        log.exception("Strateji analizi hatası"); raise HTTPException(status_code=500, detail=str(e))


@app.get("/precedents/search")
def search_precedents_ep(q: str, category: str = "", top_k: int = 8, conn = Depends(get_db)):
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "case_tools"))
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
    from precedent_scraper import search_precedents as _search
    try: return _search(conn, q, category=category, top_k=top_k)
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


def get_notifications(
    unread_only: bool = False,
    limit:       int  = 30,
    lawyer: dict      = Depends(get_current_lawyer),
    conn              = Depends(get_db),
):
    """Avukatın bildirimlerini listeler."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "notifications"))
    from notifier import get_notifications as _get, get_unread_count
    items = _get(conn, lawyer["lawyer_id"], unread_only=unread_only, limit=limit)
    count = get_unread_count(conn, lawyer["lawyer_id"])
    return {"notifications": items, "unread_count": count}


@app.post("/notifications/read")
def mark_notifications_read(
    ids:    list[int] = [],
    lawyer: dict      = Depends(get_current_lawyer),
    conn              = Depends(get_db),
):
    """Bildirimleri okundu işaretle. ids boşsa tümünü işaretle."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "notifications"))
    from notifier import mark_read
    mark_read(conn, lawyer["lawyer_id"], ids or None)
    return {"status": "ok"}


@app.get("/notifications/preferences")
def get_preferences(
    lawyer: dict = Depends(get_current_lawyer),
    conn         = Depends(get_db),
):
    """Avukatın bildirim tercihlerini döner."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "notifications"))
    from notifier import get_preferences as _get_pref
    return _get_pref(conn, lawyer["lawyer_id"])


@app.post("/notifications/preferences")
def save_preferences(
    body:   dict,
    lawyer: dict = Depends(get_current_lawyer),
    conn         = Depends(get_db),
):
    """Avukatın kategori tercihlerini kaydeder."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "notifications"))
    from notifier import save_preferences as _save
    _save(
        conn,
        lawyer["lawyer_id"],
        categories   = body.get("categories", []),
        email_digest = body.get("email_digest", True),
        digest_hour  = body.get("digest_hour", 8),
    )
    return {"status": "ok"}


@app.get("/decrees/search")
def search_decrees(
    q:        str,
    top_k:    int = 10,
    category: str = "",
    conn          = Depends(get_db),
):
    """Semantik kararname araması."""
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
    from embedder import semantic_search
    results = semantic_search(
        conn            = conn,
        query           = q,
        top_k           = top_k,
        category_filter = category or None,
    )
    return results


@app.get("/decrees/categories")
def list_categories(conn = Depends(get_db)):
    """Veritabanındaki kararname kategorilerini listeler. Arama filtresi için."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT category, COUNT(*) AS cnt
            FROM decrees
            WHERE category IS NOT NULL
            GROUP BY category
            ORDER BY cnt DESC
        """)
        rows = cur.fetchall()
    return [{"category": r[0], "count": r[1]} for r in rows]


# Statik web dosyaları
import os as _os
_web_dir = _os.path.join(_os.path.dirname(__file__), "..", "web")
if _os.path.exists(_web_dir):
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=_web_dir, html=True), name="web")
