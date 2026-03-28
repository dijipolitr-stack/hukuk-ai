"""
parser.py — PDF metin çıkartma ve madde/bent bazlı chunking
İndirilen kararname PDF'lerinden metin çıkarır,
madde ve bentlere böler, veritabanını günceller.
"""

import os
import re
import logging
from pathlib import Path
from typing import Generator

import pdfplumber
from dotenv import load_dotenv
import psycopg as psycopg2

load_dotenv()
log = logging.getLogger(__name__)

# Chunk başına maksimum karakter (embedding model limiti)
MAX_CHUNK_CHARS = 1500
MIN_CHUNK_CHARS = 80   # Çok kısa chunk'ları atla


# --- Madde/bent tespit pattern'leri ---

MADDE_PATTERNS = [
    re.compile(r"^MADDE\s+(\d+)\s*[–\-—]?\s*(.{0,120})", re.MULTILINE | re.IGNORECASE),
    re.compile(r"^Madde\s+(\d+)\s*[–\-—]?\s*(.{0,120})", re.MULTILINE),
    re.compile(r"^(\d+)\.\s+MADDE\s*[–\-—]?\s*(.{0,120})", re.MULTILINE | re.IGNORECASE),
]

BENT_PATTERN = re.compile(
    r"^([a-zçğıöşü])\)\s+(.+?)(?=^[a-zçğıöşü]\)|^MADDE|\Z)",
    re.MULTILINE | re.DOTALL
)

FIKRA_PATTERN = re.compile(
    r"^\((\d+)\)\s+(.+?)(?=^\(\d+\)|^MADDE|\Z)",
    re.MULTILINE | re.DOTALL
)


def extract_text_from_pdf(pdf_path: str) -> tuple[str, int]:
    """
    pdfplumber ile PDF'den metin çıkarır.
    (ham_metin, sayfa_sayısı) döner.
    """
    text_parts = []
    page_count = 0
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages:
                page_text = page.extract_text(
                    x_tolerance=2,
                    y_tolerance=3,
                    layout=True,
                )
                if page_text:
                    text_parts.append(page_text)
    except Exception as e:
        log.error(f"PDF okuma hatası {pdf_path}: {e}")
        return "", 0

    full_text = "\n".join(text_parts)
    full_text = clean_text(full_text)
    return full_text, page_count


def clean_text(text: str) -> str:
    """PDF'den gelen ham metni temizler."""
    # Başlık/sayfa numarası kalıplarını kaldır
    text = re.sub(r"Resmî Gazete\s+Sayı\s*:\s*\d+", "", text)
    text = re.sub(r"\d+\s*/\s*\d+\s*Sayfa", "", text)
    text = re.sub(r"www\.resmigazete\.gov\.tr", "", text)
    # Çoklu boşluk
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Tireleri düzelt (OCR hatası)
    text = re.sub(r"([a-züğışçöA-ZÜĞİŞÇÖ])\s*-\s*\n\s*([a-züğışçöa-z])", r"\1\2", text)
    return text.strip()


def split_into_chunks(text: str) -> Generator[dict, None, None]:
    """
    Metni madde/bent bazlı anlamlı chunk'lara böler.
    Her chunk: {chunk_type, madde_no, content} sözlüğü döner.
    """
    if not text:
        return

    # Önce maddeleri bul
    madde_splits = []
    for pattern in MADDE_PATTERNS:
        madde_splits = list(pattern.finditer(text))
        if madde_splits:
            break

    if not madde_splits:
        # Madde bulunamadı → paragraf bazlı böl
        yield from split_by_paragraphs(text)
        return

    # Madde aralıklarını çıkar
    for i, match in enumerate(madde_splits):
        madde_no = match.group(1)
        start    = match.start()
        end      = madde_splits[i + 1].start() if i + 1 < len(madde_splits) else len(text)
        madde_text = text[start:end].strip()

        if len(madde_text) < MIN_CHUNK_CHARS:
            continue

        if len(madde_text) <= MAX_CHUNK_CHARS:
            yield {
                "chunk_type": "madde",
                "madde_no":   f"Madde {madde_no}",
                "content":    madde_text,
            }
        else:
            # Uzun maddeleri bentlere/fıkralara böl
            yield from split_madde(madde_text, madde_no)


