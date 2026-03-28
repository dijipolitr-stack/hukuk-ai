from dotenv import load_dotenv
import os, psycopg

load_dotenv()
conn = psycopg.connect(os.getenv('DATABASE_URL'))
conn.execute("""
    INSERT INTO lawyers (id, full_name, bar_number, email, password_hash)
    VALUES (1, 'Test Avukat', '12345', 'test@hukukai.com', 'test_hash')
    ON CONFLICT (email) DO NOTHING
""")
conn.commit()
conn.close()
print('Test avukati eklendi!')