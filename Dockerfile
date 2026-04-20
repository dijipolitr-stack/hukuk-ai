FROM python:3.11-slim

WORKDIR /app

# Sadece gerekli klasörleri kopyala
COPY petition_engine/ ./petition_engine/
COPY scraper/embedder.py ./scraper/embedder.py
COPY scraper/prompts.py ./scraper/prompts.py
COPY notifications/ ./notifications/
COPY case_tools/ ./case_tools/

# Requirements kur
COPY petition_engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Başlat
CMD ["uvicorn", "petition_engine.api:app", "--host", "0.0.0.0", "--port", "8080"]
