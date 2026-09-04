"""Eleven derived reads: formulas, calibrating paths, no synthetic points."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from thaalam import db
from thaalam.services.derived_metrics import recompute
from thaalam.services.reads_service import (
    CARDIAC_MIN_MATCHED,
    READ_ORDER,
    STAGE_WINDOW,
    compute_and_store_reads,
    get_read_dive_payload,
    get_reads_payload,
    get_runway_payload,
)

USER_ID = 42
ORIGIN = datetime(2026, 1, 15, 7, 0, 0)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _seed_profile(con) -> None:
    db.upsert_profile(
        con,
        {"user_id": USER_ID, "email": "a@b.c", "first_name": "Ada", "last_name": "Lovelace"},
    )


def _seed_night(
    con,
    index: int,
    *,
    hrv: float = 50.0,
    recovery: int = 70,
    strain: float = 10.0,
    rem_h: float = 1.8,
    deep_h: float = 1.2,
    light_h: float = 4.0,
    in_bed_h: float = 8.0,
    awake_min: float = 20.0,
    debt_h: float = 0.4,
    consistency: float = 80.0,
    start_hour: int = 23,
) -> None:
    wake = ORIGIN + timedelta(days=index)
    sleep_end = wake
    sleep_start = datetime(wake.year, wake.month, wake.day, start_hour, 0, 0)
    if start_hour >= 12:
        sleep_start -= timedelta(days=1)
    cycle_id = 1000 + index
    sleep_id = f"sleep-{cycle_id}"
    in_bed_ms = int(in_bed_h * 3_600_000)
    rem_ms = int(rem_h * 3_600_000)
    deep_ms = int(deep_h * 3_600_000)
    light_ms = int(light_h * 3_600_000)
    awake_ms = int(awake_min * 60_000)
    debt_ms = int(debt_h * 3_600_000)
    db.upsert_cycles(
        con,
        [
            {
                "id": cycle_id,
                "user_id": USER_ID,
                "start": _iso(wake),
                "end": _iso(wake + timedelta(hours=16)),
                "timezone_offset": "+00:00",
                "score_state": "SCORED",
                "score": {"strain": strain, "average_heart_rate": 70, "kilojoule": 2000},
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
                    "sleep_performance_percentage": 85,
                    "sleep_consistency_percentage": consistency,
                    "sleep_efficiency_percentage": 90,
                    "stage_summary": {
                        "total_in_bed_time_milli": in_bed_ms,
                        "total_awake_time_milli": awake_ms,
                        "total_no_data_time_milli": 0,
                        "total_light_sleep_time_milli": light_ms,
                        "total_slow_wave_sleep_time_milli": deep_ms,
                        "total_rem_sleep_time_milli": rem_ms,
                        "sleep_cycle_count": 4,
                        "disturbance_count": 8,
                    },
                    "sleep_needed": {
                        "baseline_milli": int(7.5 * 3_600_000),
                        "need_from_sleep_debt_milli": debt_ms,
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
                "created_at": _iso(sleep_end),
                "score_state": "SCORED",
                "score": {
                    "recovery_score": recovery,
                    "hrv_rmssd_milli": hrv,
                    "resting_heart_rate": 54,
                },
            }
        ],
    )


def _seed_workout(
    con,
    *,
    wid: str,
    day: int,
    sport_id: int,
    sport_name: str,
    kilojoule: float | None,
    hr: int | None,
    hour: int = 12,
) -> None:
    start = ORIGIN + timedelta(days=day, hours=hour - 7)
    payload = {
        "id": wid,
        "user_id": USER_ID,
        "start": _iso(start),
        "end": _iso(start + timedelta(hours=1)),
        "sport_id": sport_id,
        "sport_name": sport_name,
        "score_state": "SCORED",
        "score": {},
    }
    if kilojoule is not None:
        payload["score"]["kilojoule"] = kilojoule
    if hr is not None:
        payload["score"]["average_heart_rate"] = hr
    db.upsert_workouts(con, [payload])


def _by_id(payload: dict) -> dict:
    return {row["id"]: row for row in payload["reads"]}


def test_empty_store_returns_eleven_calibrating_rows_without_fake_sparklines(tmp_db):
    _seed_profile(tmp_db)
    payload = get_reads_payload(tmp_db)
    assert payload["present"] is True
    assert [row["id"] for row in payload["reads"]] == READ_ORDER
    assert len(payload["reads"]) == 11
    for row in payload["reads"]:
        assert row["calibrating"] is True
        assert row["sparkline"] == []
        assert "calibrating" in row["finding"]
        assert row["progress"] is not None
        assert row["progress_needed"] is not None


def test_stage_dependency_calibrating_before_60_nights(tmp_db):
    _seed_profile(tmp_db)
    for i in range(25):
        rem = 1.2 + 0.04 * i
        _seed_night(tmp_db, i, hrv=40 + rem * 8, rem_h=rem, deep_h=1.1, light_h=4.0)
    payload = _by_id(get_reads_payload(tmp_db))
    row = payload["stage_dependency"]
    assert row["calibrating"] is True
    assert row["progress"] == 25
    assert row["progress_needed"] == STAGE_WINDOW
    assert row["sparkline"] == []
    dive = get_read_dive_payload(tmp_db, "stage_dependency")["dive"]
    assert dive["calibrating"] is True
    assert dive["variance"] == []
    assert len(dive["stacked_14"]) == 14
    assert all("rem" in point and "deep" in point and "light" in point for point in dive["stacked_14"])


def test_stage_dependency_ready_at_60_nights_tracks_rem(tmp_db):
    _seed_profile(tmp_db)
    for i in range(STAGE_WINDOW + 2):
        rem = 0.8 + 0.03 * (i % 20)
        hrv = 35 + rem * 12 + 0.2 * (i % 3)
        _seed_night(tmp_db, i, hrv=hrv, rem_h=rem, deep_h=1.1, light_h=4.2, strain=8 + (i % 5))
    payload = _by_id(get_reads_payload(tmp_db))
    row = payload["stage_dependency"]
    assert row["calibrating"] is False
    assert row["value"] is not None
    assert row["unit"] == "%"
    assert "REM" in row["finding"] or "Deep" in row["finding"] or "Light" in row["finding"]
    dive = get_read_dive_payload(tmp_db, "stage_dependency")["dive"]
    assert dive["calibrating"] is False
    pcts = [item["pct"] for item in dive["variance"]]
    assert pcts
    assert pytest.approx(sum(pcts), abs=0.2) == 100
    assert dive["dominant"] in {"REM", "Deep", "Light"}


def test_restorative_yield_is_rem_plus_sws_over_hours_in_bed(tmp_db):
    _seed_profile(tmp_db)
    for i in range(21):
        _seed_night(tmp_db, i, rem_h=2.0, deep_h=1.0, in_bed_h=8.0, hrv=50 + i * 0.1)
    payload = _by_id(get_reads_payload(tmp_db))
    row = payload["restorative_yield"]
    assert row["calibrating"] is False
    # (2h REM + 1h SWS) / 8h in bed = 0.375 h/h = 22.5 min/h
    assert row["value"] == pytest.approx(22.5, abs=0.2)
    assert row["unit"] == "min/h"
    assert "21-night mean" in row["finding"]
    assert row["sparkline"]
    assert all(isinstance(v, (int, float)) for v in row["sparkline"])


def test_hyperarousal_flags_only_when_debt_and_latency_are_both_high(tmp_db):
    _seed_profile(tmp_db)
    # 12 calm, 3 high-debt-only, 3 long-latency-only, 2 both — 75th percentile
    # sits between the calm cluster and the high cluster.
    for i in range(12):
        _seed_night(tmp_db, i, debt_h=0.3, awake_min=15, hrv=55)
    for i in range(12, 15):
        _seed_night(tmp_db, i, debt_h=3.0, awake_min=15, hrv=48)  # debt only
    for i in range(15, 18):
        _seed_night(tmp_db, i, debt_h=0.3, awake_min=80, hrv=48)  # latency only
    _seed_night(tmp_db, 18, debt_h=3.0, awake_min=80, hrv=40)  # both
    _seed_night(tmp_db, 19, debt_h=3.2, awake_min=88, hrv=38)  # both, last night
    payload = _by_id(get_reads_payload(tmp_db))
    row = payload["hyperarousal"]
    assert row["calibrating"] is False
    assert row["flagged"] is True
    assert row["value"] == pytest.approx(2.0)
    dive = get_read_dive_payload(tmp_db, "hyperarousal")["dive"]
    flagged = [p for p in dive["scatter"] if p["flagged"]]
    assert len(flagged) == 2
    for point in flagged:
        assert point["debt_hours"] >= dive["debt_threshold"]
        assert point["latency_min"] >= dive["latency_threshold"]
    only_debt = [p for p in dive["scatter"] if p["debt_hours"] >= dive["debt_threshold"] and not p["flagged"]]
    only_lat = [p for p in dive["scatter"] if p["latency_min"] >= dive["latency_threshold"] and not p["flagged"]]
    assert only_debt
    assert only_lat


def test_cardiac_efficiency_disables_sport_without_matched_sessions(tmp_db):
    _seed_profile(tmp_db)
    for i in range(16):
        _seed_night(tmp_db, i, hrv=50, strain=10)
    # Running: eight sessions near 400 kJ, HR drifting down.
    for i in range(8):
        _seed_workout(
            tmp_db,
            wid=f"run-{i}",
            day=i + 1,
            sport_id=1,
            sport_name="running",
            kilojoule=400 + (i % 2) * 10,
            hr=155 - i,
        )
    # Cycling: only two sessions — below the matched-load floor.
    _seed_workout(tmp_db, wid="c1", day=2, sport_id=2, sport_name="cycling", kilojoule=700, hr=140)
    _seed_workout(tmp_db, wid="c2", day=8, sport_id=2, sport_name="cycling", kilojoule=710, hr=138)
    payload = _by_id(get_reads_payload(tmp_db))
    row = payload["cardiac_efficiency"]
    assert row["calibrating"] is False
    assert row["unit"] == "bpm"
    assert "running" in row["finding"].lower() or "Running" in row["finding"]
    dive = get_read_dive_payload(tmp_db, "cardiac_efficiency")["dive"]
    sports = {s["sport_name"]: s for s in dive["sports"]}
    assert sports["running"]["enabled"] is True
    assert sports["running"]["matched"] >= CARDIAC_MIN_MATCHED
    assert sports["running"]["delta_bpm"] < 0
    assert sports["cycling"]["enabled"] is False
    assert sports["cycling"]["series"]  # real matched points only, no filler
    assert len(sports["cycling"]["series"]) < CARDIAC_MIN_MATCHED
    assert "swimming" not in sports


def test_cardiac_efficiency_ignores_sessions_outside_kj_window(tmp_db):
    _seed_profile(tmp_db)
    for i in range(16):
        _seed_night(tmp_db, i)
    for i in range(6):
        _seed_workout(
            tmp_db,
            wid=f"run-{i}",
            day=i + 1,
            sport_id=1,
            sport_name="running",
            kilojoule=400,
            hr=150,
        )
    # Far from the 400 kJ median — must not enter the matched series.
    _seed_workout(
        tmp_db,
        wid="run-long",
        day=7,
        sport_id=1,
        sport_name="running",
        kilojoule=800,
        hr=99,
    )
    dive = get_read_dive_payload(tmp_db, "cardiac_efficiency")["dive"]
    running = next(s for s in dive["sports"] if s["sport_name"] == "running")
    hrs = [p["hr"] for p in running["series"]]
    assert 99 not in hrs
    assert all(abs(p["kilojoule"] - 400) / 400 <= 0.08 for p in running["series"])


def test_strain_sensitivity_ols_negative_when_strain_hurts_next_hrv(tmp_db):
    _seed_profile(tmp_db)
    prior = 8.0
    for i in range(30):
        strain = 6.0 + (i % 8)
        hrv = 70.0 - prior * 1.7
        _seed_night(tmp_db, i, hrv=hrv, strain=strain, rem_h=1.5, deep_h=1.2)
        prior = strain
    payload = _by_id(get_reads_payload(tmp_db))
    row = payload["strain_sensitivity"]
    assert row["calibrating"] is False
    assert row["value"] < 0
    assert row["unit"] == "ms/u"
    dive = get_read_dive_payload(tmp_db, "strain_sensitivity")["dive"]
    assert dive["slope"] < 0
    assert dive["scatter"]
    assert dive["calibrating"] is False


def test_recompute_also_stores_reads(tmp_db, monkeypatch):
    monkeypatch.setenv("STEPS_SOURCE", "none")
    _seed_profile(tmp_db)
    for i in range(16):
        _seed_night(tmp_db, i, hrv=45 + i * 0.2, strain=9 + (i % 4))
    recompute(tmp_db, trigger="test", now=ORIGIN + timedelta(days=16))
    stored = db.list_derived_reads(tmp_db, USER_ID)
    assert {row["id"] for row in stored} == set(READ_ORDER)
    runway = db.get_derived_read_dive(tmp_db, "runway", USER_ID)
    assert runway is not None
    assert isinstance(runway["payload"].get("history"), list)


def test_runway_endpoint_exposes_history_without_projection_card_fields(tmp_db):
    _seed_profile(tmp_db)
    for i in range(21):
        _seed_night(tmp_db, i, hrv=60 - i * 0.4, recovery=75 - i)
    payload = get_runway_payload(tmp_db)
    assert payload["present"] is True
    assert payload["history"]
    assert payload["sparkline"]
    assert "cone" not in payload
    assert "projection" not in payload
    assert payload["methodology"]
    assert "90-day" in (payload["finding"] or "") or "ms" in (payload["finding"] or "")


def test_circadian_phase_uses_own_midpoint_not_a_clock_ideal(tmp_db):
    _seed_profile(tmp_db)
    for i in range(28):
        # Stable 23:00 starts, last night delayed two hours.
        start_hour = 2 if i == 27 else 23
        _seed_night(tmp_db, i, start_hour=start_hour, hrv=55 if i < 27 else 42)
    payload = _by_id(get_reads_payload(tmp_db))
    row = payload["circadian_phase"]
    assert row["calibrating"] is False
    assert row["unit"] == "min"
    assert "21-night mean" in row["finding"]
    dive = get_read_dive_payload(tmp_db, "circadian_phase")["dive"]
    assert dive["calendar"]
    assert dive["penalty_bars"]
    assert dive["midpoint_mean_21d"] is not None
    # Last night started 02:00 instead of 23:00 → ~+180 min shift, not vs 00:00.
    assert abs(dive["latest_shift_min"]) > 60


def test_unknown_read_id_is_absent(tmp_db):
    _seed_profile(tmp_db)
    bundle = get_read_dive_payload(tmp_db, "not_a_read")
    assert bundle["present"] is False
    assert bundle["read"] is None
