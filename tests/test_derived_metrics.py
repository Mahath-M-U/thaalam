"""Derived baselines, token persistence, backfill pagination, reconciliation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from thaalam import db
from thaalam.services.derived_metrics import OPTION2_WEIGHTS, recompute
from thaalam.services.nightly_job import run_nightly_job
from thaalam.sync import backfill_window, reconcile_recent
from thaalam.whoop_client.auth import TOKEN_FILE_PREFIX, WhoopAuth
from thaalam.whoop_client.client import WhoopClient

USER_ID = 42
TEST_KEY = bytes(range(32))


def _seed_profile(con) -> None:
    db.upsert_profile(con, {"user_id": USER_ID, "email": "a@b.c", "first_name": "Ada", "last_name": "Lovelace"})


def _seed_night(con, day: int, *, hrv: float, rhr: int, cycle_id: int) -> None:
    wake_day = day
    sleep_start = datetime(2026, 7, wake_day, 23, 0, 0) - timedelta(days=1)
    sleep_end = datetime(2026, 7, wake_day, 7, 0, 0)
    sleep_id = f"sleep-{cycle_id}"
    db.upsert_sleep(
        con,
        [
            {
                "id": sleep_id,
                "cycle_id": cycle_id,
                "user_id": USER_ID,
                "start": sleep_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "end": sleep_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "timezone_offset": "+00:00",
                "nap": False,
                "score_state": "SCORED",
                "score": {"sleep_performance_percentage": 85},
            }
        ],
    )
    db.upsert_recovery(
        con,
        [
            {
                "cycle_id": cycle_id,
                "sleep_id": sleep_id,
                "user_id": USER_ID,
                "created_at": sleep_end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "score_state": "SCORED",
                "score": {
                    "recovery_score": 70,
                    "hrv_rmssd_milli": hrv,
                    "resting_heart_rate": rhr,
                },
            }
        ],
    )


def test_derived_baseline_from_fixture_rows(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    hrvs = []
    rhrs = []
    for i in range(1, 16):
        hrv = 40.0 + i
        rhr = 50 + (i % 3)
        hrvs.append(hrv)
        rhrs.append(rhr)
        _seed_night(tmp_db, i, hrv=hrv, rhr=rhr, cycle_id=100 + i)
    db.upsert_workouts(
        tmp_db,
        [
            {
                "id": "w1",
                "user_id": USER_ID,
                "start": "2026-07-10T12:00:00.000Z",
                "end": "2026-07-10T13:00:00.000Z",
                "sport_name": "running",
                "score": {"strain": 10},
            },
            {
                "id": "w2",
                "user_id": USER_ID,
                "start": "2026-07-12T12:00:00.000Z",
                "end": "2026-07-12T13:00:00.000Z",
                "sport_name": "cycling",
                "score": {"strain": 12},
            },
        ],
    )

    now = datetime(2026, 7, 16, 12, 0, 0)
    row = recompute(tmp_db, trigger="test", now=now)

    assert row["user_id"] == USER_ID
    assert row["n_nights"] == 15
    assert row["n_sessions"] == 2
    assert row["calibrating"] is False
    assert row["hrv_mean_90d"] == pytest.approx(sum(hrvs) / len(hrvs))
    assert row["rhr_mean_90d"] == pytest.approx(sum(rhrs) / len(rhrs))
    # 23:00 → 07:00 midpoint is 03:00 local.
    assert row["sleep_midpoint_mean_21d"] == pytest.approx(3.0)
    assert row["steps_source"] == "none"
    assert row["weights"] == OPTION2_WEIGHTS
    assert row["yesterday_complete"] is True
    assert row["awaiting_sleep_close"] is True

    stored = db.get_derived_baseline(tmp_db, USER_ID)
    assert stored is not None
    assert stored["n_nights"] == 15
    log_count = tmp_db.execute("SELECT COUNT(*) FROM derived_recompute_log").fetchone()[0]
    assert log_count == 1


def test_calibrating_when_fewer_than_14_nights(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    for i in range(1, 4):
        _seed_night(tmp_db, i, hrv=50.0, rhr=55, cycle_id=i)
    row = recompute(tmp_db, trigger="test", now=datetime(2026, 7, 5, 12, 0, 0))
    assert row["n_nights"] == 3
    assert row["calibrating"] is True


def test_token_rotation_persists_encrypted_refresh(tmp_path, monkeypatch):
    monkeypatch.delenv("WHOOP_TOKEN_KEY", raising=False)
    token_path = tmp_path / "whoop_token.json"
    auth = WhoopAuth(
        "client-id",
        "client-secret",
        token_path=token_path,
        token_key=TEST_KEY,
        token={
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "expires_in": 3600,
            "token_type": "bearer",
        },
    )

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3600,
                "token_type": "bearer",
            }

    def _post(url, data=None, **kwargs):
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "old-refresh"
        return _Resp()

    auth.session.post = _post  # type: ignore[method-assign]
    auth.refresh_access_token()

    raw = token_path.read_bytes()
    assert raw.startswith(TOKEN_FILE_PREFIX)
    assert b"new-refresh" not in raw
    assert b"old-refresh" not in raw
    assert b"new-access" not in raw
    assert auth.token["refresh_token"] == "new-refresh"

    reloaded = WhoopAuth("client-id", "client-secret", token_path=token_path, token_key=TEST_KEY)
    try:
        assert reloaded.token["refresh_token"] == "new-refresh"
        assert reloaded.token["access_token"] == "new-access"
    finally:
        reloaded.close()
        auth.close()


def test_plaintext_token_migrates_to_encrypted(tmp_path, monkeypatch):
    monkeypatch.delenv("WHOOP_TOKEN_KEY", raising=False)
    token_path = tmp_path / "whoop_token.json"
    token_path.write_text(
        json.dumps(
            {
                "access_token": "plain-access",
                "refresh_token": "plain-refresh",
                "expires_at": 9_999_999_999,
                "token_type": "bearer",
            }
        ),
        encoding="utf-8",
    )
    auth = WhoopAuth("client-id", "client-secret", token_path=token_path, token_key=TEST_KEY)
    try:
        assert auth.token["refresh_token"] == "plain-refresh"
        raw = token_path.read_bytes()
        assert raw.startswith(TOKEN_FILE_PREFIX)
        assert b"plain-refresh" not in raw
    finally:
        auth.close()


def test_get_paginated_follows_next_token(monkeypatch):
    monkeypatch.delenv("WHOOP_TOKEN_KEY", raising=False)
    monkeypatch.setattr("thaalam.whoop_client.client.PAGE_DELAY_SECONDS", 0)
    monkeypatch.setattr("thaalam.whoop_client.client.time.sleep", lambda *_a, **_k: None)

    pages = [
        {"records": [{"id": 1}, {"id": 2}], "next_token": "tok-2"},
        {"records": [{"id": 3}], "next_token": None},
    ]
    seen: list[dict] = []

    def fake_get(self, url_slug, params=None, *, optional=False):
        seen.append(dict(params or {}))
        return pages[len(seen) - 1]

    client = WhoopClient(
        "id",
        "secret",
        token={"access_token": "t", "refresh_token": "r", "expires_in": 99_999},
    )
    try:
        monkeypatch.setattr(WhoopClient, "_get", fake_get)
        records = client.get_cycle_collection("2026-01-01", "2026-04-01")
    finally:
        client.close()

    assert [r["id"] for r in records] == [1, 2, 3]
    assert "nextToken" not in seen[0]
    assert seen[0]["limit"] == 25
    assert "start" in seen[0]
    assert "end" in seen[0]
    assert seen[1]["nextToken"] == "tok-2"


def _mock_whoop_client(captured: list) -> MagicMock:
    client = MagicMock()
    client.get_profile.return_value = {
        "user_id": USER_ID,
        "email": "a@b.c",
        "first_name": "Ada",
        "last_name": "Lovelace",
    }
    client.get_body_measurement.return_value = {
        "height_meter": 1.7,
        "weight_kilogram": 65,
        "max_heart_rate": 190,
    }

    def _capture(label):
        def _fn(start_date=None, end_date=None):
            captured.append((label, start_date, end_date))
            if label == "cycles":
                return [
                    {
                        "id": 1,
                        "user_id": USER_ID,
                        "start": start_date,
                        "end": end_date or start_date,
                        "score_state": "SCORED",
                        "score": {"strain": 10.0},
                    }
                ]
            return []

        return _fn

    client.get_cycle_collection.side_effect = _capture("cycles")
    client.get_recovery_collection.side_effect = _capture("recovery")
    client.get_sleep_collection.side_effect = _capture("sleep")
    client.get_workout_collection.side_effect = _capture("workouts")
    return client


def _window_days(start: str, end: str | None) -> float:
    assert end is not None
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    return (end_dt - start_dt).total_seconds() / 86400


def test_backfill_uses_90_day_window_and_pagination(tmp_path):
    captured: list[tuple] = []
    client = _mock_whoop_client(captured)
    db_path = tmp_path / "whoop.duckdb"
    result = backfill_window(client, db_path, days=90)
    assert result["skipped"] is False
    labels = {label for label, _s, _e in captured}
    assert labels == {"cycles", "recovery", "sleep", "workouts"}
    for _label, start, end in captured:
        assert end is not None
        assert _window_days(start, end) == pytest.approx(90, abs=0.05)
    # Collection helpers are the ones that paginate via nextToken; the mock
    # still receives a bounded start/end the same way WhoopClient._get_paginated does.
    assert client.get_cycle_collection.call_count == 1


def test_reconciliation_refetches_seven_days(tmp_path):
    captured: list[tuple] = []
    client = _mock_whoop_client(captured)
    db_path = tmp_path / "whoop.duckdb"
    result = reconcile_recent(client, db_path, days=7)
    assert result["skipped"] is False
    for _label, start, end in captured:
        assert _window_days(start, end) == pytest.approx(7, abs=0.05)


def test_nightly_job_reconciles_then_recomputes(tmp_path, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    captured: list[tuple] = []
    client = _mock_whoop_client(captured)
    db_path = tmp_path / "whoop.duckdb"
    # Pre-seed enough nights so recompute has real WHOOP-shaped rows.
    con = db.get_connection(db_path)
    try:
        _seed_profile(con)
        for i in range(1, 16):
            _seed_night(con, i, hrv=45.0 + i, rhr=54, cycle_id=200 + i)
    finally:
        con.close()

    result = run_nightly_job(db_path, client=client, reconcile_days=7)
    assert result["skipped"] is False
    assert result["reconciliation"]["skipped"] is False
    assert result["baselines"]["n_nights"] == 15
    assert result["baselines"]["hrv_mean_90d"] is not None
    for _label, start, end in captured:
        assert _window_days(start, end) == pytest.approx(7, abs=0.05)
