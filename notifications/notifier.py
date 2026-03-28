"""
notifier.py — Bildirim servisi
Yeni kararname tespit edilince ilgili avukatlara bildirim oluşturur.
Pipeline.py tarafından her scrape sonrası çağrılır.
"""

import os
import logging
from datetime import date, datetime, timedelta
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def get_db():
    return psycopg.connect(os.getenv("DATABASE_URL"))


# ── Bildirim oluşturma ────────────────────────────────────────────────────────

def create_notifications_for_decree(conn, decree_id: int) -> int:
    """
    Yeni bir kararname için ilgili avukatlara bildirim oluşturur.
    Avukatın kategori tercihleriyle eşleşen veya tercih yoksa herkese gönderir.
    Oluşturulan bildirim sayısını döner.
    """
    # Kararname bilgisini al
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT id, title, category, gazette_number, gazette_date FROM decrees WHERE id = %s",
            (decree_id,)
        )
        decree = cur.fetchone()

    if not decree:
        return 0

    category = decree["category"] or "Genel"
    title    = f"Yeni {category} Kararnamesi"
    body     = f"{decree['title'][:120]} — Resmi Gazete {decree['gazette_number']} ({decree['gazette_date']})"

    # İlgili avukatları bul
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT l.id AS lawyer_id
            FROM lawyers l
            LEFT JOIN lawyer_preferences lp ON lp.lawyer_id = l.id
            WHERE l.is_active = TRUE
              AND (
                lp.categories IS NULL          -- Tercih ayarlamamış → herkese
                OR lp.categories = '{}'        -- Boş tercih → herkese
                OR %s = ANY(lp.categories)     -- Kategori eşleşiyor
              )
        """, (category,))
        lawyers = cur.fetchall()

    if not lawyers:
        return 0

    # Toplu bildirim ekle
    with conn.cursor() as cur:
        cur.executemany("""
            INSERT INTO notifications (lawyer_id, decree_id, title, body, category)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
        """, [
            (l["lawyer_id"], decree_id, title, body, category)
            for l in lawyers
        ])
        conn.commit()

    log.info(f"  {len(lawyers)} avukata bildirim oluşturuldu: {decree['title'][:60]}")
    return len(lawyers)


def notify_new_decrees(conn, since_hours: int = 24) -> int:
    """
    Son N saatte eklenen işlenmemiş kararnameler için bildirim oluşturur.
    Pipeline'ın günlük çalışmasından sonra tetiklenir.
    """
    since = datetime.now() - timedelta(hours=since_hours)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT d.id FROM decrees d
            LEFT JOIN notifications n ON n.decree_id = d.id
            WHERE d.created_at >= %s
              AND n.id IS NULL   -- Henüz bildirim oluşturulmamış
            ORDER BY d.gazette_date DESC
        """, (since,))
        new_decrees = cur.fetchall()

    total = 0
    for row in new_decrees:
        total += create_notifications_for_decree(conn, row["id"])

    log.info(f"Bildirim turu: {len(new_decrees)} kararname, {total} bildirim")
    return total


# ── Avukat tercihleri ─────────────────────────────────────────────────────────

def get_preferences(conn, lawyer_id: int) -> dict:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM lawyer_preferences WHERE lawyer_id = %s",
            (lawyer_id,)
        )
        row = cur.fetchone()
    return dict(row) if row else {
        "lawyer_id":   lawyer_id,
        "categories":  [],
        "email_digest": True,
        "digest_hour":  8,
    }


def save_preferences(conn, lawyer_id: int, categories: list[str],
                     email_digest: bool = True, digest_hour: int = 8):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO lawyer_preferences (lawyer_id, categories, email_digest, digest_hour)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (lawyer_id) DO UPDATE SET
                categories   = EXCLUDED.categories,
                email_digest = EXCLUDED.email_digest,
                digest_hour  = EXCLUDED.digest_hour,
                updated_at   = NOW()
        """, (lawyer_id, categories, email_digest, digest_hour))
        conn.commit()
    log.info(f"Tercihler kaydedildi: avukat #{lawyer_id}, kategoriler: {categories}")


# ── Bildirim okuma ────────────────────────────────────────────────────────────

def get_notifications(conn, lawyer_id: int,
                      unread_only: bool = False, limit: int = 30) -> list[dict]:
    where = "WHERE n.lawyer_id = %s"
    if unread_only:
        where += " AND n.is_read = FALSE"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"""
            SELECT n.id, n.title, n.body, n.category,
                   n.is_read, n.created_at, n.decree_id
            FROM notifications n
            {where}
            ORDER BY n.created_at DESC
            LIMIT %s
        """, (lawyer_id, limit))
        return [dict(r) for r in cur.fetchall()]


def get_unread_count(conn, lawyer_id: int) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM notifications WHERE lawyer_id = %s AND is_read = FALSE",
            (lawyer_id,)
        )
        return cur.fetchone()[0]


def mark_read(conn, lawyer_id: int, notification_ids: Optional[list[int]] = None):
    """Bildirimleri okundu olarak işaretle. ids=None ise hepsini işaretle."""
    with conn.cursor() as cur:
        if notification_ids:
            cur.execute("""
                UPDATE notifications SET is_read = TRUE
                WHERE lawyer_id = %s AND id = ANY(%s)
            """, (lawyer_id, notification_ids))
        else:
            cur.execute(
                "UPDATE notifications SET is_read = TRUE WHERE lawyer_id = %s",
                (lawyer_id,)
            )
        conn.commit()
