FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/requirements-runtime.txt /tmp/requirements-runtime.txt
RUN python -m pip install --upgrade pip \
    && pip install -r /tmp/requirements-runtime.txt

COPY . /app

RUN useradd --create-home --shell /bin/bash shakti \
    && chown -R shakti:shakti /app

USER shakti

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"

ENTRYPOINT ["/app/ops/docker-entrypoint.sh"]
