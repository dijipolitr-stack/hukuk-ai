"""
mailer.py — Günlük e-posta özeti
Her sabah avukatlara o günkü yeni kararnamelerin özetini gönderir.
SMTP veya SendGrid ile çalışır.
"""

import os
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date, datetime, timedelta

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)

# SMTP ayarları (.env'den okunur)
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASS     = os.getenv("SMTP_PASS", "")
SMTP_FROM     = os.getenv("SMTP_FROM", "Hukuk AI <bildirim@hukukai.com.tr>")
APP_URL       = os.getenv("APP_URL", "http://localhost:8000")


def get_db():
    return psycopg.connect(os.getenv("DATABASE_URL"))


def build_digest_html(lawyer_name: str, decrees: list[dict], today: date) -> str:
    """Günlük özet e-postası HTML şablonu."""
    decree_rows = ""
    for d in decrees:
        cat_color = {
            "İş Hukuku":    "#2D4A8A",
            "Vergi Hukuku": "#7B3FA0",
            "İdare Hukuku": "#1D7A4F",
            "Ceza Hukuku":  "#C0392B",
            "İcra Hukuku":  "#B87333",
            "Medeni Hukuk": "#1A5C8A",
            "Anayasa":      "#0f1e3c",
        }.get(d["category"], "#5A6482")

        decree_rows += f"""
        <tr>
          <td style="padding:12px 16px;border-bottom:1px solid #eee;">
            <span style="display:inline-block;padding:2px 8px;border-radius:4px;
                         background:{cat_color}20;color:{cat_color};
                         font-size:11px;font-weight:600;margin-bottom:6px">
              {d['category'] or 'Genel'}
            </span><br>
            <strong style="font-size:14px;color:#1a2238">{d['title'][:100]}</strong><br>
            <span style="font-size:12px;color:#8a94a8">
              Resmi Gazete {d['gazette_number']} — {d['gazette_date']}
            </span>
          </td>
        </tr>"""

    date_str = today.strftime("%-d %B %Y") if hasattr(today, 'strftime') else str(today)

    return f"""
<!DOCTYPE html>
<html lang="tr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f6fb;font-family:'Helvetica Neue',Arial,sans-serif">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:32px 16px">
<table width="580" cellpadding="0" cellspacing="0" style="max-width:580px">

  <!-- Header -->
  <tr><td style="background:#0f1e3c;border-radius:12px 12px 0 0;padding:28px 32px;text-align:center">
    <div style="font-size:28px">⚖</div>
    <h1 style="color:#c8a45a;font-size:22px;margin:8px 0 4px;font-family:Georgia,serif">Hukuk AI</h1>
    <p style="color:rgba(255,255,255,.6);font-size:12px;margin:0;letter-spacing:2px;text-transform:uppercase">
      Günlük Kararname Özeti
    </p>
  </td></tr>

  <!-- Tarih bandı -->
  <tr><td style="background:#c8a45a;padding:10px 32px;text-align:center">
    <span style="color:#0f1e3c;font-size:13px;font-weight:600">{date_str} — Resmi Gazete</span>
  </td></tr>

  <!-- Selamlama -->
  <tr><td style="background:#fff;padding:24px 32px 16px">
    <p style="color:#1a2238;font-size:15px;margin:0">
      Merhaba <strong>Av. {lawyer_name}</strong>,
    </p>
    <p style="color:#5a6482;font-size:14px;margin:10px 0 0;line-height:1.6">
      Bugün Resmi Gazete'de <strong>{len(decrees)} yeni kararname/kanun</strong> yayımlandı.
      Kategori tercihlerinizle ilgili olanlar aşağıda listelenmektedir.
    </p>
  </td></tr>

  <!-- Kararname listesi -->
  <tr><td style="background:#fff;padding:0 32px 8px">
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #eee;border-radius:8px;overflow:hidden">
      {decree_rows}
    </table>
  </td></tr>

  <!-- CTA butonu -->
  <tr><td style="background:#fff;padding:20px 32px 28px;text-align:center">
    <a href="{APP_URL}/index.html"
       style="display:inline-block;padding:13px 32px;background:#0f1e3c;
              color:#c8a45a;text-decoration:none;border-radius:8px;
              font-size:14px;font-weight:600;letter-spacing:.5px">
      Paneli Aç ve Dilekçe Oluştur
    </a>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f4f6fb;border-radius:0 0 12px 12px;
                 padding:20px 32px;text-align:center">
    <p style="color:#9ba3be;font-size:12px;margin:0;line-height:1.7">
      Bu e-postayı almak istemiyorsanız panel ayarlarından bildirim tercihlerinizi güncelleyebilirsiniz.<br>
      <strong>Hukuk AI</strong> — Yapay Zeka Destekli Dilekçe Sistemi
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    """SMTP ile e-posta gönderir. Başarı durumunu döner."""
    if not SMTP_USER or not SMTP_PASS:
        log.warning("SMTP ayarları eksik — e-posta gönderilmedi")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_FROM, to_email, msg.as_string())
        log.info(f"  E-posta gönderildi: {to_email}")
        return True
    except Exception as e:
        log.error(f"  E-posta hatası {to_email}: {e}")
        return False


def log_email(conn, lawyer_id: int, email: str, subject: str, status: str):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO email_logs (lawyer_id, email, subject, status)
            VALUES (%s, %s, %s, %s)
        """, (lawyer_id, email, subject, status))
        conn.commit()


