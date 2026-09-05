"""Shared FastAPI dependencies (DB connections, paths, WHOOP client)."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from threading import Lock

import duckdb
from fastapi import HTTPException

from thaalam.config import get_settings
from thaalam.db import DEFAULT_DB_PATH
from thaalam.db import get_connection as _open_base_connection
from thaalam.whoop_client.auth import AUTHORIZE_URL, REVOKE_URL, TOKEN_URL, default_token_key_path
from thaalam.whoop_client.client import WhoopClient

DB_PATH = DEFAULT_DB_PATH
DATA_DIR = Path(DEFAULT_DB_PATH).resolve().parent
TOKEN_PATH = DATA_DIR / "whoop_token.json"
TOKEN_KEY_PATH = default_token_key_path()
OAUTH_STATE_PATH = DATA_DIR / "whoop_oauth_state.json"

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
                "No WHOOP database found. Connect at /api/oauth/whoop/connect "
                "or run `uv run main.py` "
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


def acquire_writable_connection() -> duckdb.DuckDBPyConnection:
    """Cursor on the process-wide DuckDB connection; creates the file if needed.

    Callers must `.close()` the cursor (not the base connection). Use this
    from API routes instead of a second `duckdb.connect()`.
    """
    return _get_base_connection().cursor()


def get_or_create_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Writable cursor; creates the database on first connect / OAuth backfill."""
    con = acquire_writable_connection()
    try:
        yield con
    finally:
        con.close()


def whoop_credentials() -> dict[str, str]:
    settings = get_settings()
    return {
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
        "redirect_uri": settings.redirect_uri,
        "authorize_url": settings.authorization_url or AUTHORIZE_URL,
        "token_url": settings.token_url or TOKEN_URL,
        "revoke_url": settings.revoke_url or REVOKE_URL,
        "token_key": settings.whoop_token_key,
    }


def build_whoop_client() -> WhoopClient:
    creds = whoop_credentials()
    if not creds["client_id"] or not creds["client_secret"]:
        raise RuntimeError("CLIENT_ID and CLIENT_SECRET must be set")
    kwargs: dict = {
        "redirect_uri": creds["redirect_uri"] or None,
        "authorize_url": creds["authorize_url"],
        "token_url": creds["token_url"],
        "revoke_url": creds["revoke_url"],
        "token_path": TOKEN_PATH,
        "token_key_path": TOKEN_KEY_PATH,
    }
    if creds["token_key"]:
        kwargs["token_key"] = creds["token_key"]
    return WhoopClient(creds["client_id"], creds["client_secret"], **kwargs)


def is_whoop_connected() -> bool:
    """Whether a refreshable token is stored locally -- never inspects secret values for clients."""
    if not TOKEN_PATH.exists():
        return False
    try:
        client = build_whoop_client()
    except Exception:
        return False
    try:
        token = client.token or {}
        return bool(token.get("refresh_token") or token.get("access_token"))
    finally:
        client.close()
