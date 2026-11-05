# Stage 1: build the web app (Next.js static export) into /web/out
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Stage 2: the Python app, which also serves the built web app at /app
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt && useradd --system --uid 10001 --no-create-home app \
    && chown app /srv  # only the directory, so a local SQLite file can be created; code stays root-owned
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=web /web/out ./frontend/out
# The app never writes to its own files; it runs as an unprivileged user
USER app
ENV PORT=8000
# One worker only: the dialer keeps its batch lock, scheduler, webhook worker and rate limits in this process.
# Migrations run at start-up unless MIGRATE_ON_START=false, under a PostgreSQL advisory lock. The controlled
# alternative is "python -m app.migrate" as a deploy step (docs/phase5_deployment.md).
# The graceful timeout lets in-flight webhook requests finish when Render stops the old instance.
CMD ["sh", "-c", "uvicorn app.server:app --host 0.0.0.0 --port ${PORT} --workers 1 --timeout-graceful-shutdown 20"]
