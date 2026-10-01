# Review service (Step 8): CPU-only, the frozen baseline and tuned legal-BERT baked in.
FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# CPU wheel first, so the lock's torch pin is already satisfied and no CUDA packages are pulled.
RUN pip install --no-cache-dir --only-binary=:all: "$(grep '^torch==' requirements.txt)" \
        --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --only-binary=:all: -r requirements.txt

RUN useradd --create-home --uid 10001 app
COPY src/ src/
COPY service/ service/
# Owned by the service user: safetensors writes weights as owner-only (0600), which root ownership would make unreadable.
COPY --chown=app:app models/ models/
COPY data/eval/ data/eval/
USER app
ENV HOME=/home/app \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    SERVICE_MODELS=baseline,transformer-tuned \
    SERVICE_REQUIRE_ALL_MODELS=1

EXPOSE 8080
CMD exec uvicorn service.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
