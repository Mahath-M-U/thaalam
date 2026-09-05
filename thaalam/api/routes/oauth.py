"""Server-side WHOOP OAuth connect / callback / status.

Tokens are exchanged and stored on the server only -- JSON responses never
include access or refresh tokens.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import sqlite3
import time
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from thaalam.api.deps import (
    OAUTH_STATE_PATH,
    acquire_writable_connection,
    build_whoop_client,
    client_ip,
    get_auth_db,
    is_whoop_connected,
    require_admin,
    whoop_credentials,
)
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import AuthenticatedUser
from thaalam.config import get_settings
from thaalam.logging_config import request_id_var
from thaalam.services.derived_metrics import recompute
from thaalam.sync import BACKFILL_DAYS, backfill_window
from thaalam.whoop_client.client import WhoopClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/oauth/whoop", tags=["oauth"])

_STATE_TTL_SECONDS = 10 * 60


@router.get("/status")
def oauth_status(_: AuthenticatedUser = Depends(require_admin)) -> dict[str, bool]:
    return {"connected": is_whoop_connected()}


@router.get("/connect")
def oauth_connect(
    request: Request,
    user: AuthenticatedUser = Depends(require_admin),
    auth_con: sqlite3.Connection = Depends(get_auth_db),
) -> RedirectResponse:
    """Start the WHOOP consent flow. Admin-only: it links the account's data.

    A GET that writes the pending state, which is safe from CSRF only because
    it is reached by a top-level browser navigation the admin performs; the
    state it stores is single-use and short-lived, and the callback checks it.
    """
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
    _write_oauth_state(state, user_id=user.id)
    auth_store.record_audit(
        auth_con,
        "whoop.connect_started",
        user_id=user.id,
        actor_email=user.email,
        client_ip=client_ip(request),
        request_id=request_id_var.get(),
    )
    return RedirectResponse(url, status_code=302)


@router.get("/callback")
def oauth_callback(
    background_tasks: BackgroundTasks,
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    auth_con: sqlite3.Connection = Depends(get_auth_db),
) -> RedirectResponse:
    """Where WHOOP redirects the browser back to.

    Deliberately not session-gated: WHOOP sends the user's browser here and
    the request may not carry the app's cookie. The single-use `state` written
    by the admin-only /connect is what authorises it.
    """
    frontend = _frontend_base(request)
    if error:
        return RedirectResponse(f"{frontend}/?whoop=error", status_code=302)
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
    pending = _consume_oauth_state(state)
    if pending is None:
        logger.warning(
            "Rejected WHOOP callback with an invalid or expired state",
            extra={"client_ip": client_ip(request)},
        )
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

    auth_store.record_audit(
        auth_con,
        "whoop.connected",
        user_id=pending.get("user_id"),
        client_ip=client_ip(request),
        request_id=request_id_var.get(),
    )
    background_tasks.add_task(_run_oauth_backfill, pending.get("user_id"))
    return RedirectResponse(f"{frontend}/?whoop=connected", status_code=302)


def _frontend_base(request: Request) -> str:
    """The origin to send the browser back to once WHOOP has redirected here.

    `FRONTEND_URL` when it is set, otherwise the origin this request arrived
    on. The old fallback was a literal http://localhost:3001, which is correct
    on a laptop running Vite and useless anywhere else: a deployment that had
    not set FRONTEND_URL would complete the token exchange and then redirect
    the user to a port on their own machine. Production serves the built
    frontend from this very origin, so the request is the right source for it.

    `run_api.py` enables proxy headers in production, so `base_url` reflects
    the public https:// domain rather than the container's address.
    """
    configured = get_settings().resolved_frontend_url
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _run_oauth_backfill(user_id: int | None) -> None:
    """Runs after the callback has already responded (see `background_tasks`).

    A failure here used to be visible only in the container's own logs --
    Administration -> Audit showed "whoop.connected" and then nothing, so a
    dashboard that stayed empty after a successful connect had no way to
    tell "still importing" from "the import broke" without reading logs no
    Dokploy Environment tab gives you. Recording the outcome here, success
    or failure, makes that the same one click as everything else in Audit.
    """
    client: WhoopClient | None = None
    try:
        client = build_whoop_client()
        con = acquire_writable_connection()
        try:
            result = backfill_window(client, days=BACKFILL_DAYS, con=con)
            recompute(con, trigger="backfill")
        finally:
            con.close()
    except Exception as exc:
        logger.exception("90-day WHOOP backfill after OAuth failed")
        with auth_store.connect() as auth_con:
            auth_store.record_audit(
                auth_con,
                "whoop.backfill_failed",
                user_id=user_id,
                detail=str(exc) or exc.__class__.__name__,
            )
    else:
        with auth_store.connect() as auth_con:
            auth_store.record_audit(
                auth_con,
                "whoop.backfill_completed",
                user_id=user_id,
                detail=f"{result.get('records', 0)} record(s) over {BACKFILL_DAYS} days",
            )
    finally:
        if client is not None:
            client.close()


def _write_oauth_state(state: str, *, user_id: int | None = None) -> None:
    OAUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "state": state,
        "created_at": time.time(),
        "user_id": user_id,
    }
    OAUTH_STATE_PATH.write_text(json.dumps(payload), encoding="utf-8")
    try:
        OAUTH_STATE_PATH.chmod(0o600)
    except OSError:
        pass


def _consume_oauth_state(state: str | None) -> dict[str, Any] | None:
    """Validate and burn the pending state; returns its payload or None.

    WHOOP caps self-generated state at 8 characters, so this value carries
    only ~32 bits. It is single-use and expires in ten minutes, and reaching
    it at all requires an admin to have just started a connect -- the
    comparison is constant-time so the window can't be narrowed by timing.
    """
    if not state or not OAUTH_STATE_PATH.exists():
        return None
    try:
        payload = json.loads(OAUTH_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    try:
        OAUTH_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass
    saved = payload.get("state") or ""
    created_at = float(payload.get("created_at") or 0)
    if not hmac.compare_digest(str(saved), state):
        return None
    if time.time() - created_at > _STATE_TTL_SECONDS:
        return None
    return payload
