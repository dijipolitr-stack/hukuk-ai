"""
scraper.py — Resmi Gazete kararname tarayıcısı
resmigazete.gov.tr adresinden günlük yeni kararnameleri çeker,
PDF indirir ve veritabanına kaydeder.
"""

import os
import re
import time
import logging
import hashlib
import requests
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dotenv import load_dotenv
import psycopg as psycopg2
from psycopg.rows import dict_row as RealDictCursorFactory

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

BASE_URL    = "https://www.resmigazete.gov.tr"
PDF_DIR     = Path(os.getenv("PDF_DIR", "./pdfs"))
PDF_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; HukukAI-Scraper/1.0; "
        "+mailto:admin@hukukai.com.tr)"
    )
}

# Kararname kategorisi tespiti için anahtar kelimeler
CATEGORY_KEYWORDS = {
    "İş Hukuku":     ["iş kanunu", "işçi", "işveren", "kıdem", "ihbar", "sgk",
                       "sosyal güvenlik", "toplu iş"],
    "Vergi Hukuku":  ["vergi", "kdv", "gelir vergisi", "kurumlar vergisi",
                       "gümrük", "harç", "damga"],
    "Ceza Hukuku":   ["türk ceza kanunu", "tck", "ceza", "suç", "kovuşturma",
                       "dava", "beraat", "mahkumiyet"],
    "İdare Hukuku":  ["idare", "belediye", "valilik", "bakanlık", "yönetmelik",
                       "tüzük", "genelge"],
    "Ticaret Hukuku":["ticaret", "şirket", "ttk", "iflas", "konkordato",
                       "anonim", "limited"],
    "İcra Hukuku":   ["icra", "iflas", "haciz", "alacak", "borç", "ödeme emri"],
    "Medeni Hukuk":  ["medeni", "aile", "miras", "velayet", "nafaka",
                       "boşanma", "evlilik"],
    "Anayasa":       ["anayasa", "temel haklar", "özgürlük", "cumhurbaşkanlığı kararnamesi"],
}


def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def detect_category(title: str, text: str = "") -> tuple[str, str]:
    """Başlık ve metne göre kategori + alt kategori döner."""
    combined = (title + " " + text[:500]).lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in combined for kw in keywords):
            return category, ""
    return "Diğer", ""


def already_scraped(conn, gazette_number: str, decree_number: str) -> bool:
    """Bu kararname daha önce kaydedildi mi?"""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM decrees WHERE gazette_number=%s AND decree_number=%s",
            (gazette_number, decree_number)
        )
        return cur.fetchone() is not None


def download_pdf(url: str, filename: str) -> Optional[Path]:
    """PDF indirir, yerel path döner."""
    dest = PDF_DIR / filename
    if dest.exists():
        log.info(f"  PDF zaten var: {filename}")
        return dest
    try:
        r = requests.get(url, headers=HEADERS, timeout=30, stream=True)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info(f"  PDF indirildi: {filename} ({dest.stat().st_size // 1024} KB)")
        return dest
    except Exception as e:
        log.warning(f"  PDF indirilemedi {url}: {e}")
        return None


def save_decree(conn, data: dict) -> Optional[int]:
    """Kararname kaydeder, ID döner."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO decrees
                (gazette_number, gazette_date, decree_number, title,
                 category, subcategory, source_url, pdf_path)
            VALUES
                (%(gazette_number)s, %(gazette_date)s, %(decree_number)s,
                 %(title)s, %(category)s, %(subcategory)s,
                 %(source_url)s, %(pdf_path)s)
            ON CONFLICT (gazette_number, decree_number) DO NOTHING
            RETURNING id
        """, data)
        row = cur.fetchone()
        conn.commit()
        return row[0] if row else None


