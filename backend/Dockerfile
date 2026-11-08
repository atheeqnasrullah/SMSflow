# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN mkdir -p app && touch app/__init__.py && pip install . && rm -rf app

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
RUN pip install --no-deps . \
    && useradd --create-home --uid 10001 smsflow \
    && mkdir -p /data/storage && chown -R smsflow /data

USER smsflow
ENV STORAGE_DIR=/data/storage

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -fsS http://localhost:8000/health/live || exit 1

# Default: API. Workers/beat override the command in docker-compose.
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "4", "-b", "0.0.0.0:8000", \
     "--forwarded-allow-ips", "*", "--access-logfile", "-", "--graceful-timeout", "30"]
