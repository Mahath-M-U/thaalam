"""Shared FastAPI dependencies (DB connections, paths)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import duckdb
from fastapi import HTTPException

from thaalam.db import DEFAULT_DB_PATH

DB_PATH = DEFAULT_DB_PATH


def get_readonly_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Yield a read-only DuckDB connection, or 404 if the DB has not been synced yet."""
    if not Path(DB_PATH).exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No WHOOP database found. Run `uv run main.py` once to sync data "
                f"(expected at {DB_PATH})."
            ),
        )

    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        yield con
    finally:
        con.close()
