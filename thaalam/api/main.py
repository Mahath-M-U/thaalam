"""FastAPI application entrypoint for the Thaalam dashboard API.

Run from the project root:

    uv run uvicorn thaalam.api.main:app --reload --port 8001

The React frontend (``frontend/``) expects this API on port 8001 during
development (Vite proxies ``/api`` and ``/health``).
"""

from __future__ import annotations

from pathlib import Path

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from thaalam.api.middleware import (
    REQUEST_ID_HEADER,
    RateLimitMiddleware,
    RequestContextMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)
from thaalam.api import scheduler
from thaalam.api.routes import (
    admin,
    auth,
    briefs,
    chat,
    data,
    derived,
    health,
    oauth,
    webhooks,
)
from thaalam.config import get_settings
from thaalam.logging_config import request_id_var, setup_logging

settings = get_settings()
settings.validate_runtime()
setup_logging()

logger = logging.getLogger(__name__)

# The schema names every route and its shape. Useful in dev, needless
# reconnaissance for an unauthenticated caller in production.
_docs_enabled = not settings.is_production

_background: set[asyncio.Task] = set()


def _assistant_state() -> str:
    """One word for whether the chat dock will work, and why not if it won't."""
    if not settings.chat_enabled:
        return "off (CHAT_ENABLED=false)"
    if not settings.openrouter_api_key.strip():
        # Distinguish "never passed" from "passed empty" -- from a deploy log
        # those look identical but are different mistakes.
        for name in ("OPENROUTER_API_KEY", "OPROUTER_API_KEY"):
            if os.getenv(name) is not None:
                return f"off ({name} is present but empty once trimmed)"
        return "off (no OPENROUTER_API_KEY in this process's environment)"
    return f"on (model={settings.openrouter_model.strip() or 'auto-selected free'})"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # One line that answers the questions a bad deploy actually raises: which
    # environment won, which port the proxy has to target, whether the built
    # frontend made it into the image, and where the OAuth callback will send
    # the browser. Working these out from a 502 and a healthy container is
    # otherwise a long afternoon.
    # Built into the message rather than `extra`, because the JSON formatter
    # only promotes a fixed set of extra fields and this has to be readable in
    # whichever format the deployment happens to be using.
    # `assistant` is here for the same reason the WHOOP key state is logged:
    # a chat dock that silently never appears is indistinguishable from a
    # deployment that set OPENROUTER_API_KEY into the wrong place.
    logger.info(
        "Thaalam serving: app_env=%s port=%s (point the reverse proxy here) "
        "frontend_bundled=%s oauth_redirect=%s data_dir=%s assistant=%s",
        settings.app_env,
        os.getenv("PORT") or "8001",
        FRONTEND_DIST is not None,
        settings.resolved_frontend_url or "<origin of the request>",
        settings.resolved_data_dir,
        _assistant_state(),
    )
    task = scheduler.start(_background)
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Thaalam API",
    description="WHOOP health data API (DuckDB-backed).",
    version="0.2.0",
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
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

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)

if settings.trusted_hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

# Added last so it wraps everything else and every request gets logged once,
# with a correlation id, whatever the inner layers do -- including requests
# the rate limiter or size cap rejects before they reach a route.
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return the request id and nothing else.

    An unhandled error's message can carry a file path, a query, or a
    connection string. The detail goes to the log, where the same id makes it
    findable; the caller gets only the id.
    """
    request_id = request_id_var.get()
    logger.exception("Unhandled error", extra={"request_id": request_id})
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers={REQUEST_ID_HEADER: request_id} if request_id else None,
    )

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(data.router)
app.include_router(briefs.router)
app.include_router(oauth.router)
app.include_router(webhooks.router)
app.include_router(derived.router)
app.include_router(chat.router)


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
