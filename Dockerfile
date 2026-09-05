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

# DuckDB file, WHOOP token, auth sqlite and logs all live under /app/data,
# mounted as a volume so redeploys keep your data.
#
# DATA_DIR is required, not cosmetic: `pip install .` puts the package under
# site-packages, so without it every path would resolve next to the installed
# package and a redeploy would silently discard the database, the WHOOP token
# and every account. The app refuses to start in production if it resolves
# there.
ENV APP_ENV=production \
    PORT=8000 \
    DATA_DIR=/app/data

# Run as a non-root user; /app/data holds the WHOOP token and the auth
# database. Ownership is set before VOLUME so the named volume inherits it.
RUN useradd --create-home --uid 10001 thaalam \
    && mkdir -p /app/data \
    && chown -R thaalam:thaalam /app
USER thaalam

VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

# Started through run_api.py rather than uvicorn directly, so the production
# serving rules live in one place: bind 0.0.0.0, trust the proxy's forwarded
# client address, and stay on a single worker. DuckDB allows one writer and
# the API holds one process-wide writable connection, so a second worker
# would fight it for the file.
CMD ["python", "run_api.py"]
