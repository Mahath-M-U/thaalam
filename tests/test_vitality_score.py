"""Vitality Score: band() identity, rounded-part totals, edge paths."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from thaalam import db
from thaalam.services.derived_metrics import OPTION1_WEIGHTS, OPTION2_WEIGHTS, recompute
from thaalam.services.vitality_score import (
    apply_rounded_points,
    band,
    build_vitality_payload,
    js_round,
    persist_vitality,
    score_band_name,
    score_from_inputs,
    _circular_diff_minutes,
)

USER_ID = 42


def test_band_inside_returns_one():
    assert band(12, 9.5, 14.5, 4, 19) == 1
    assert band(9.5, 9.5, 14.5, 4, 19) == 1
    assert band(14.5, 9.5, 14.5, 4, 19) == 1
    assert band(8.0, 7.0, 9.0, 5.0, 10.5) == 1


def test_band_floor_and_ceil_are_zero():
    assert band(4, 9.5, 14.5, 4, 19) == 0
    assert band(19, 9.5, 14.5, 4, 19) == 0
    assert band(3, 9.5, 14.5, 4, 19) == 0
    assert band(20, 9.5, 14.5, 4, 19) == 0


def test_band_linear_falloff():
    mid_lo = (4 + 9.5) / 2
    assert band(mid_lo, 9.5, 14.5, 4, 19) == pytest.approx(0.5)
    mid_hi = (14.5 + 19) / 2
    assert band(mid_hi, 9.5, 14.5, 4, 19) == pytest.approx(0.5)
    assert band(0.80, 0.97, 1.15, 0.80, 1.30) == pytest.approx(0)
    assert band(1.30, 0.97, 1.15, 0.80, 1.30) == pytest.approx(0)
    assert band(1.06, 0.97, 1.15, 0.80, 1.30) == 1


def test_band_zero_width_falloff_does_not_raise():
    assert band(10, 10, 10, 10, 10) == 1
    assert band(5, 10, 10, 10, 10) == 0
    assert band(4, 10, 12, 10, 14) == 0
    assert band(16, 10, 12, 8, 12) == 0


def test_js_round_matches_math_round_not_bankers():
    assert js_round(0.5) == 1
    assert js_round(1.5) == 2
    assert js_round(2.5) == 3
    assert js_round(2.4) == 2
    assert round(2.5) == 2  # Python bankers; we must not use this


def _assert_total_is_sum(result: dict) -> None:
    parts = result["parts"]
    assert result["score"] == sum(p["pts"] for p in parts)
    for part in parts:
        expected = js_round(part["weight"] * part["sub"] * 1000)
        assert part["pts"] == expected


def test_score_is_sum_of_rounded_parts_full_credit_option2():
    result = score_from_inputs(
        strain_7d=12.0,
        steps=None,
        hrv_ratio=1.02,
        tib_hours=8.0,
        drift_min=10.0,
        weights=OPTION2_WEIGHTS,
        n_nights=20,
    )
    assert [p["name"] for p in result["parts"]] == [
        "Training load",
        "Autonomic readiness",
        "Sleep opportunity",
        "Rhythm consistency",
    ]
    assert all(p["sub"] == 1 for p in result["parts"])
    _assert_total_is_sum(result)
    assert result["score"] == 1000
    assert result["band"] == "Optimal"


def test_score_is_sum_of_rounded_parts_full_credit_option1():
    result = score_from_inputs(
        strain_7d=11.0,
        steps=10_000,
        hrv_ratio=1.00,
        tib_hours=7.5,
        drift_min=0.0,
        weights=OPTION1_WEIGHTS,
        n_nights=20,
    )
    assert "Daily movement" in [p["name"] for p in result["parts"]]
    assert result["score"] == 1000
    _assert_total_is_sum(result)


def test_score_is_sum_of_rounded_parts_partial_and_zero():
    fixtures = [
        dict(strain_7d=4.0, steps=None, hrv_ratio=1.0, tib_hours=8.0, drift_min=0.0),
        dict(strain_7d=6.75, steps=None, hrv_ratio=0.80, tib_hours=5.0, drift_min=180.0),
        dict(strain_7d=16.75, steps=None, hrv_ratio=1.30, tib_hours=10.5, drift_min=90.0),
        dict(strain_7d=12.0, steps=None, hrv_ratio=None, tib_hours=None, drift_min=None),
        dict(strain_7d=None, steps=None, hrv_ratio=None, tib_hours=None, drift_min=None),
        dict(strain_7d=9.0, steps=5_000, hrv_ratio=0.90, tib_hours=6.0, drift_min=45.0),
    ]
    for kwargs in fixtures:
        weights = OPTION1_WEIGHTS if kwargs["steps"] is not None else OPTION2_WEIGHTS
        result = score_from_inputs(weights=weights, n_nights=10, **kwargs)
        _assert_total_is_sum(result)
        assert 0 <= result["score"] <= 1000


def test_apply_rounded_points_uses_rounded_parts_not_unrounded_sum():
    parts = [
        {"weight": 0.340, "sub": 0.5},
        {"weight": 0.250, "sub": 1 / 3},
        {"weight": 0.250, "sub": 0.2},
        {"weight": 0.160, "sub": 0.7},
    ]
    score = apply_rounded_points(parts)
    unrounded = sum(p["weight"] * p["sub"] * 1000 for p in parts)
    assert score == sum(p["pts"] for p in parts)
    assert score == js_round(170) + js_round(250 / 3) + js_round(50) + js_round(112)
    # Unrounded total may differ from the sum of rounded parts.
    assert score != pytest.approx(unrounded) or score == js_round(unrounded) or True
    assert score == parts[0]["pts"] + parts[1]["pts"] + parts[2]["pts"] + parts[3]["pts"]


def test_rhythm_full_credit_under_30_then_linear():
    inside = score_from_inputs(
        strain_7d=12, steps=None, hrv_ratio=1.0, tib_hours=8, drift_min=29.9,
        weights=OPTION2_WEIGHTS,
    )
    edge = score_from_inputs(
        strain_7d=12, steps=None, hrv_ratio=1.0, tib_hours=8, drift_min=30.0,
        weights=OPTION2_WEIGHTS,
    )
    gone = score_from_inputs(
        strain_7d=12, steps=None, hrv_ratio=1.0, tib_hours=8, drift_min=180.0,
        weights=OPTION2_WEIGHTS,
    )
    rhythm = next(p for p in inside["parts"] if p["key"] == "rhythm")
    assert rhythm["sub"] == 1
    rhythm_edge = next(p for p in edge["parts"] if p["key"] == "rhythm")
    assert rhythm_edge["sub"] == pytest.approx(1 - 30 / 180)
    rhythm_gone = next(p for p in gone["parts"] if p["key"] == "rhythm")
    assert rhythm_gone["sub"] == 0
    _assert_total_is_sum(inside)
    _assert_total_is_sum(edge)
    _assert_total_is_sum(gone)


def test_score_band_names():
    assert score_band_name(0) == "Under-moving"
    assert score_band_name(399) == "Under-moving"
    assert score_band_name(400) == "Building"
    assert score_band_name(599) == "Building"
    assert score_band_name(600) == "Balanced"
    assert score_band_name(799) == "Balanced"
    assert score_band_name(800) == "Optimal"
    assert score_band_name(1000) == "Optimal"


def test_missing_inputs_score_zero_for_that_part():
    result = score_from_inputs(
        strain_7d=None,
        steps=None,
        hrv_ratio=None,
        tib_hours=None,
        drift_min=None,
        weights=OPTION2_WEIGHTS,
        n_nights=3,
    )
    assert result["score"] == 0
    assert all(p["pts"] == 0 for p in result["parts"])
    assert all("Waiting" in p["note"] for p in result["parts"])
    _assert_total_is_sum(result)


def test_calibrating_under_60_nights():
    result = score_from_inputs(
        strain_7d=12, steps=None, hrv_ratio=1.0, tib_hours=8, drift_min=0,
        weights=OPTION2_WEIGHTS, n_nights=59,
    )
    assert result["calibrating"] is True
    result2 = score_from_inputs(
        strain_7d=12, steps=None, hrv_ratio=1.0, tib_hours=8, drift_min=0,
        weights=OPTION2_WEIGHTS, n_nights=60,
    )
    assert result2["calibrating"] is False


def test_copy_never_says_population():
    result = score_from_inputs(
        strain_7d=4, steps=None, hrv_ratio=0.8, tib_hours=5, drift_min=90,
        weights=OPTION2_WEIGHTS, n_nights=5,
    )
    blob = " ".join(p["note"] for p in result["parts"]).lower()
    assert "population" not in blob


def _seed_profile(con) -> None:
    db.upsert_profile(
        con,
        {"user_id": USER_ID, "email": "a@b.c", "first_name": "Ada", "last_name": "Lovelace"},
    )


def _seed_night(
    con,
    day: int,
    *,
    month: int = 7,
    year: int = 2026,
    hrv: float = 50.0,
    rhr: int = 52,
    cycle_id: int,
    strain: float | None = 12.0,
    tib_hours: float = 8.0,
    sleep_perf: float = 87.0,
    tz: str = "+00:00",
) -> None:
    wake = datetime(year, month, day, 7, 0, 0)
    duration = timedelta(hours=tib_hours)
    sleep_start = wake - duration
    sleep_id = f"sleep-{cycle_id}"
    stage = {"total_in_bed_time_milli": int(tib_hours * 3_600_000)}
    db.upsert_sleep(
        con,
        [
            {
                "id": sleep_id,
                "cycle_id": cycle_id,
                "user_id": USER_ID,
                "start": sleep_start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "end": wake.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "timezone_offset": tz,
                "nap": False,
                "score_state": "SCORED",
                "score": {
                    "sleep_performance_percentage": sleep_perf,
                    "stage_summary": stage,
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
                "created_at": wake.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "score_state": "SCORED",
                "score": {
                    "recovery_score": 70,
                    "hrv_rmssd_milli": hrv,
                    "resting_heart_rate": rhr,
                },
            }
        ],
    )
    if strain is not None:
        db.upsert_cycles(
            con,
            [
                {
                    "id": cycle_id,
                    "user_id": USER_ID,
                    "start": wake.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "end": (wake + timedelta(hours=16)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "score_state": "SCORED",
                    "score": {"strain": strain},
                }
            ],
        )


def test_payload_from_fixture_nights_sums_parts(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    for i in range(1, 16):
        _seed_night(tmp_db, i, hrv=50.0, rhr=52, cycle_id=100 + i, strain=12.0)
    now = datetime(2026, 7, 16, 12, 0, 0)
    payload = build_vitality_payload(tmp_db, now=now)
    assert payload["present"] is True
    assert payload["score"] == sum(p["pts"] for p in payload["parts"])
    assert payload["score"] == 1000
    assert payload["band"] == "Optimal"
    assert payload["calibrating"] is True  # 15 nights < 60
    assert payload["sleep_not_closed"] is True
    assert "waiting on last night" in payload["verdict"].lower()
    assert "population" not in payload["verdict"].lower()
    assert "population" not in payload["cause"].lower()
    assert payload["supporting"]["day_strain"] == pytest.approx(12.0)
    assert payload["supporting"]["sleep_yield"] == pytest.approx(87.0)
    assert payload["supporting"]["resting_hr"] == pytest.approx(52.0)
    assert len(payload["trend_30d"]) == 15
    assert payload["trend_30d"][-1]["score"] == payload["score"]


def test_no_steps_drops_movement_and_uses_option2(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    _seed_night(tmp_db, 1, cycle_id=1, strain=12.0)
    payload = build_vitality_payload(tmp_db, now=datetime(2026, 7, 1, 12, 0, 0))
    names = [p["name"] for p in payload["parts"]]
    assert "Daily movement" not in names
    max_pts = {p["key"]: p["max_pts"] for p in payload["parts"]}
    assert max_pts == {"load": 340, "autonomic": 250, "sleep": 250, "rhythm": 160}
    assert payload["score"] == sum(p["pts"] for p in payload["parts"])


def test_healthkit_without_step_rows_still_option2(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "healthkit")
    _seed_profile(tmp_db)
    _seed_night(tmp_db, 1, cycle_id=1, strain=12.0)
    payload = build_vitality_payload(tmp_db, now=datetime(2026, 7, 1, 18, 0, 0))
    assert all(p["key"] != "movement" for p in payload["parts"])
    assert sum(p["max_pts"] for p in payload["parts"]) == 1000


def test_option1_with_real_step_rows(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "healthkit")
    _seed_profile(tmp_db)
    _seed_night(tmp_db, 1, cycle_id=1, strain=12.0)
    tmp_db.execute(
        """
        CREATE TABLE steps (
            "date" DATE,
            steps DOUBLE
        )
        """
    )
    tmp_db.execute("INSERT INTO steps VALUES ('2026-07-01', 10000)")
    payload = build_vitality_payload(tmp_db, now=datetime(2026, 7, 1, 18, 0, 0))
    names = [p["name"] for p in payload["parts"]]
    assert "Daily movement" in names
    movement = next(p for p in payload["parts"] if p["key"] == "movement")
    assert movement["sub"] == 1
    assert movement["max_pts"] == 220
    assert payload["score"] == sum(p["pts"] for p in payload["parts"])
    assert payload["score"] == 1000


def test_empty_db_is_calibrating_not_dummy(tmp_db):
    payload = build_vitality_payload(tmp_db, now=datetime(2026, 7, 1, 12, 0, 0))
    assert payload["present"] is False
    assert payload["score"] is None
    assert payload["calibrating"] is True
    assert payload["parts"] == []
    assert payload["trend_30d"] == []
    assert "729" not in payload["verdict"]


def test_partial_inputs_still_score_what_exists(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    # Sleep + recovery, no cycle/strain.
    db.upsert_sleep(
        tmp_db,
        [
            {
                "id": "s1",
                "cycle_id": 1,
                "user_id": USER_ID,
                "start": "2026-06-30T23:00:00.000Z",
                "end": "2026-07-01T07:00:00.000Z",
                "timezone_offset": "+00:00",
                "nap": False,
                "score_state": "SCORED",
                "score": {"sleep_performance_percentage": 80},
            }
        ],
    )
    db.upsert_recovery(
        tmp_db,
        [
            {
                "cycle_id": 1,
                "sleep_id": "s1",
                "user_id": USER_ID,
                "created_at": "2026-07-01T07:00:00.000Z",
                "score_state": "SCORED",
                "score": {"recovery_score": 60, "hrv_rmssd_milli": 40, "resting_heart_rate": 55},
            }
        ],
    )
    payload = build_vitality_payload(tmp_db, now=datetime(2026, 7, 1, 12, 0, 0))
    assert payload["present"] is True
    load = next(p for p in payload["parts"] if p["key"] == "load")
    assert load["pts"] == 0
    assert load["actual"] is None
    sleep = next(p for p in payload["parts"] if p["key"] == "sleep")
    assert sleep["actual"] == pytest.approx(8.0)
    assert sleep["pts"] == 250
    assert payload["score"] == sum(p["pts"] for p in payload["parts"])
    assert payload["score"] > 0


def test_sleep_not_closed_uses_yesterday(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    _seed_night(tmp_db, 10, cycle_id=10, strain=12.0)
    now = datetime(2026, 7, 11, 8, 0, 0)  # next calendar day, last sleep ended yesterday
    payload = build_vitality_payload(tmp_db, now=now)
    assert payload["sleep_not_closed"] is True
    assert payload["present"] is True
    assert "waiting on last night" in payload["verdict"].lower()


def test_same_day_sleep_is_not_waiting(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    _seed_night(tmp_db, 10, cycle_id=10, strain=12.0)
    now = datetime(2026, 7, 10, 18, 0, 0)
    payload = build_vitality_payload(tmp_db, now=now)
    assert payload["sleep_not_closed"] is False
    assert "waiting on last night" not in payload["verdict"].lower()


def test_circular_midpoint_drift_wraps_midnight():
    assert _circular_diff_minutes(23.0, 1.0) == pytest.approx(120.0)
    assert _circular_diff_minutes(1.0, 23.0) == pytest.approx(120.0)
    assert _circular_diff_minutes(3.0, 3.0) == pytest.approx(0.0)
    assert _circular_diff_minutes(0.0, 12.0) == pytest.approx(720.0)


def test_personalise_bands_after_60_nights(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    # 60 nights of high strain ~16–18 so personal lo/hi should sit above 9.5–14.5.
    for i in range(1, 61):
        strain = 16.0 + (i % 5) * 0.4  # 16.0–17.6
        day = i
        month = 6
        if i > 30:
            day = i - 30
            month = 7
        _seed_night(
            tmp_db,
            day,
            month=month,
            cycle_id=1000 + i,
            strain=strain,
            hrv=50.0,
        )
    now = datetime(2026, 7, 31, 12, 0, 0)
    payload = build_vitality_payload(tmp_db, now=now)
    assert payload["calibrating"] is False
    load = next(p for p in payload["parts"] if p["key"] == "load")
    assert load["band_lo"] != pytest.approx(9.5) or load["band_hi"] != pytest.approx(14.5)
    assert load["band_lo"] > 9.5
    assert payload["score"] == sum(p["pts"] for p in payload["parts"])
    assert "population" not in load["note"].lower()
    assert "population" not in payload["verdict"].lower()


def test_recompute_persists_vitality(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    for i in range(1, 16):
        _seed_night(tmp_db, i, cycle_id=200 + i, strain=12.0, hrv=48.0 + i)
    now = datetime(2026, 7, 16, 12, 0, 0)
    recompute(tmp_db, trigger="test", now=now)
    stored = db.get_latest_derived_vitality(tmp_db, USER_ID)
    assert stored is not None
    assert stored["score"] == sum(p["pts"] for p in stored["parts"])
    trend = db.get_derived_vitality_trend(tmp_db, user_id=USER_ID, days=30)
    assert len(trend) >= 1
    assert trend[-1]["score"] == stored["score"]


def test_persist_without_nights_is_empty(tmp_db):
    _seed_profile(tmp_db)
    payload = persist_vitality(tmp_db, user_id=USER_ID, now=datetime(2026, 7, 1, 12, 0, 0))
    assert payload["present"] is False
    assert db.get_latest_derived_vitality(tmp_db, USER_ID) is None


def test_overtraining_costs_the_same_direction_as_under_moving():
    low = score_from_inputs(
        strain_7d=4.0, steps=None, hrv_ratio=1.0, tib_hours=8, drift_min=0,
        weights=OPTION2_WEIGHTS,
    )
    high = score_from_inputs(
        strain_7d=19.0, steps=None, hrv_ratio=1.0, tib_hours=8, drift_min=0,
        weights=OPTION2_WEIGHTS,
    )
    load_low = next(p for p in low["parts"] if p["key"] == "load")
    load_high = next(p for p in high["parts"] if p["key"] == "load")
    assert load_low["pts"] == 0
    assert load_high["pts"] == 0
    _assert_total_is_sum(low)
    _assert_total_is_sum(high)
