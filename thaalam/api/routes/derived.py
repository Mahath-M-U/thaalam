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


@router.get("/reads")
def get_reads(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    from thaalam.services.reads_service import get_reads_payload

    return get_reads_payload(con)


@router.get("/reads/{read_id}")
def get_read_dive(
    read_id: str,
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    from thaalam.services.reads_service import READ_ORDER, get_read_dive_payload

    if read_id not in READ_ORDER:
        return {"present": False, "id": read_id, "read": None, "dive": None}
    return get_read_dive_payload(con, read_id)


@router.get("/runway")
def get_runway(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    from thaalam.services.reads_service import get_runway_payload

    return get_runway_payload(con)
