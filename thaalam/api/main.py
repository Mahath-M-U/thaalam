"""FastAPI application entrypoint for the Thaalam dashboard API.

Run from the project root:

    uv run uvicorn thaalam.api.main:app --reload --port 8000

The React frontend (``frontend/``) expects this API on port 8000 during
development (Vite proxies ``/api`` and ``/health``).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from thaalam.api.middleware import RequestContextMiddleware
from thaalam.api.routes import auth, briefs, data, derived, health, oauth, webhooks
from thaalam.config import get_settings
from thaalam.logging_config import setup_logging

settings = get_settings()
settings.validate_runtime()
setup_logging()

app = FastAPI(
    title="Thaalam API",
    description="Local WHOOP health data API (DuckDB-backed).",
    version="0.2.0",
)

# Vite dev origins by default; empty in production, where the packaged app
# serves the frontend from this same origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Added last so it wraps everything else and every request gets logged once,
# with a correlation id, whatever the inner layers do.
app.add_middleware(RequestContextMiddleware)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(data.router)
app.include_router(briefs.router)
app.include_router(oauth.router)
app.include_router(webhooks.router)
app.include_router(derived.router)


def _find_frontend_dist() -> Path | None:
    """Locate the built Vite frontend, if present.

    Local dev:  <repo>/frontend/dist  (gitignored, may not exist)
    Docker:     /app/frontend/dist     (copied from the frontend-builder stage)
    """
    here = Path(__file__).resolve()
    candidates = [
        here.parent.parent.parent / "frontend" / "dist",
        Path("/app/frontend/dist"),
        Path("frontend/dist"),
    ]
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").is_file():
            return candidate
    return None


FRONTEND_DIST = _find_frontend_dist()

if FRONTEND_DIST is None:

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "name": "Thaalam API",
            "docs": "/docs",
            "health": "/health",
            "api_prefix": "/api",
        }

else:
    # Serve hashed Vite assets with proper cache headers.
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve the SPA: real files directly, everything else -> index.html.

        API / docs / health paths are excluded so a missing API route still
        returns a JSON 404 (which the React `api.ts` client expects) instead
        of HTML.
        """
        if full_path.startswith(("api", "health", "docs", "openapi.json", "redoc")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = FRONTEND_DIST / full_path
        # Guard against path traversal: resolved file must stay under dist/.
        try:
            candidate.resolve().relative_to(FRONTEND_DIST.resolve())
        except ValueError:
            raise HTTPException(status_code=404, detail="Not found")
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(FRONTEND_DIST / "index.html"))
