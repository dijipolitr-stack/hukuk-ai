import sys, os
sys.path.insert(0, '../scraper')
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector
import numpy as np
load_dotenv()

conn = psycopg.connect(os.getenv('DATABASE_URL'))
register_vector(conn)

# Adim 1: Kac satir var?
with conn.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM precedents")
    print(f"Toplam satir: {cur.fetchone()[0]}")
    
    cur.execute("SELECT COUNT(*) FROM precedents WHERE embedding IS NOT NULL")
    print(f"Embedding'li satir: {cur.fetchone()[0]}")

# Adim 2: Embedding degerini oku
with conn.cursor() as cur:
    cur.execute("SELECT id, embedding FROM precedents WHERE id=1")
    row = cur.fetchone()
    if row:
        emb = row[1]
        print(f"ID=1 embedding tipi: {type(emb)}, deger ornegi: {str(emb)[:50]}")
    else:
        print("ID=1 bulunamadi!")

# Adim 3: Self-similarity (ayni vektoru kendisiyle karsilastir)
with conn.cursor(row_factory=dict_row) as cur:
    cur.execute("SELECT embedding FROM precedents WHERE id=1")
    stored_emb = cur.fetchone()['embedding']
    print(f"Stored embedding tipi: {type(stored_emb)}")
    
    if stored_emb is not None:
        cur.execute("""
            SELECT id, 1 - (embedding <=> %s) AS sim
            FROM precedents LIMIT 5
        """, (stored_emb,))
        rows = cur.fetchall()
        print(f"Self-sim sonuc: {len(rows)}")
        for r in rows:
            print(f"  [{float(r['sim']):.4f}] id={r['id']}")

conn.close()
