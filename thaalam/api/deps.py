"""Shared FastAPI dependencies (DB connections, paths, WHOOP client)."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Generator
from pathlib import Path
from threading import Lock

import duckdb
from fastapi import Depends, HTTPException, Request

from thaalam.auth import sessions as session_store
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import AuthenticatedUser
from thaalam.config import get_settings
from thaalam.db import DEFAULT_DB_PATH
from thaalam.db import get_connection as _open_base_connection
from thaalam.logging_config import current_user_var
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


def get_optional_readonly_connection() -> Generator[duckdb.DuckDBPyConnection | None, None, None]:
    """Like `get_readonly_connection`, but yields None instead of raising 404.

    For routes that have something useful to say with no database yet. The
    assistant is the case that motivated it: "I have no data, what do I do?"
    is a fair question, and a 404 telling the user to connect WHOOP is a worse
    answer than the assistant giving them that instruction in prose.
    """
    if not Path(DB_PATH).exists():
        yield None
        return
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


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def get_auth_db() -> Generator[sqlite3.Connection, None, None]:
    """Yield a connection to the auth database (separate from the DuckDB)."""
    with auth_store.connect() as con:
        yield con


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _unauthenticated() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Cookie"},
    )


def get_current_user(
    request: Request,
    con: sqlite3.Connection = Depends(get_auth_db),
) -> AuthenticatedUser:
    """Resolve the session cookie, enforcing CSRF on state-changing requests.

    CSRF is checked here rather than in a separate dependency so that every
    authenticated write is covered by construction -- a route cannot forget it
    while still requiring a user. Requests without a session never reach this,
    which is what keeps the signature-verified WHOOP webhook exempt.
    """
    token = request.cookies.get(session_store.SESSION_COOKIE, "")
    if not token:
        raise _unauthenticated()

    user = session_store.lookup_session(
        con, token, ttl_minutes=get_settings().session_ttl_minutes
    )
    if user is None:
        raise _unauthenticated()

    if request.method not in session_store.SAFE_METHODS:
        supplied = request.headers.get(session_store.CSRF_HEADER, "")
        if not supplied or not secrets.compare_digest(supplied, user.csrf_token):
            raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")

    # Surfaces the account in the access log for this request.
    current_user_var.set(user.email)
    return user


def require_user(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """An authenticated user who is not mid-forced-password-change.

    A user who must rotate their password can still reach the auth routes, but
    nothing else, so a bootstrap credential can't be left in place while the
    account is used normally.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=403,
            detail="Password change required before continuing",
        )
    return user


def require_admin(
    user: AuthenticatedUser = Depends(require_user),
) -> AuthenticatedUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user
