"""Health and meta endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from thaalam.api.deps import DB_PATH

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    """Liveness check plus whether local WHOOP data is available."""
    db_exists = Path(DB_PATH).exists()
    return {
        "status": "ok",
        "database_exists": db_exists,
        "database_path": str(DB_PATH),
    }
