import sys, os
sys.path.insert(0, '../scraper')
from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector
import numpy as np
import openai
load_dotenv()

conn = psycopg.connect(os.getenv('DATABASE_URL'), autocommit=True)
register_vector(conn)

client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
resp = client.embeddings.create(model="text-embedding-3-small", input=["kidem tazminati"])
query_vec = np.array(resp.data[0].embedding, dtype=np.float32)
print(f"Vec: {query_vec.shape} {query_vec.dtype}")

with conn.cursor(row_factory=dict_row) as cur:
    cur.execute("""
        SELECT id, court, chamber,
               1 - (embedding <=> %s) AS similarity
        FROM precedents
        ORDER BY embedding <=> %s
        LIMIT 5
    """, (query_vec, query_vec))
    rows = cur.fetchall()

print(f"Sonuc: {len(rows)}")
for r in rows:
    print(f"  [{float(r['similarity']):.3f}] {r['court']} {r['chamber']}")

conn.close()