def send_daily_digests() -> int:
    """
    Tüm avukatlara günlük özet e-postası gönderir.
    Her sabah 08:00'de çalıştırılır (pipeline scheduler'a eklenir).
    Gönderilen e-posta sayısını döner.
    """
    conn  = get_db()
    today = date.today()
    sent  = 0

    # E-posta özeti açık olan aktif avukatları bul
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            SELECT l.id, l.full_name, l.email,
                   COALESCE(lp.categories, '{}') AS categories
            FROM lawyers l
            LEFT JOIN lawyer_preferences lp ON lp.lawyer_id = l.id
            WHERE l.is_active = TRUE
              AND (lp.email_digest IS NULL OR lp.email_digest = TRUE)
        """)
        lawyers = cur.fetchall()

    log.info(f"Günlük özet: {len(lawyers)} avukata gönderilecek")

    for lawyer in lawyers:
        # Bu avukatın kategorilerine uyan bugünkü kararnameleri bul
        categories = lawyer["categories"] or []
        with conn.cursor(row_factory=dict_row) as cur:
            if categories:
                cur.execute("""
                    SELECT title, category, gazette_number, gazette_date
                    FROM decrees
                    WHERE gazette_date = %s AND category = ANY(%s)
                    ORDER BY category, title
                """, (today, categories))
            else:
                cur.execute("""
                    SELECT title, category, gazette_number, gazette_date
                    FROM decrees
                    WHERE gazette_date = %s
                    ORDER BY category, title
                """, (today,))
            decrees = [dict(r) for r in cur.fetchall()]

        if not decrees:
            log.info(f"  {lawyer['email']}: bugün ilgili kararname yok, atlandı")
            continue

        html    = build_digest_html(lawyer["full_name"], decrees, today)
        subject = f"[Hukuk AI] {today.strftime('%d.%m.%Y')} Resmi Gazete — {len(decrees)} yeni kararname"
        ok      = send_email(lawyer["email"], subject, html)
        log_email(conn, lawyer["id"], lawyer["email"], subject, "sent" if ok else "failed")
        if ok:
            sent += 1

    conn.close()
    log.info(f"Günlük özet tamamlandı: {sent}/{len(lawyers)} e-posta gönderildi")
    return sent


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Test: python mailer.py test av@test.com
        email = sys.argv[2] if len(sys.argv) > 2 else SMTP_USER
        conn  = get_db()
        html  = build_digest_html("Test Avukat", [
            {"title": "Test Kararname — İş Kanunu Değişikliği", "category": "İş Hukuku",
             "gazette_number": "32500", "gazette_date": str(date.today())},
        ], date.today())
        ok = send_email(email, "[Hukuk AI] Test E-postası", html)
        print("Gönderildi!" if ok else "Hata — SMTP ayarlarını kontrol edin")
        conn.close()
    else:
        send_daily_digests()
