"""FastAPI application entrypoint for the Thaalam dashboard API.

Run from the project root:

    uv run uvicorn thaalam.api.main:app --reload --port 8000

The React frontend (``frontend/``) expects this API on port 8000 during
development (Vite proxies ``/api`` and ``/health``).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from thaalam.api.routes import data, health
from thaalam.logging_config import setup_logging

setup_logging()

app = FastAPI(
    title="Thaalam API",
    description="Local WHOOP health data API (DuckDB-backed).",
    version="0.2.0",
)

# Local Vite dev server + optional production static host.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(data.router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "Thaalam API",
        "docs": "/docs",
        "health": "/health",
        "api_prefix": "/api",
    }
