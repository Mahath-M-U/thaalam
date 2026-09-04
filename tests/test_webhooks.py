"""Webhook signature validation and delete/upsert handling (no live WHOOP)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest
from fastapi import HTTPException

from thaalam import db
from thaalam.api.routes.webhooks import check_webhook_signature, handle_whoop_event, verify_whoop_signature


SECRET = "whoop-client-secret"
TIMESTAMP = "1710000000000"


def _sign(body: bytes, timestamp: str = TIMESTAMP, secret: str = SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), timestamp.encode("utf-8") + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def test_valid_signature_accepted():
    body = b'{"type":"sleep.updated","id":"abc","user_id":1}'
    signature = _sign(body)
    assert verify_whoop_signature(body, TIMESTAMP, signature, SECRET) is True
    check_webhook_signature(body, TIMESTAMP, signature, SECRET)


def test_invalid_signature_rejected():
    body = b'{"type":"sleep.updated","id":"abc","user_id":1}'
    with pytest.raises(HTTPException) as exc:
        check_webhook_signature(body, TIMESTAMP, "not-a-real-signature", SECRET)
    assert exc.value.status_code in (401, 403)


def test_unsigned_webhook_rejected():
    body = b'{"type":"sleep.updated","id":"abc","user_id":1}'
    with pytest.raises(HTTPException) as exc:
        check_webhook_signature(body, None, None, SECRET)
    assert exc.value.status_code == 401


def test_tampered_body_rejected():
    body = b'{"type":"sleep.deleted","id":"abc","user_id":1}'
    signature = _sign(body)
    with pytest.raises(HTTPException) as exc:
        check_webhook_signature(b'{"type":"sleep.deleted","id":"TAMPER","user_id":1}', TIMESTAMP, signature, SECRET)
    assert exc.value.status_code in (401, 403)


def test_sleep_delete_removes_row_and_is_idempotent(tmp_db):
    db.upsert_sleep(
        tmp_db,
        [
            {
                "id": "sleep-1",
                "cycle_id": 10,
                "user_id": 1,
                "start": "2026-08-01T23:00:00.000Z",
                "end": "2026-08-02T07:00:00.000Z",
                "nap": False,
                "score_state": "SCORED",
                "score": {},
            }
        ],
    )
    assert tmp_db.execute("SELECT COUNT(*) FROM sleep WHERE id = 'sleep-1'").fetchone()[0] == 1

    result = handle_whoop_event(
        tmp_db,
        {"user_id": 1, "id": "sleep-1", "type": "sleep.deleted", "trace_id": "t1"},
    )
    assert result["action"] == "deleted"
    assert tmp_db.execute("SELECT COUNT(*) FROM sleep WHERE id = 'sleep-1'").fetchone()[0] == 0

    again = handle_whoop_event(
        tmp_db,
        {"user_id": 1, "id": "sleep-1", "type": "sleep.deleted", "trace_id": "t2"},
    )
    assert again["action"] == "deleted"


def test_workout_delete_removes_row(tmp_db):
    db.upsert_workouts(
        tmp_db,
        [
            {
                "id": "workout-1",
                "user_id": 1,
                "start": "2026-08-02T12:00:00.000Z",
                "end": "2026-08-02T13:00:00.000Z",
                "sport_name": "running",
                "score_state": "SCORED",
                "score": {"strain": 8.0},
            }
        ],
    )
    handle_whoop_event(tmp_db, {"user_id": 1, "id": "workout-1", "type": "workout.deleted"})
    assert tmp_db.execute("SELECT COUNT(*) FROM workouts WHERE id = 'workout-1'").fetchone()[0] == 0


def test_recovery_delete_by_sleep_id(tmp_db):
    db.upsert_recovery(
        tmp_db,
        [
            {
                "cycle_id": 99,
                "sleep_id": "sleep-rec",
                "user_id": 1,
                "score_state": "SCORED",
                "score": {"recovery_score": 66, "hrv_rmssd_milli": 40.0, "resting_heart_rate": 55},
            }
        ],
    )
    handle_whoop_event(tmp_db, {"user_id": 1, "id": "sleep-rec", "type": "recovery.deleted"})
    assert tmp_db.execute("SELECT COUNT(*) FROM recovery WHERE sleep_id = 'sleep-rec'").fetchone()[0] == 0


def test_sleep_updated_upserts_from_client(tmp_db):
    class _Client:
        def get_sleep_by_id(self, sleep_id, *, optional=False):
            return {
                "id": sleep_id,
                "cycle_id": 11,
                "user_id": 1,
                "start": "2026-08-03T23:00:00.000Z",
                "end": "2026-08-04T07:00:00.000Z",
                "nap": False,
                "score_state": "SCORED",
                "score": {"sleep_performance_percentage": 80},
            }

    result = handle_whoop_event(
        tmp_db,
        {"user_id": 1, "id": "sleep-up", "type": "sleep.updated"},
        client=_Client(),
    )
    assert result["action"] == "upserted"
    row = tmp_db.execute("SELECT cycle_id FROM sleep WHERE id = 'sleep-up'").fetchone()
    assert row is not None
    assert row[0] == 11


def test_updated_404_deletes_existing_row(tmp_db):
    db.upsert_workouts(
        tmp_db,
        [{"id": "gone", "user_id": 1, "start": "2026-08-02T12:00:00.000Z", "score": {}}],
    )

    class _Client:
        def get_workout_by_id(self, workout_id, *, optional=False):
            return None

    handle_whoop_event(
        tmp_db,
        {"user_id": 1, "id": "gone", "type": "workout.updated"},
        client=_Client(),
    )
    assert tmp_db.execute("SELECT COUNT(*) FROM workouts WHERE id = 'gone'").fetchone()[0] == 0


def test_payload_roundtrip_matches_whoop_signing_input():
    payload = {"user_id": 456, "id": "550e8400-e29b-41d4-a716-446655440000", "type": "sleep.updated", "trace_id": "t"}
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = _sign(body)
    assert verify_whoop_signature(body, TIMESTAMP, signature, SECRET)
