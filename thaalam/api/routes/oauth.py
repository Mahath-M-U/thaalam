"""Server-side WHOOP OAuth connect / callback / status.

Tokens are exchanged and stored on the server only -- JSON responses never
include access or refresh tokens.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import RedirectResponse

from thaalam.api.deps import (
    OAUTH_STATE_PATH,
    acquire_writable_connection,
    build_whoop_client,
    is_whoop_connected,
    whoop_credentials,
)
from thaalam.services.derived_metrics import recompute
from thaalam.sync import BACKFILL_DAYS, backfill_window
from thaalam.whoop_client.client import WhoopClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oauth/whoop", tags=["oauth"])

_STATE_TTL_SECONDS = 10 * 60


@router.get("/status")
def oauth_status() -> dict[str, bool]:
    return {"connected": is_whoop_connected()}


@router.get("/connect")
def oauth_connect() -> RedirectResponse:
    creds = whoop_credentials()
    if not creds["client_id"] or not creds["client_secret"]:
        raise HTTPException(status_code=503, detail="WHOOP CLIENT_ID and CLIENT_SECRET are not configured")
    if not creds["redirect_uri"]:
        raise HTTPException(status_code=500, detail="REDIRECT_URI is not configured")

    client = build_whoop_client()
    try:
        url, state = client.authorization_url()
    finally:
        client.close()
    _write_oauth_state(state)
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
def oauth_callback(
    background_tasks: BackgroundTasks,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    frontend = os.getenv("FRONTEND_URL") or "http://localhost:5173"
    if error:
        return RedirectResponse(f"{frontend}/?whoop=error", status_code=302)
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    if not _consume_oauth_state(state):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    client = build_whoop_client()
    try:
        client.fetch_token(code=code)
    except Exception:
        logger.exception("WHOOP token exchange failed")
        client.close()
        return RedirectResponse(f"{frontend}/?whoop=error", status_code=302)
    else:
        client.close()

    background_tasks.add_task(_run_oauth_backfill)
    return RedirectResponse(f"{frontend}/?whoop=connected", status_code=302)


def _run_oauth_backfill() -> None:
    client: WhoopClient | None = None
    try:
        client = build_whoop_client()
        con = acquire_writable_connection()
        try:
            backfill_window(client, days=BACKFILL_DAYS, con=con)
            recompute(con, trigger="backfill")
        finally:
            con.close()
    except Exception:
        logger.exception("90-day WHOOP backfill after OAuth failed")
    finally:
        if client is not None:
            client.close()


def _write_oauth_state(state: str) -> None:
    OAUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"state": state, "created_at": time.time()}
    OAUTH_STATE_PATH.write_text(json.dumps(payload), encoding="utf-8")


def _consume_oauth_state(state: str | None) -> bool:
    if not state or not OAUTH_STATE_PATH.exists():
        return False
    try:
        payload = json.loads(OAUTH_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
    try:
        OAUTH_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    saved = payload.get("state")
    created_at = float(payload.get("created_at") or 0)
    if saved != state:
        return False
    if time.time() - created_at > _STATE_TTL_SECONDS:
        return False
    return True
