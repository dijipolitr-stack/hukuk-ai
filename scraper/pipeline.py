"""
pipeline.py — Ana orkestratör
Scraper → Parser → Embedder zincirini yönetir.
Hem tek seferlik toplu yükleme hem günlük cron için kullanılır.

Kullanım:
  python pipeline.py init          # İlk kurulum: son 2 yıl
  python pipeline.py init --years 5
  python pipeline.py daily         # Cron: sadece bugün
  python pipeline.py process       # Sadece parse + embed (scraper atla)
  python pipeline.py stats         # Veritabanı istatistikleri
"""

import os
import sys
import logging
import time
from datetime import date, timedelta

import psycopg as psycopg2
from psycopg.rows import dict_row as RealDictCursorFactory
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log"),
    ]
)
log = logging.getLogger(__name__)


def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))


def run_daily_pipeline():
    """
    Günlük cron görevi:
    1. Bugünün gazetesini tara
    2. Yeni PDF'leri parse et
    3. Embedding üret
    """
    log.info("=" * 50)
    log.info("Günlük pipeline başladı")
    conn = get_db()

    try:
        from scraper import scrape_date
        from parser import process_unprocessed
        from embedder import embed_unprocessed_chunks

        # 1. Scrape
        new_decrees = scrape_date(date.today(), conn)
        log.info(f"Scrape: {new_decrees} yeni kararname")

        # 2. Parse
        new_chunks = process_unprocessed(conn, limit=100)
        log.info(f"Parse: {new_chunks} yeni chunk")

        # 3. Embed
        embedded = embed_unprocessed_chunks(conn, limit=500)
        log.info(f"Embed: {embedded} chunk vektörlendi")

        log.info("Günlük pipeline tamamlandı.")

    except Exception as e:
        log.exception(f"Pipeline hatası: {e}")
    finally:
        conn.close()


def run_init_pipeline(years: int = 2):
    """
    İlk kurulum: belirtilen yıl sayısı kadar geriye gider.
    Her ay ayrı bağlantı açar — Neon timeout sorununu önler.
    """
    log.info(f"İLK KURULUM: Son {years} yıl taranıyor")

    from scraper import scrape_date
    from parser import process_unprocessed
    from embedder import embed_unprocessed_chunks

    end   = date.today()
    start = end.replace(year=end.year - years)

    # Gün gün tara — her gün için bağlantıyı yenile
    current = start
    total_decrees = 0
    while current <= end:
        conn = psycopg.connect(os.getenv("DATABASE_URL"))
        try:
            count = scrape_date(current, conn)
            total_decrees += count
        except Exception as e:
            log.warning(f"Scrape hatası {current}: {e}")
        finally:
            conn.close()
        current += timedelta(days=1)
        time.sleep(1)

    log.info(f"Scrape tamamlandı: {total_decrees} kararname")

    # Parse — her seferinde yeni bağlantı
    log.info("Parse başlıyor...")
    while True:
        conn = psycopg.connect(os.getenv("DATABASE_URL"))
        try:
            count = process_unprocessed(conn, limit=50)
        except Exception as e:
            log.warning(f"Parse hatası: {e}")
            count = 0
        finally:
            conn.close()
        if count == 0:
            break
        time.sleep(2)

    # Embed — her seferinde yeni bağlantı
    log.info("Embedding başlıyor...")
    while True:
        conn = psycopg.connect(os.getenv("DATABASE_URL"))
        try:
            count = embed_unprocessed_chunks(conn, limit=200)
        except Exception as e:
            log.warning(f"Embed hatası: {e}")
            count = 0
        finally:
            conn.close()
        if count == 0:
            break
        time.sleep(2)

    log.info("İlk kurulum tamamlandı!")
    print_stats()


def run_process_only():
    """Scraper çalıştırmadan, mevcut PDF'leri parse + embed eder."""
    conn = get_db()
    from parser import process_unprocessed
    from embedder import embed_unprocessed_chunks

    log.info("Parse başlıyor...")
    process_unprocessed(conn, limit=200)
    log.info("Embedding başlıyor...")
    embed_unprocessed_chunks(conn, limit=1000)
    conn.close()


def print_stats():
    """Veritabanı durumunu özetler."""
    conn = get_db()
    with conn.cursor(row_factory=RealDictCursorFactory) as cur:
        cur.execute("SELECT COUNT(*) AS total FROM decrees")
        total = cur.fetchone()["total"]

        cur.execute("SELECT COUNT(*) AS processed FROM decrees WHERE is_processed = TRUE")
        processed = cur.fetchone()["processed"]

        cur.execute("SELECT COUNT(*) AS chunks FROM decree_chunks")
        chunks = cur.fetchone()["chunks"]

        cur.execute("SELECT COUNT(*) AS embedded FROM decree_chunks WHERE embedding IS NOT NULL")
        embedded = cur.fetchone()["embedded"]

        cur.execute("""
            SELECT category, COUNT(*) AS cnt
            FROM decrees
            GROUP BY category
            ORDER BY cnt DESC
        """)
        categories = cur.fetchall()

        cur.execute("SELECT MIN(gazette_date), MAX(gazette_date) FROM decrees")
        date_range = cur.fetchone()

    conn.close()

    print("\n" + "=" * 45)
    print("VERİTABANI İSTATİSTİKLERİ")
    print("=" * 45)
    print(f"Kararname (toplam)   : {total:,}")
    print(f"Kararname (işlenmiş) : {processed:,}  ({100*processed//max(total,1)}%)")
    print(f"Chunk (toplam)       : {chunks:,}")
    print(f"Chunk (embedding)    : {embedded:,}  ({100*embedded//max(chunks,1)}%)")
    if date_range["min"]:
        print(f"Tarih aralığı        : {date_range['min']} → {date_range['max']}")
    print("\nKategori dağılımı:")
    for row in categories:
        print(f"  {row['category']:<25} {row['cnt']:>5}")
    print("=" * 45 + "\n")


def start_scheduler():
    """
    APScheduler ile günlük cron başlatır.
    Her gün 02:30'da çalışır.
    Docker/Railway için ideal.
    """
    scheduler = BlockingScheduler(timezone="Europe/Istanbul")
    scheduler.add_job(
        run_daily_pipeline,
        "cron",
        hour=2,
        minute=30,
        id="daily_pipeline",
    )
    log.info("Scheduler başlatıldı. Her gün 02:30'da çalışacak.")
    log.info("İlk çalıştırmadan önce 'python pipeline.py init' komutunu unutmayın.")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        log.info("Scheduler durduruldu.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "init":
        years = 2
        if "--years" in sys.argv:
            idx = sys.argv.index("--years")
            years = int(sys.argv[idx + 1])
        run_init_pipeline(years=years)

    elif cmd == "daily":
        run_daily_pipeline()

    elif cmd == "process":
        run_process_only()

    elif cmd == "stats":
        print_stats()

    elif cmd == "scheduler":
        start_scheduler()

    else:
        print(__doc__)
