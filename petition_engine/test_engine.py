"""
test_engine.py — Dilekçe motorunu uçtan uca test eder.
Veritabanı bağlantısı ve API key gerektirir.

Kullanım:
  python test_engine.py                    # Tüm testler
  python test_engine.py mahkeme            # Sadece mahkeme dilekçesi
  python test_engine.py search "ihbar"     # Sadece semantik arama
"""

import os
import sys
import json
import logging
import psycopg as psycopg2
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scraper"))


def get_db():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise EnvironmentError("DATABASE_URL tanımlanmamış (.env dosyasını kontrol edin)")
    return psycopg2.connect(url)


# ── Test senaryoları ──────────────────────────────────────────────────────────

TEST_CASES = {
    "mahkeme": {
        "petition_type": "mahkeme",
        "talep": (
            "Müvekkilim 5 yıldır çalıştığı şirketten haksız yere işten çıkarıldı. "
            "İhbar ve kıdem tazminatı ödenmedi. İş mahkemesine dava açmak istiyoruz. "
            "Ücret 25.000 TL, kıdemi 5 yıl 3 ay."
        ),
        "category_hint": "İş Hukuku",
    },
    "ihtarname": {
        "petition_type": "ihtarname",
        "talep": (
            "Kiracım 3 aydır kira ödemiyor. Toplam 45.000 TL borcu var. "
            "Tahliye için ihtarname göndermek istiyorum. "
            "Kira sözleşmesi 2022 tarihli, aylık kira 15.000 TL."
        ),
        "category_hint": "Medeni Hukuk",
    },
    "idari": {
        "petition_type": "idari",
        "talep": (
            "Müvekkilimin inşaat ruhsatı belediye tarafından hukuka aykırı biçimde iptal edildi. "
            "İptal kararının iptali için idareye başvurmak istiyoruz. "
            "Karar tarihi 15.03.2024, taşınmaz İstanbul Kadıköy'de."
        ),
        "category_hint": "İdare Hukuku",
    },
    "icra": {
        "petition_type": "icra",
        "talep": (
            "Müvekkilimin alıcıya sattığı mallar için düzenlenen 75.000 TL'lik fatura "
            "vadesinden 60 gün geçmesine rağmen ödenmedi. "
            "İcra takibi başlatmak istiyoruz. Fatura tarihi 01.02.2024."
        ),
        "category_hint": "İcra Hukuku",
    },
}


def test_semantic_search(query: str = "iş sözleşmesi feshi"):
    """Semantik arama testini çalıştırır."""
    from embedder import semantic_search
    print(f"\n{'='*50}")
    print(f"SEMANTİK ARAMA TESTİ: '{query}'")
    print("="*50)
    conn = get_db()
    results = semantic_search(conn, query, top_k=5)
    conn.close()

    if not results:
        print("SONUÇ YOK — Veritabanı boş olabilir.")
        print("İpucu: 'python pipeline.py daily' ile kararname çekin.")
        return

    for i, r in enumerate(results, 1):
        print(f"\n#{i} Benzerlik: {r['similarity']:.3f}")
        print(f"   Kararname: {r['decree_title'][:70]}")
        print(f"   Gazete   : {r['gazette_number']} ({r['gazette_date']})")
        print(f"   Bölüm    : {r['madde_no']}")
        print(f"   İçerik   : {r['content'][:120]}...")


def test_petition(case_name: str):
    """Dilekçe üretimini test eder."""
    from engine import PetitionEngine, PetitionRequest

    case = TEST_CASES.get(case_name)
    if not case:
        print(f"Geçersiz test: {case_name}. Seçenekler: {list(TEST_CASES)}")
        return

    print(f"\n{'='*50}")
    print(f"DİLEKÇE TESTİ: {case_name.upper()}")
    print("="*50)

    conn = get_db()
    engine = PetitionEngine(conn)

    req = PetitionRequest(
        lawyer_id     = 1,          # Test avukatı
        petition_type = case["petition_type"],
        talep         = case["talep"],
        avukat_adi    = "Ahmet Yılmaz",
        baro          = "İstanbul",
        sicil         = "12345",
        category_hint = case.get("category_hint"),
        use_haiku     = True,       # Test için Haiku (daha hızlı ve ucuz)
    )

    print(f"\nTalep: {req.talep[:100]}...")
    print("\nDilekçe üretiliyor", end="", flush=True)

    try:
        # Streaming test
        full_text = ""
        for event in engine.generate_stream(req):
            if event["type"] == "chunk":
                print(".", end="", flush=True)
                full_text += event["data"]
            elif event["type"] == "meta":
                decrees = event["data"]["used_decrees"]
                print(f"\n\nKullanılan kararname sayısı: {len(decrees)}")
                for d in decrees:
                    print(f"  [{d['similarity']:.2f}] {d['title'][:60]}")
            elif event["type"] == "warning":
                print(f"\nUYARI: {event['data']}")
            elif event["type"] == "done":
                meta = event["data"]
                cost = meta["cost_usd"]
                print(f"\n\nMaliyet: ${cost:.5f} | Model: {meta['model']}")
                print(f"Token: {meta['input_tokens']} giriş, {meta['output_tokens']} çıkış")

        print("\n" + "-"*50)
        print("ÜRETİLEN DİLEKÇE:")
        print("-"*50)
        print(full_text)

    except Exception as e:
        print(f"\nHATA: {e}")
        raise
    finally:
        conn.close()


def test_all():
    """Tüm dilekçe türlerini test eder."""
    for case_name in TEST_CASES:
        test_petition(case_name)
        print("\n")


def check_env():
    """Ortam değişkenlerini kontrol eder."""
    required = ["DATABASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    missing  = [k for k in required if not os.getenv(k)]
    if missing:
        print(f"EKSİK .env DEĞERLERI: {missing}")
        print("'.env.example' dosyasını kopyalayın ve doldurun.")
        return False
    print("Ortam değişkenleri: OK")
    return True


def check_db():
    """Veritabanı bağlantısını ve tablo sayılarını kontrol eder."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM decrees")
            decrees = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM decree_chunks WHERE embedding IS NOT NULL")
            chunks = cur.fetchone()[0]
        conn.close()
        print(f"Veritabanı: OK | {decrees} kararname, {chunks} chunk (embedding'li)")
        return decrees > 0
    except Exception as e:
        print(f"Veritabanı HATA: {e}")
        return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd == "env":
        check_env()
    elif cmd == "db":
        check_db()
    elif cmd == "search":
        query = " ".join(sys.argv[2:]) or "iş sözleşmesi feshi"
        test_semantic_search(query)
    elif cmd in TEST_CASES:
        if check_env() and check_db():
            test_petition(cmd)
    elif cmd == "all":
        if check_env() and check_db():
            test_all()
    else:
        print(__doc__)
