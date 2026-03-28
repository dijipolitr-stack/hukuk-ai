"""
embedder.py — Chunk embedding oluşturma ve semantik arama
OpenAI text-embedding-3-small ile her chunk için vektör üretir,
pgvector'e yazar. Dilekçe üretiminde semantic search sağlar.
"""

import os
import time
import logging
from typing import Optional

import openai
from dotenv import load_dotenv
import psycopg as psycopg2
from psycopg.rows import dict_row as RealDictCursorFactory

load_dotenv()
log = logging.getLogger(__name__)

openai.api_key = os.getenv("OPENAI_API_KEY")
EMBED_MODEL    = "text-embedding-3-small"
EMBED_DIM      = 1536
BATCH_SIZE     = 100   # OpenAI batch limit
RATE_LIMIT_SLEEP = 0.1 # saniye


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    OpenAI API ile toplu embedding üretir.
    Rate limit durumunda otomatik yeniden dener.
    """
    for attempt in range(3):
        try:
            response = openai.embeddings.create(
                model=EMBED_MODEL,
                input=texts,
                encoding_format="float",
            )
            return [item.embedding for item in response.data]
        except openai.RateLimitError:
            wait = 2 ** attempt * 5
            log.warning(f"Rate limit, {wait}s bekleniyor...")
            time.sleep(wait)
        except openai.OpenAIError as e:
            log.error(f"OpenAI hatası: {e}")
            raise
    raise RuntimeError("3 denemede embedding alınamadı")


def embed_unprocessed_chunks(conn, limit: int = 500) -> int:
    """
    Embedding'i olmayan chunk'ları toplu işler.
    Maliyet tahmini: 1000 chunk ≈ $0.002
    """
    with conn.cursor(row_factory=RealDictCursorFactory) as cur:
        cur.execute("""
            SELECT dc.id, dc.content, dc.decree_id
            FROM decree_chunks dc
            WHERE dc.embedding IS NULL
            ORDER BY dc.decree_id DESC, dc.chunk_index
            LIMIT %s
        """, (limit,))
        chunks = cur.fetchall()

    if not chunks:
        log.info("Tüm chunk'lar zaten embedding'e sahip.")
        return 0

    log.info(f"{len(chunks)} chunk için embedding üretiliyor...")

    # Batch'lere böl
    total = 0
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i:i + BATCH_SIZE]
        texts = [c["content"] for c in batch]
        ids   = [c["id"] for c in batch]

        try:
            embeddings = embed_texts(texts)
        except Exception as e:
            log.error(f"Batch {i//BATCH_SIZE} atlandı: {e}")
            continue

        # Toplu update
        with conn.cursor() as cur:
            for chunk_id, embedding in zip(ids, embeddings):
                vec_str = "[" + ",".join(f"{v:.6f}" for v in embedding) + "]"
                cur.execute(
                    "UPDATE decree_chunks SET embedding = %s WHERE id = %s",
                    (vec_str, chunk_id)
                )

            # İlgili decree'leri işlenmiş olarak işaretle
            decree_ids = list({c["decree_id"] for c in batch})
            cur.execute(
                "UPDATE decrees SET is_processed = TRUE WHERE id = ANY(%s)",
                (decree_ids,)
            )
            conn.commit()

        total += len(batch)
        log.info(f"  {total}/{len(chunks)} chunk işlendi")
        time.sleep(RATE_LIMIT_SLEEP)

    log.info(f"Embedding tamamlandı: {total} chunk")
    return total


def embed_query(query: str) -> "np.ndarray":
    """
    Kullanıcı sorgusunu vektöre çevirir.
    Dilekçe motorunda her arama öncesi çağrılır.
    """
    import numpy as np
    response = openai.embeddings.create(
        model=EMBED_MODEL,
        input=[query],
        encoding_format="float",
    )
    return np.array(response.data[0].embedding, dtype=np.float32)


def semantic_search(
    conn,
    query: str,
    top_k: int = 8,
    category_filter: Optional[str] = None,
    date_from: Optional[str] = None,
) -> list[dict]:
    """
    Kullanıcı talebine en yakın kararname chunk'larını döner.
    """
    import numpy as np
    try:
        from pgvector.psycopg import register_vector
        register_vector(conn)
    except Exception:
        pass
    query_vec = embed_query(query)

    # Dinamik filtre inşa et
    filters = []
    params  = []

    if category_filter:
        filters.append("d.category = %s")
        params.append(category_filter)
    if date_from:
        filters.append("d.gazette_date >= %s")
        params.append(date_from)

    where = ("WHERE " + " AND ".join(filters)) if filters else ""

    query_sql = f"""
        SELECT
            dc.id            AS chunk_id,
            dc.decree_id,
            dc.madde_no,
            dc.content,
            dc.chunk_type,
            d.title          AS decree_title,
            d.gazette_number,
            d.gazette_date,
            d.category,
            1 - (dc.embedding <=> %s) AS similarity
        FROM decree_chunks dc
        JOIN decrees d ON d.id = dc.decree_id
        {where}
        ORDER BY dc.embedding <=> %s
        LIMIT %s
    """
    params_full = [query_vec] + params + [query_vec, top_k]

    with conn.cursor(row_factory=RealDictCursorFactory) as cur:
        cur.execute(query_sql, params_full)
        rows = cur.fetchall()

    results = []
    for row in rows:
        results.append({
            "chunk_id":      row["chunk_id"],
            "decree_id":     row["decree_id"],
            "madde_no":      row["madde_no"] or "",
            "content":       row["content"],
            "chunk_type":    row["chunk_type"],
            "decree_title":  row["decree_title"],
            "gazette_number":row["gazette_number"],
            "gazette_date":  str(row["gazette_date"]),
            "category":      row["category"],
            "similarity":    round(float(row["similarity"]), 4),
        })

    return results


def format_context_for_claude(results: list[dict]) -> str:
    """
    Semantic search sonuçlarını Claude'a gönderilecek
    bağlam metnine dönüştürür.
    """
    if not results:
        return "İlgili kararname bulunamadı."

    parts = []
    for r in results:
        parts.append(
            f"--- KARARNAME ---\n"
            f"Başlık    : {r['decree_title']}\n"
            f"Gazete No : {r['gazette_number']}  |  Tarih: {r['gazette_date']}\n"
            f"Bölüm     : {r['madde_no']}\n"
            f"Metin     :\n{r['content']}\n"
        )

    return "\n".join(parts)


if __name__ == "__main__":
    import sys
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))

    if len(sys.argv) > 1 and sys.argv[1] == "search":
        # Test: python embedder.py search "iş sözleşmesi feshi"
        query = " ".join(sys.argv[2:])
        results = semantic_search(conn, query, top_k=5)
        for r in results:
            print(f"\n[{r['similarity']:.3f}] {r['decree_title']}")
            print(f"  {r['madde_no']} — {r['content'][:150]}...")
    else:
        embed_unprocessed_chunks(conn)

    conn.close()
