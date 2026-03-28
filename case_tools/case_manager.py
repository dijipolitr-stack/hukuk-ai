"""
case_manager.py — Dava yönetimi, süre takibi ve strateji asistanı
"""

import os
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import anthropic
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-5"

# Süre türleri ve varsayılan gün sayıları
DEADLINE_TYPES = {
    "hearing":   {"label": "Duruşma Tarihi",          "days": 0,   "color": "#2D4A8A"},
    "appeal":    {"label": "Temyiz Süresi",            "days": 30,  "color": "#7B3FA0"},
    "objection": {"label": "İtiraz Süresi",            "days": 14,  "color": "#C0392B"},
    "statute":   {"label": "Dava Açma Zamanaşımı",     "days": 365, "color": "#B87333"},
    "payment":   {"label": "Ödeme Vadesi",             "days": 0,   "color": "#1D7A4F"},
    "contract":  {"label": "Sözleşme Bitiş Tarihi",   "days": 0,   "color": "#888780"},
}

def get_db():
    return psycopg.connect(os.getenv("DATABASE_URL"))


# ── Dava CRUD ─────────────────────────────────────────────────────────────────

def create_case(conn, lawyer_id: int, data: dict) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO cases
                (lawyer_id, case_number, title, case_type, court,
                 plaintiff, defendant, subject, filed_date, notes)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            lawyer_id,
            data.get("case_number"),
            data["title"],
            data.get("case_type", "mahkeme"),
            data.get("court"),
            data.get("plaintiff"),
            data.get("defendant"),
            data.get("subject"),
            data.get("filed_date"),
            data.get("notes"),
        ))
        case_id = cur.fetchone()[0]
        conn.commit()
    log.info(f"Dava oluşturuldu [#{case_id}]: {data['title']}")
    return case_id


def get_cases(conn, lawyer_id: int, status: str = "active") -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT c.*,
                COUNT(cd.id) FILTER (WHERE cd.is_done = FALSE) AS pending_deadlines,
                MIN(cd.due_date) FILTER (WHERE cd.is_done = FALSE) AS next_deadline
            FROM cases c
            LEFT JOIN case_deadlines cd ON cd.case_id = c.id
            WHERE c.lawyer_id = %s AND c.status = %s
            GROUP BY c.id
            ORDER BY next_deadline ASC NULLS LAST, c.created_at DESC
        """, (lawyer_id, status))
        return [dict(r) for r in cur.fetchall()]


def get_case(conn, case_id: int, lawyer_id: int) -> Optional[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM cases WHERE id=%s AND lawyer_id=%s",
            (case_id, lawyer_id)
        )
        row = cur.fetchone()
    return dict(row) if row else None


# ── Süre takibi ───────────────────────────────────────────────────────────────

def add_deadline(conn, case_id: int, lawyer_id: int, data: dict) -> int:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO case_deadlines
                (case_id, lawyer_id, deadline_type, title, due_date,
                 description, reminder_days)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (
            case_id,
            lawyer_id,
            data["deadline_type"],
            data["title"],
            data["due_date"],
            data.get("description"),
            data.get("reminder_days", 3),
        ))
        dl_id = cur.fetchone()[0]
        conn.commit()
    return dl_id


def get_upcoming_deadlines(conn, lawyer_id: int,
                            days_ahead: int = 30) -> list[dict]:
    """Yaklaşan süreleri getirir."""
    until = date.today() + timedelta(days=days_ahead)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT cd.*, c.title AS case_title, c.case_number,
                   cd.due_date - CURRENT_DATE AS days_remaining
            FROM case_deadlines cd
            JOIN cases c ON c.id = cd.case_id
            WHERE cd.lawyer_id = %s
              AND cd.is_done = FALSE
              AND cd.due_date <= %s
              AND cd.due_date >= CURRENT_DATE
            ORDER BY cd.due_date ASC
        """, (lawyer_id, until))
        return [dict(r) for r in cur.fetchall()]


def get_overdue_deadlines(conn, lawyer_id: int) -> list[dict]:
    """Geçmiş ve tamamlanmamış süreleri getirir."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT cd.*, c.title AS case_title, c.case_number,
                   CURRENT_DATE - cd.due_date AS days_overdue
            FROM case_deadlines cd
            JOIN cases c ON c.id = cd.case_id
            WHERE cd.lawyer_id = %s
              AND cd.is_done = FALSE
              AND cd.due_date < CURRENT_DATE
            ORDER BY cd.due_date ASC
        """, (lawyer_id,))
        return [dict(r) for r in cur.fetchall()]


