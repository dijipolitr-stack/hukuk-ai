-- pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Hukuk firmaları
CREATE TABLE IF NOT EXISTS firms (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT UNIQUE NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Avukatlar
CREATE TABLE IF NOT EXISTS lawyers (
    id          SERIAL PRIMARY KEY,
    firm_id     INT REFERENCES firms(id) ON DELETE SET NULL,
    full_name   TEXT NOT NULL,
    bar_number  TEXT UNIQUE,
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Kararnameler (üst kayıt)
CREATE TABLE IF NOT EXISTS decrees (
    id              SERIAL PRIMARY KEY,
    gazette_number  TEXT NOT NULL,          -- Resmi Gazete sayısı
    gazette_date    DATE NOT NULL,          -- Yayın tarihi
    decree_number   TEXT,                  -- Kararname/Kanun numarası
    title           TEXT NOT NULL,         -- Başlık
    category        TEXT,                  -- İş, Vergi, Ceza, İdare, vb.
    subcategory     TEXT,
    source_url      TEXT,                  -- Resmi Gazete linki
    pdf_path        TEXT,                  -- Yerel PDF yolu
    raw_text        TEXT,                  -- Ham metin (tüm belge)
    page_count      INT,
    is_processed    BOOLEAN DEFAULT FALSE, -- Embedding yapıldı mı
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(gazette_number, decree_number)
);

-- Kararname bölümleri (madde/bent bazlı chunk'lar)
CREATE TABLE IF NOT EXISTS decree_chunks (
    id          SERIAL PRIMARY KEY,
    decree_id   INT NOT NULL REFERENCES decrees(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,              -- Sıra numarası
    chunk_type  TEXT,                      -- 'madde', 'bent', 'fikra', 'genel'
    madde_no    TEXT,                      -- "Madde 5" gibi
    content     TEXT NOT NULL,            -- Chunk metni
    embedding   vector(1536),             -- OpenAI text-embedding-3-small
    token_count INT,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Dilekçeler (ileride kullanılacak)
CREATE TABLE IF NOT EXISTS petitions (
    id              SERIAL PRIMARY KEY,
    lawyer_id       INT NOT NULL REFERENCES lawyers(id),
    petition_type   TEXT NOT NULL,  -- 'mahkeme','ihtarname','idari','icra'
    subject         TEXT NOT NULL,
    user_input      TEXT NOT NULL,  -- Avukatın talebi (ses transkripsiyonu veya yazı)
    generated_text  TEXT,           -- Üretilen dilekçe
    used_decree_ids INT[],          -- Hangi kararnameler kullanıldı
    status          TEXT DEFAULT 'draft',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Scraper log (hangi gazette'ler tarandı)
CREATE TABLE IF NOT EXISTS scraper_logs (
    id              SERIAL PRIMARY KEY,
    gazette_number  TEXT,
    gazette_date    DATE,
    status          TEXT,   -- 'success', 'error', 'skipped'
    decrees_found   INT DEFAULT 0,
    error_message   TEXT,
    scraped_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Hızlı arama için index'ler
CREATE INDEX IF NOT EXISTS idx_decrees_date     ON decrees(gazette_date DESC);
CREATE INDEX IF NOT EXISTS idx_decrees_category ON decrees(category);
CREATE INDEX IF NOT EXISTS idx_decrees_processed ON decrees(is_processed) WHERE is_processed = FALSE;
CREATE INDEX IF NOT EXISTS idx_chunks_decree    ON decree_chunks(decree_id);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON decree_chunks USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
