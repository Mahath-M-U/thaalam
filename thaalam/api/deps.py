"""Shared FastAPI dependencies (DB connections, paths)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from threading import Lock

import duckdb
from fastapi import HTTPException

from thaalam.db import DEFAULT_DB_PATH
from thaalam.db import get_connection as _open_base_connection

DB_PATH = DEFAULT_DB_PATH

# DuckDB refuses a second `connect()` to the same file with a different
# read_only/config than an already-open connection in the same process --
# and with concurrent requests (the dashboard fires ~10 GETs in parallel),
# a plain read_only=True connect() here would race with the writable one
# the brief endpoint needs. So we open ONE writable base connection lazily
# and hand out `.cursor()`s of it per request instead -- cursors are cheap,
# share the same underlying file handle/config, and are safe to use
# concurrently across requests/threads.
_base_connection: duckdb.DuckDBPyConnection | None = None
_base_connection_lock = Lock()


def _require_db_exists() -> None:
    if not Path(DB_PATH).exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "No WHOOP database found. Run `uv run main.py` once to sync data "
                f"(expected at {DB_PATH})."
            ),
        )


def _get_base_connection() -> duckdb.DuckDBPyConnection:
    global _base_connection
    if _base_connection is None:
        with _base_connection_lock:
            if _base_connection is None:
                _base_connection = _open_base_connection(DB_PATH)
    return _base_connection


def get_readonly_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Yield a per-request DuckDB cursor for read-only routes."""
    _require_db_exists()
    con = _get_base_connection().cursor()
    try:
        yield con
    finally:
        con.close()


def get_writable_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Yield a per-request DuckDB cursor for routes that also need to write

    (e.g. logging a row to the insight brief history table).
    """
    _require_db_exists()
    con = _get_base_connection().cursor()
    try:
        yield con
    finally:
        con.close()