def log_scrape(conn, gazette_number: str, gazette_date: date,
               status: str, found: int = 0, error: str = None):
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO scraper_logs
                (gazette_number, gazette_date, status, decrees_found, error_message)
            VALUES (%s, %s, %s, %s, %s)
        """, (gazette_number, gazette_date, status, found, error))
        conn.commit()


def parse_gazette_page(html: str, gazette_number: str,
                        gazette_date: date) -> list[dict]:
    """
    Gazete sayfasındaki kararname linklerini çıkarır.
    resmigazete.gov.tr'nin HTML yapısına göre yazılmıştır.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []

    # Ana içerik tablosu veya liste
    for link in soup.find_all("a", href=True):
        href = link["href"]
        text = link.get_text(strip=True)

        # Sadece kararname/kanun/yönetmelik linkleri
        if not any(kw in text.lower() for kw in
                   ["kararname", "kanun", "yönetmelik", "tebliğ",
                    "tüzük", "genelge", "karar"]):
            continue
        if not (href.endswith(".pdf") or "/pdf/" in href or "eskiler" in href):
            continue

        full_url = urljoin(BASE_URL, href)

        # Kararname numarasını başlıktan çıkarmaya çalış
        decree_no = ""
        no_match = re.search(r"(\d{4}/\d+|\d+)", text)
        if no_match:
            decree_no = no_match.group(1)
        else:
            # URL'den hash al
            decree_no = hashlib.md5(full_url.encode()).hexdigest()[:8]

        category, subcategory = detect_category(text)

        # PDF dosya adı
        safe_title = re.sub(r"[^\w\-]", "_", text[:60])
        pdf_filename = f"{gazette_date}_{gazette_number}_{safe_title[:40]}.pdf"

        items.append({
            "gazette_number":  gazette_number,
            "gazette_date":    gazette_date,
            "decree_number":   decree_no,
            "title":           text,
            "category":        category,
            "subcategory":     subcategory,
            "source_url":      full_url,
            "pdf_filename":    pdf_filename,
        })

    # Duplicate decree_number temizleme
    seen = set()
    unique = []
    for item in items:
        key = (item["gazette_number"], item["decree_number"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def scrape_date(target_date: date, conn) -> int:
    """
    Belirli bir tarihe ait Resmi Gazete sayfasını tarar.
    Bulunan kararname sayısını döner.
    """
    date_str     = target_date.strftime("%Y%m%d")
    gazette_url  = f"{BASE_URL}/{date_str}.htm"

    log.info(f"Tarih taranıyor: {target_date} → {gazette_url}")

    try:
        r = requests.get(gazette_url, headers=HEADERS, timeout=20)
        if r.status_code == 404:
            log.info(f"  Gazete bulunamadı (muhtemelen tatil günü): {target_date}")
            return 0
        r.raise_for_status()
        r.encoding = "utf-8"
    except requests.RequestException as e:
        log.error(f"  Sayfa alınamadı: {e}")
        log_scrape(conn, date_str, target_date, "error", error=str(e))
        return 0

    # Gazete numarasını sayfadan çıkar
    soup = BeautifulSoup(r.text, "html.parser")
    gazette_number = date_str  # fallback
    no_tag = soup.find(string=re.compile(r"sayı\s*:\s*\d+", re.I))
    if no_tag:
        m = re.search(r"(\d{5,})", no_tag)
        if m:
            gazette_number = m.group(1)

    items = parse_gazette_page(r.text, gazette_number, target_date)
    log.info(f"  {len(items)} kararname bulundu")

    saved = 0
    for item in items:
        if already_scraped(conn, item["gazette_number"], item["decree_number"]):
            log.info(f"  Atlandı (zaten var): {item['title'][:50]}")
            continue

        # PDF indir
        pdf_path = download_pdf(item["source_url"], item["pdf_filename"])
        item["pdf_path"] = str(pdf_path) if pdf_path else None
        del item["pdf_filename"]

        decree_id = save_decree(conn, item)
        if decree_id:
            log.info(f"  Kaydedildi [#{decree_id}]: {item['title'][:60]}")
            saved += 1
        time.sleep(0.5)  # Sunucuya nazik ol

    log_scrape(conn, gazette_number, target_date, "success", found=saved)
    return saved


def scrape_range(start_date: date, end_date: date):
    """Tarih aralığını tarar. İlk kurulum için kullanılır."""
    conn = get_db()
    total = 0
    current = start_date
    while current <= end_date:
        count = scrape_date(current, conn)
        total += count
        current += timedelta(days=1)
        time.sleep(1)
    conn.close()
    log.info(f"Tamamlandı. Toplam {total} kararname kaydedildi.")


def scrape_today():
    """Sadece bugünü tarar. Cron job için kullanılır."""
    conn = get_db()
    count = scrape_date(date.today(), conn)
    conn.close()
    log.info(f"Bugün {count} yeni kararname kaydedildi.")


def scrape_last_n_days(n: int = 7):
    """Son N günü tarar. Başlangıç senkronizasyonu için kullanılır."""
    conn = get_db()
    total = 0
    for i in range(n):
        d = date.today() - timedelta(days=i)
        total += scrape_date(d, conn)
        time.sleep(1)
    conn.close()
    log.info(f"Son {n} gün tamamlandı. {total} kararname.")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "today":
            scrape_today()
        elif sys.argv[1] == "last":
            days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
            scrape_last_n_days(days)
        elif sys.argv[1] == "range":
            # python scraper.py range 2024-01-01 2024-12-31
            s = datetime.strptime(sys.argv[2], "%Y-%m-%d").date()
            e = datetime.strptime(sys.argv[3], "%Y-%m-%d").date()
            scrape_range(s, e)
    else:
        scrape_today()
