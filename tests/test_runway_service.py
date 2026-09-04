"""Recovery sustainability runway: slope, cone, crossing, short-history edges."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from thaalam import db
from thaalam.services.derived_metrics import recompute
from thaalam.services.runway_service import (
    CONE_PCT,
    _sleep_opportunity_gap,
    compute_and_store_runway,
    compute_runway,
)

USER_ID = 42
_MS_H = 3_600_000


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _seed_profile(con) -> None:
    db.upsert_profile(
        con,
        {"user_id": USER_ID, "email": "a@b.c", "first_name": "Ada", "last_name": "Lovelace"},
    )


def _seed_day(
    con,
    day: datetime,
    *,
    cycle_id: int,
    recovery: float,
    strain: float = 10.0,
    sleep_start_hour: int = 23,
    sleep_hours: float = 8.0,
    need_hours: float = 8.0,
) -> None:
    sleep_end = day.replace(hour=7, minute=0, second=0, microsecond=0)
    sleep_start = sleep_end - timedelta(hours=sleep_hours)
    if sleep_start_hour != 23:
        sleep_start = day.replace(hour=sleep_start_hour, minute=0, second=0, microsecond=0)
        sleep_end = sleep_start + timedelta(hours=sleep_hours)
    sleep_id = f"sleep-{cycle_id}"
    in_bed_ms = int(sleep_hours * _MS_H)
    need_ms = int(need_hours * _MS_H)
    db.upsert_cycles(
        con,
        [
            {
                "id": cycle_id,
                "user_id": USER_ID,
                "start": _iso(day.replace(hour=7, minute=0, second=0, microsecond=0)),
                "end": _iso(day.replace(hour=7, minute=0, second=0, microsecond=0) + timedelta(days=1)),
                "score_state": "SCORED",
                "score": {"strain": strain},
            }
        ],
    )
    db.upsert_sleep(
        con,
        [
            {
                "id": sleep_id,
                "cycle_id": cycle_id,
                "user_id": USER_ID,
                "start": _iso(sleep_start),
                "end": _iso(sleep_end),
                "timezone_offset": "+00:00",
                "nap": False,
                "score_state": "SCORED",
                "score": {
                    "sleep_performance_percentage": 80,
                    "stage_summary": {"total_in_bed_time_milli": in_bed_ms},
                    "sleep_needed": {
                        "baseline_milli": need_ms,
                        "need_from_sleep_debt_milli": 0,
                        "need_from_recent_strain_milli": 0,
                        "need_from_recent_nap_milli": 0,
                    },
                },
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
                "created_at": _iso(day.replace(hour=7, minute=0, second=0, microsecond=0)),
                "score_state": "SCORED",
                "score": {
                    "recovery_score": recovery,
                    "hrv_rmssd_milli": 50.0,
                    "resting_heart_rate": 55,
                },
            }
        ],
    )


def _seed_future_break(con) -> datetime:
    """30 days at 60, then 7-day decline 72→66 so last stays above the 90d mean."""
    start = datetime(2026, 6, 1, 7, 0, 0)
    for i in range(30):
        _seed_day(
            con,
            start + timedelta(days=i),
            cycle_id=100 + i,
            recovery=60,
            strain=8.0,
            sleep_hours=8.0,
            need_hours=8.0,
        )
    decline = [72, 71, 70, 69, 68, 67, 66]
    for j, rec in enumerate(decline):
        _seed_day(
            con,
            start + timedelta(days=30 + j),
            cycle_id=200 + j,
            recovery=rec,
            strain=16.0,
            sleep_start_hour=1,
            sleep_hours=5.0,
            need_hours=8.0,
        )
    last = start + timedelta(days=36)
    return last


def test_short_history_is_calibrating_with_empty_series(tmp_db):
    _seed_profile(tmp_db)
    start = datetime(2026, 7, 1, 7, 0, 0)
    for i in range(3):
        _seed_day(tmp_db, start + timedelta(days=i), cycle_id=i + 1, recovery=70 - i)
    payload = compute_runway(tmp_db, now=datetime(2026, 7, 4, 12, 0, 0), user_id=USER_ID)
    assert payload["calibrating"] is True
    assert payload["present"] is False
    assert payload["history"] == []
    assert payload["projection"] == []
    assert payload["baseline"] is None
    assert payload["days_remaining"] is None
    assert payload["cone_pct"] == CONE_PCT
    assert payload["spend"] == []
    assert payload["adaptation_window"] is None


def test_declining_load_projects_future_baseline_break(tmp_db):
    _seed_profile(tmp_db)
    last = _seed_future_break(tmp_db)
    now = last + timedelta(hours=5)
    payload = compute_runway(tmp_db, now=now, user_id=USER_ID)

    assert payload["calibrating"] is False
    assert payload["present"] is True
    assert payload["cone_pct"] == 80
    assert payload["baseline"] is not None
    assert payload["days_remaining"] == 4
    assert payload["baseline_break_date"] is not None
    assert payload["history"], "history must be real recovery points"
    assert payload["projection"], "projection comes from the fitted slope"
    hist_dates = {p["date"] for p in payload["history"]}
    assert last.date().isoformat() in hist_dates
    # Never invent history past the last observed recovery.
    assert max(hist_dates) == last.date().isoformat()
    assert all(p["date"] > last.date().isoformat() or p["date"] == last.date().isoformat()
               for p in payload["projection"])
    join = payload["projection"][0]
    assert join["date"] == last.date().isoformat()
    assert join["lo"] == join["yhat"] == join["hi"]
    later = payload["projection"][-1]
    assert later["lo"] <= later["yhat"] <= later["hi"]
    assert payload["baseline_break_date"] in {p["date"] for p in payload["projection"]}
    assert "≈ 4 days at this load" in payload["headline"]
    assert "4 days before your baseline is projected to break" in payload["subtitle"]
    assert payload["what_it_means"]
    assert payload["methodology"]
    assert "80%" in payload["methodology"]
    assert "own-band" not in (payload["methodology"] or "").lower()
    window = payload["adaptation_window"]
    assert window["state"] == "Closing"
    assert len(window["cells"]) == 7
    assert sum(1 for c in window["cells"] if c > 0) == 4
    spend = payload["spend"]
    assert spend
    assert sum(s["pct"] for s in spend) == 100
    labels = {s["label"] for s in spend}
    assert "Strain above absorbable" in labels
    assert "Short sleep opportunity" in labels
    assert payload["cta"]


def test_already_past_baseline_break_is_zero_days(tmp_db):
    _seed_profile(tmp_db)
    start = datetime(2026, 6, 1, 7, 0, 0)
    # 21-day linear drop 80 → 60; last sits below the 90-day mean.
    for i in range(21):
        _seed_day(tmp_db, start + timedelta(days=i), cycle_id=10 + i, recovery=80 - i)
    last = start + timedelta(days=20)
    payload = compute_runway(tmp_db, now=last + timedelta(hours=6), user_id=USER_ID)
    assert payload["calibrating"] is False
    assert payload["days_remaining"] == 0
    assert payload["baseline_break_date"] == last.date().isoformat()
    assert payload["history"][-1]["value"] < payload["baseline"]
    assert payload["adaptation_window"]["state"] == "Closed"
    assert "0 days" in payload["subtitle"]


def test_holding_slope_has_no_projected_break(tmp_db):
    _seed_profile(tmp_db)
    start = datetime(2026, 6, 1, 7, 0, 0)
    for i in range(21):
        _seed_day(tmp_db, start + timedelta(days=i), cycle_id=30 + i, recovery=70 + i * 0.2)
    last = start + timedelta(days=20)
    payload = compute_runway(tmp_db, now=last + timedelta(hours=6), user_id=USER_ID)
    assert payload["calibrating"] is False
    assert payload["days_remaining"] is None
    assert payload["baseline_break_date"] is None
    assert payload["adaptation_window"]["state"] == "Open"
    assert "holding" in payload["headline"]
    # Projection still exists (fitted slope forward) but does not invent history.
    assert payload["projection"]
    assert payload["history"][-1]["date"] == last.date().isoformat()
    for point in payload["projection"][1:]:
        assert point["lo"] <= point["yhat"] <= point["hi"]


def test_recompute_persists_runway_payload(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    last = _seed_future_break(tmp_db)
    recompute(tmp_db, trigger="test", now=last + timedelta(hours=5), user_id=USER_ID)
    stored = db.get_derived_runway(tmp_db, USER_ID)
    assert stored is not None
    assert stored["calibrating"] is False
    assert stored["days_remaining"] == 4
    assert stored["cone_pct"] == 80
    raw = tmp_db.execute("SELECT payload FROM derived_runway WHERE user_id = ?", [USER_ID]).fetchone()
    assert raw is not None
    parsed = json.loads(raw[0]) if isinstance(raw[0], str) else raw[0]
    assert parsed["history"]


def test_compute_and_store_round_trip(tmp_db):
    _seed_profile(tmp_db)
    last = _seed_future_break(tmp_db)
    payload = compute_and_store_runway(
        tmp_db, now=last + timedelta(hours=5), user_id=USER_ID
    )
    stored = db.get_derived_runway(tmp_db, USER_ID)
    assert stored is not None
    assert stored["days_remaining"] == payload["days_remaining"]
    assert stored["baseline_break_date"] == payload["baseline_break_date"]


def test_gap_in_last_week_still_projects_real_history(tmp_db):
    """A missing recovery in the last 7 calendar days is not short history."""
    _seed_profile(tmp_db)
    start = datetime(2026, 6, 1, 7, 0, 0)
    skip = 27  # one hole inside the last week of a 30-day series
    for i in range(30):
        if i == skip:
            continue
        _seed_day(tmp_db, start + timedelta(days=i), cycle_id=400 + i, recovery=70 - (i % 5))
    last = start + timedelta(days=29)
    payload = compute_runway(tmp_db, now=last + timedelta(hours=6), user_id=USER_ID)
    assert payload["calibrating"] is False
    assert payload["present"] is True
    hist_dates = {p["date"] for p in payload["history"]}
    assert (start + timedelta(days=skip)).date().isoformat() not in hist_dates
    assert last.date().isoformat() in hist_dates
    assert payload["projection"]
    assert payload["as_of"] == last.date().isoformat()


def test_sleep_spend_dates_by_wake_not_bedtime(tmp_db):
    """Main sleeps that start the evening before still land in the 7-day window."""
    _seed_profile(tmp_db)
    start = datetime(2026, 6, 1, 7, 0, 0)
    for i in range(21):
        short = i >= 14
        _seed_day(
            tmp_db,
            start + timedelta(days=i),
            cycle_id=500 + i,
            recovery=70,
            strain=10.0,
            sleep_hours=5.0 if short else 8.0,
            need_hours=8.0,
        )
    last = start + timedelta(days=20)
    gap, note = _sleep_opportunity_gap(tmp_db, last.date() - timedelta(days=6), last.date())
    assert gap == pytest.approx(3.0, abs=0.05)
    assert "5.0h" in note
    payload = compute_runway(tmp_db, now=last + timedelta(hours=6), user_id=USER_ID)
    sleep_spend = next(s for s in payload["spend"] if s["label"] == "Short sleep opportunity")
    assert sleep_spend["pct"] > 0


def test_as_of_is_last_observed_not_clock_today(tmp_db):
    _seed_profile(tmp_db)
    last = _seed_future_break(tmp_db)
    now = last + timedelta(days=3, hours=4)
    payload = compute_runway(tmp_db, now=now, user_id=USER_ID)
    assert payload["calibrating"] is False
    assert payload["as_of"] == last.date().isoformat()
    assert payload["computed_on"] == now.date().isoformat()
    assert payload["as_of"] != payload["computed_on"]
    assert max(p["date"] for p in payload["history"]) == last.date().isoformat()


def test_now_bounds_future_recoveries(tmp_db):
    _seed_profile(tmp_db)
    start = datetime(2026, 6, 1, 7, 0, 0)
    for i in range(30):
        _seed_day(tmp_db, start + timedelta(days=i), cycle_id=600 + i, recovery=68)
    cutoff = start + timedelta(days=19)
    payload = compute_runway(tmp_db, now=cutoff + timedelta(hours=8), user_id=USER_ID)
    assert payload["as_of"] == cutoff.date().isoformat()
    assert max(p["date"] for p in payload["history"]) == cutoff.date().isoformat()
    assert all(p["date"] <= cutoff.date().isoformat() for p in payload["history"])