def split_madde(text: str, madde_no: str) -> Generator[dict, None, None]:
    """Uzun bir madde metnini bentlere veya fıkralara böler."""
    # Fıkra dene
    fikralar = list(FIKRA_PATTERN.finditer(text))
    if fikralar:
        for f in fikralar:
            content = f"Madde {madde_no} fıkra {f.group(1)}:\n{f.group(2).strip()}"
            if len(content) >= MIN_CHUNK_CHARS:
                yield {
                    "chunk_type": "fikra",
                    "madde_no":   f"Madde {madde_no}",
                    "content":    content[:MAX_CHUNK_CHARS],
                }
        return

    # Bent dene
    bentler = list(BENT_PATTERN.finditer(text))
    if bentler:
        for b in bentler:
            content = f"Madde {madde_no} bent {b.group(1)}):\n{b.group(2).strip()}"
            if len(content) >= MIN_CHUNK_CHARS:
                yield {
                    "chunk_type": "bent",
                    "madde_no":   f"Madde {madde_no}",
                    "content":    content[:MAX_CHUNK_CHARS],
                }
        return

    # Fallback: sabit boyut böl
    for part in fixed_split(text, MAX_CHUNK_CHARS):
        yield {
            "chunk_type": "genel",
            "madde_no":   f"Madde {madde_no}",
            "content":    part,
        }


def split_by_paragraphs(text: str) -> Generator[dict, None, None]:
    """Madde olmayan belgeler için paragraf bazlı böler."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    buffer = ""
    for para in paragraphs:
        if len(buffer) + len(para) < MAX_CHUNK_CHARS:
            buffer += "\n\n" + para if buffer else para
        else:
            if len(buffer) >= MIN_CHUNK_CHARS:
                yield {"chunk_type": "genel", "madde_no": "", "content": buffer}
            buffer = para
    if len(buffer) >= MIN_CHUNK_CHARS:
        yield {"chunk_type": "genel", "madde_no": "", "content": buffer}


def fixed_split(text: str, max_len: int) -> list[str]:
    """Metni max_len karakterlik parçalara böler, kelime sınırına saygılı."""
    parts = []
    while len(text) > max_len:
        split_at = text.rfind(" ", 0, max_len)
        if split_at == -1:
            split_at = max_len
        parts.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        parts.append(text)
    return parts


def process_decree(decree_id: int, pdf_path: str, conn) -> int:
    """
    Tek bir kararname PDF'ini işler:
    1. Metni çıkar
    2. Chunk'lara böl
    3. Veritabanına yaz (embedding olmadan)
    Oluşturulan chunk sayısını döner.
    """
    log.info(f"İşleniyor [#{decree_id}]: {pdf_path}")

    text, page_count = extract_text_from_pdf(pdf_path)
    if not text:
        log.warning(f"  Metin çıkarılamadı: {pdf_path}")
        return 0

    chunks = list(split_into_chunks(text))
    log.info(f"  {page_count} sayfa, {len(chunks)} chunk")

    with conn.cursor() as cur:
        # Decree'yi güncelle
        cur.execute("""
            UPDATE decrees
            SET raw_text = %s, page_count = %s
            WHERE id = %s
        """, (text[:50000], page_count, decree_id))

        # Mevcut chunk'ları temizle (yeniden işleme durumunda)
        cur.execute("DELETE FROM decree_chunks WHERE decree_id = %s", (decree_id,))

        # Chunk'ları kaydet
        for idx, chunk in enumerate(chunks):
            token_est = len(chunk["content"].split()) * 1.3  # kaba tahmin
            cur.execute("""
                INSERT INTO decree_chunks
                    (decree_id, chunk_index, chunk_type, madde_no, content, token_count)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                decree_id,
                idx,
                chunk["chunk_type"],
                chunk["madde_no"],
                chunk["content"],
                int(token_est),
            ))

        conn.commit()

    log.info(f"  {len(chunks)} chunk kaydedildi")
    return len(chunks)


def process_unprocessed(conn, limit: int = 50) -> int:
    """
    Henüz işlenmemiş kararnameleri toplu işler.
    (Embedding adımından önce çalışır)
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, pdf_path FROM decrees
            WHERE is_processed = FALSE
              AND pdf_path IS NOT NULL
            ORDER BY gazette_date DESC
            LIMIT %s
        """, (limit,))
        rows = cur.fetchall()

    total = 0
    for decree_id, pdf_path in rows:
        if not Path(pdf_path).exists():
            log.warning(f"  PDF bulunamadı: {pdf_path}")
            continue
        count = process_decree(decree_id, pdf_path, conn)
        total += count

    log.info(f"Toplam {len(rows)} kararname işlendi, {total} chunk oluşturuldu.")
    return total


if __name__ == "__main__":
    import sys
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        # Tek kararname işle
        with conn.cursor() as cur:
            cur.execute("SELECT pdf_path FROM decrees WHERE id=%s", (int(sys.argv[1]),))
            row = cur.fetchone()
        if row:
            process_decree(int(sys.argv[1]), row[0], conn)
    else:
        process_unprocessed(conn)
    conn.close()
