"""WHOOP webhook receiver with HMAC signature validation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from thaalam import db
from thaalam.api.deps import build_whoop_client, is_whoop_connected
from thaalam.services.derived_metrics import recompute
from thaalam.whoop_client.client import WhoopClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# sleep.updated/deleted, workout.updated/deleted, recovery.updated/deleted
_SUPPORTED_TYPES = frozenset(
    {
        "sleep.updated",
        "sleep.deleted",
        "workout.updated",
        "workout.deleted",
        "recovery.updated",
        "recovery.deleted",
    }
)


def verify_whoop_signature(
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str | None,
) -> bool:
    """WHOOP signs `timestamp + raw_body` with HMAC-SHA256, then base64-encodes it."""
    if not timestamp or not signature or not secret:
        return False
    message = timestamp.encode("utf-8") + body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(expected, signature.strip())


def check_webhook_signature(
    body: bytes,
    timestamp: str | None,
    signature: str | None,
    secret: str | None,
) -> None:
    """Raise 401 if unsigned/missing secret, 403 if the HMAC does not match."""
    if not signature or not timestamp:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    if not secret:
        raise HTTPException(status_code=401, detail="Missing webhook signature")
    if not verify_whoop_signature(body, timestamp, signature, secret):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")


def handle_whoop_event(
    con: Any,
    payload: dict[str, Any],
    client: WhoopClient | None = None,
) -> dict[str, Any]:
    """Upsert or delete the resource named by the event, then the caller recomputes."""
    event_type = str(payload.get("type") or "")
    resource_id = payload.get("id")
    if event_type not in _SUPPORTED_TYPES:
        return {"action": "ignored", "type": event_type, "id": resource_id}
    if resource_id is None:
        return {"action": "ignored", "type": event_type, "id": None}

    kind, verb = event_type.split(".", 1)
    if verb == "deleted":
        _delete_resource(con, kind, resource_id)
        return {"action": "deleted", "type": event_type, "id": resource_id}

    if client is None:
        logger.warning("WHOOP %s received but no client is available to fetch the resource", event_type)
        return {"action": "skipped", "type": event_type, "id": resource_id}

    fetched = _fetch_resource(client, kind, resource_id)
    if fetched is None:
        _delete_resource(con, kind, resource_id)
        return {"action": "deleted", "type": event_type, "id": resource_id}

    _upsert_resource(con, kind, fetched)
    return {"action": "upserted", "type": event_type, "id": resource_id}


def _delete_resource(con: Any, kind: str, resource_id: Any) -> None:
    if kind == "sleep":
        db.delete_sleep(con, resource_id)
    elif kind == "workout":
        db.delete_workout(con, resource_id)
    elif kind == "recovery":
        db.delete_recovery(con, resource_id)


def _upsert_resource(con: Any, kind: str, record: dict[str, Any]) -> None:
    if kind == "sleep":
        db.upsert_sleep(con, [record])
    elif kind == "workout":
        db.upsert_workouts(con, [record])
    elif kind == "recovery":
        db.upsert_recovery(con, [record])


def _fetch_resource(client: WhoopClient, kind: str, resource_id: Any) -> dict[str, Any] | None:
    if kind == "sleep":
        return client.get_sleep_by_id(str(resource_id), optional=True)
    if kind == "workout":
        return client.get_workout_by_id(str(resource_id), optional=True)
    if kind == "recovery":
        sleep = client.get_sleep_by_id(str(resource_id), optional=True)
        if not sleep or sleep.get("cycle_id") is None:
            return None
        return client.get_recovery_for_cycle(int(sleep["cycle_id"]), optional=True)
    return None


@router.post("/whoop")
async def whoop_webhook(request: Request) -> dict[str, Any]:
    body = await request.body()
    secret = os.getenv("CLIENT_SECRET") or os.getenv("WHOOP_CLIENT_SECRET") or ""
    check_webhook_signature(
        body,
        request.headers.get("x-whoop-signature-timestamp"),
        request.headers.get("x-whoop-signature"),
        secret,
    )

    try:
        payload = json.loads(body)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    client: WhoopClient | None = None
    try:
        if is_whoop_connected():
            client = build_whoop_client()
        con = db.get_connection()
        try:
            result = handle_whoop_event(con, payload, client)
            recompute(con, trigger="webhook")
        finally:
            con.close()
        return {"ok": True, **result}
    finally:
        if client is not None:
            client.close()
