# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.11.15-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG SCIPILOT_INSTALL_OCR=true

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/scipilot \
    XDG_CACHE_HOME=/tmp/.cache \
    TMPDIR=/tmp

# OCR is enabled in the production baseline. Setting SCIPILOT_INSTALL_OCR=false
# produces a smaller image; the API still starts and text-native PDFs still work.
RUN set -eux; \
    if [ "${SCIPILOT_INSTALL_OCR}" = "true" ]; then \
        apt-get update; \
        apt-get install -y --no-install-recommends \
            poppler-utils \
            tesseract-ocr \
            tesseract-ocr-eng; \
        rm -rf /var/lib/apt/lists/*; \
    fi; \
    groupadd --system --gid 10001 scipilot; \
    useradd --system --uid 10001 --gid scipilot --home-dir /home/scipilot \
        --create-home --shell /usr/sbin/nologin scipilot

WORKDIR /app

COPY backend/requirements.lock ./requirements.lock
RUN python -m pip install --requirement requirements.lock \
    && python -m pip check

COPY --chown=scipilot:scipilot backend/ ./

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD ["python", "-c", "import json,urllib.request; data=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)); raise SystemExit(0 if data.get('status') == 'ok' else 1)"]

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--no-server-header"]
