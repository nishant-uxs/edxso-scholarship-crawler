FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Use committed sample DB for the live demo dashboard
RUN cp data/scholarships.sample.db data/scholarships.db

ENV PYTHONPATH=src
ENV SCHOLARSHIP_DB=/app/data/scholarships.db
ENV PORT=8765

EXPOSE 8765

CMD ["sh", "-c", "uvicorn scholarship_intel.web.app:app --host 0.0.0.0 --port ${PORT:-8765}"]
