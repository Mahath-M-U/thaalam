# Thaalam — single-container image for Dokploy.
# Serves FastAPI backend + built React frontend from the same origin (port 8000).
# Dokploy terminates TLS for your custom domain; the app just listens on $PORT.

# ---------- Stage 1: build the React frontend ----------
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

# Install first for better layer caching.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build
# -> /app/frontend/dist

# ---------- Stage 2: Python backend + static frontend ----------
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl is only for the container HEALTHCHECK.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Backend source. pyproject.toml declares all runtime deps
# (fastapi, uvicorn[standard], duckdb, pandas, ...).
COPY pyproject.toml README.md ./
COPY thaalam/ ./thaalam/
COPY main.py run_api.py generate_report.py ./

RUN pip install --upgrade pip setuptools wheel \
    && pip install .

# Built SPA from stage 1. FastAPI serves it from the same origin
# (see thaalam/api/main.py -> _find_frontend_dist + serve_spa).
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

# DuckDB file, WHOOP token, auth sqlite all live under /app/data.
# Mounted as a Dokploy volume so redeploys keep your data.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

ENV APP_ENV=production \
    PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# ${PORT:-8000} lets Dokploy override the port if needed.
# 0.0.0.0 is required inside containers (127.0.0.1 would be unreachable).
CMD ["sh", "-c", "uvicorn thaalam.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
