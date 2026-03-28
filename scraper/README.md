# Hukuk AI — Kararname Pipeline

Resmi Gazete'den kararname çeken, metne dönüştüren ve
semantik arama için vektörleyen tam pipeline.

## Kurulum

```bash
cd scraper
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# .env dosyasını doldurun (DATABASE_URL, OPENAI_API_KEY)
```

## Veritabanı kurulumu

```bash
# PostgreSQL'de pgvector extension'ı aktif edin
psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Tabloları oluşturun
psql $DATABASE_URL -f schema.sql
```

DigitalOcean Managed PostgreSQL kullanıyorsanız pgvector
varsayılan olarak yüklüdür — sadece `CREATE EXTENSION` çalıştırın.

## İlk çalıştırma (tüm arşiv)

```bash
# Son 2 yıl (varsayılan)
python pipeline.py init

# Son 5 yıl
python pipeline.py init --years 5

# Sadece son 30 gün (test için)
python pipeline.py daily  # tekrar tekrar çalıştırın
```

## Günlük cron

```bash
# Scheduler'ı başlat (her gün 02:30'da çalışır)
python pipeline.py scheduler
```

Railway veya DO App Platform için `Procfile`:
```
worker: python pipeline.py scheduler
```

## Manuel komutlar

```bash
# Sadece bugünü tara
python pipeline.py daily

# Sadece parse + embed (scraper olmadan)
python pipeline.py process

# İstatistik görüntüle
python pipeline.py stats

# Semantik arama testi
python embedder.py search "iş sözleşmesi feshi ihbar süresi"
```

## Dosya yapısı

```
scraper/
├── schema.sql      — PostgreSQL + pgvector şeması
├── scraper.py      — Resmi Gazete HTML tarayıcı + PDF indiricisi
├── parser.py       — PDF → madde/bent bazlı chunk'lar
├── embedder.py     — OpenAI embedding + semantik arama
├── pipeline.py     — Orkestratör + cron scheduler
├── requirements.txt
└── .env.example
```

## Tahmini maliyet (test fazı)

| İşlem | Miktar | Maliyet |
|---|---|---|
| İlk arşiv embedding (10K kararname × ort. 20 chunk) | 200K chunk | ~$0.40 |
| Günlük yeni kararname embedding | ~5-10 chunk/gün | ~$0.00002/gün |
| PostgreSQL (DO, 1GB) | aylık | $15 |

## Sonraki adım

`petition_engine/` modülü — Claude API entegrasyonu ile
semantic search sonuçlarını dilekçeye dönüştürür.
