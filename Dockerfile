# API server for Railway (docs/deployment-plan.md). Railway builds this file and sets PORT.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install . && rm -rf src

COPY data/restaurants.parquet data/meta.json ./data/

RUN useradd --create-home --uid 10001 app
USER app

# One worker: the response cache, rate limits and LLM budget live in this process's memory.
CMD ["sh", "-c", "exec uvicorn recommender.api:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