def mark_deadline_done(conn, deadline_id: int, lawyer_id: int):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE case_deadlines SET is_done = TRUE
            WHERE id = %s AND lawyer_id = %s
        """, (deadline_id, lawyer_id))
        conn.commit()


def check_and_notify_deadlines(conn) -> int:
    """
    Bildirim günü gelen süreleri tespit eder, avukatlara bildirim oluşturur.
    Her sabah pipeline scheduler tarafından çağrılır.
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "notifications"))
    from notifier import create_notifications_for_decree

    today = date.today()
    notified = 0

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT cd.*, c.title AS case_title, l.id AS lawyer_id
            FROM case_deadlines cd
            JOIN cases c ON c.id = cd.case_id
            JOIN lawyers l ON l.id = cd.lawyer_id
            WHERE cd.is_done = FALSE
              AND cd.notified = FALSE
              AND cd.due_date - cd.reminder_days <= %s
              AND cd.due_date >= %s
        """, (today, today))
        deadlines = cur.fetchall()

    for dl in deadlines:
        days_left = (dl["due_date"] - today).days
        urgency   = "BUGÜN" if days_left == 0 else f"{days_left} gün kaldı"

        # Bildirim oluştur
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO notifications
                    (lawyer_id, title, body, category)
                VALUES (%s, %s, %s, 'Süre Takibi')
            """, (
                dl["lawyer_id"],
                f"⏰ {dl['title']} — {urgency}",
                f"{dl['case_title']} davası: {dl['due_date'].strftime('%d.%m.%Y')} tarihli süre",
            ))
            cur.execute(
                "UPDATE case_deadlines SET notified = TRUE WHERE id = %s",
                (dl["id"],)
            )
            conn.commit()
        notified += 1
        log.info(f"Süre bildirimi: {dl['title']} — {dl['case_title']}")

    return notified


# ── Dava stratejisi asistanı ──────────────────────────────────────────────────

STRATEGY_SYSTEM = """Sen deneyimli bir Türk hukuk stratejisti ve avukatısın.
Sana bir dava özeti verilecek. Şu analizi yap:

1. DAVA DEĞERLENDİRMESİ
   - Hukuki nitelik ve uygulanacak mevzuat
   - Güçlü yanlar (avantajlar)
   - Zayıf yanlar ve riskler

2. KAZANMA OLASILIĞI
   - Yüksek / Orta / Düşük (gerekçesiyle)
   - Belirleyici faktörler

3. ÖNERİLEN STRATEJİ
   - Öncelikli eylem planı (madde madde)
   - Toplanması gereken deliller
   - Dikkat edilmesi gereken süreler

4. ALTERNATİF ÇÖZÜMLER
   - Uzlaşma/arabuluculuk uygun mu?
   - Risk/fayda analizi

5. EMSAL KARARLAR
   - Sağlanan içtihatlardan stratejiye katkı sağlayanlar

Analiz net, pratik ve avukata yol gösterici olsun."""


def analyze_strategy(
    conn,
    lawyer_id:    int,
    case_summary: str,
    case_id:      Optional[int] = None,
    category:     str = "",
) -> dict:
    """
    Dava stratejisi analizi yapar.
    İlgili içtihatları bulur, Claude ile stratejik analiz üretir.
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))
    from embedder import semantic_search

    sys.path.insert(0, os.path.dirname(__file__))
    from precedent_scraper import search_precedents

    # İlgili kararname ve içtihat ara
    decree_results    = semantic_search(conn, case_summary, top_k=5, category_filter=category or None)
    precedent_results = search_precedents(conn, case_summary, category=category, top_k=5)

    # Bağlam metni oluştur
    context_parts = []
    if decree_results:
        context_parts.append("=== İLGİLİ MEVZUAT ===")
        for r in decree_results:
            context_parts.append(
                f"• {r['decree_title']} ({r['gazette_date']})\n"
                f"  {r['madde_no']}: {r['content'][:200]}"
            )

    if precedent_results:
        context_parts.append("\n=== İLGİLİ EMSAL KARARLAR ===")
        for r in precedent_results:
            context_parts.append(
                f"• {r['court']} {r.get('chamber','')} — Karar: {r.get('decision_number','')}\n"
                f"  {r.get('summary','')[:200]}"
            )

    context = "\n".join(context_parts) if context_parts else "İlgili içtihat ve mevzuat bulunamadı."

    # Claude ile analiz
    client   = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model      = CLAUDE_MODEL,
        max_tokens = 2000,
        system     = STRATEGY_SYSTEM,
        messages   = [{
            "role": "user",
            "content": (
                f"DAVA ÖZETİ:\n{case_summary}\n\n"
                f"İLGİLİ MEVZUAT VE İÇTİHATLAR:\n{context}"
            ),
        }],
    )

    analysis = response.content[0].text
    cost     = (
        response.usage.input_tokens  * 3.0  / 1e6 +
        response.usage.output_tokens * 15.0 / 1e6
    )

    # Kazanma olasılığını tespit et
    win_prob = "Orta"
    if "yüksek" in analysis.lower()[:500]:
        win_prob = "Yüksek"
    elif "düşük" in analysis.lower()[:500]:
        win_prob = "Düşük"

    # Kaydet
    used_precedent_ids = [r["id"] for r in precedent_results if r.get("id")]
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO strategy_analyses
                (case_id, lawyer_id, case_summary, analysis,
                 used_precedents, win_probability)
            VALUES (%s,%s,%s,%s,%s,%s)
            RETURNING id
        """, (case_id, lawyer_id, case_summary, analysis,
               used_precedent_ids, win_prob))
        analysis_id = cur.fetchone()[0]
        conn.commit()

    log.info(f"Strateji analizi [#{analysis_id}] | ${cost:.4f}")

    return {
        "analysis_id":   analysis_id,
        "analysis":      analysis,
        "win_probability": win_prob,
        "used_decrees":  decree_results[:3],
        "used_precedents": precedent_results[:3],
        "cost_usd":      round(cost, 5),
        "input_tokens":  response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
