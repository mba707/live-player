FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY liveplayer ./liveplayer
COPY static ./static
COPY tests ./tests
COPY pytest.ini .

EXPOSE 8112 8888-8897

ENV PYTHONUNBUFFERED=1 \
    LISTEN_HOST=0.0.0.0 \
    LISTEN_PORT=8112

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
    CMD curl -f http://localhost:8112/health || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8112"]
