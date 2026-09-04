"""Read stored derived metrics. The client never recomputes a baseline."""

from __future__ import annotations

from typing import Any

import duckdb
from fastapi import APIRouter, Depends

from thaalam.api.deps import get_readonly_connection
from thaalam.db import get_derived_baseline

router = APIRouter(prefix="/api/derived", tags=["derived"])


@router.get("/baselines")
def get_baselines(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    row = get_derived_baseline(con)
    if row is None:
        return {"present": False, "calibrating": True, "baseline": None}
    return {
        "present": True,
        "calibrating": bool(row.get("calibrating")),
        "baseline": row,
    }


@router.get("/vitality")
def get_vitality(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Vitality Score 0–1000. Client only renders; scoring is server-side."""
    from thaalam.services.vitality_score import build_vitality_payload

    return build_vitality_payload(con)
