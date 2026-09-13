"""The three headline scores: scales, calibrating states, honest emptiness."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

from thaalam import db
from thaalam.services.derived_metrics import recompute
from thaalam.services.headline_scores import (
    CALIBRATING_NIGHTS,
    RUNWAY_MAX_DAYS,
    _rhythm_composition,
    _runway_score,
    _settled_contributor,
    _sub,
    compute_headline,
)

USER_ID = 42
MS_PER_HOUR = 3_600_000.0


def _seed_profile(con) -> None:
    db.upsert_profile(
        con,
        {"user_id": USER_ID, "email": "a@b.c", "first_name": "Ada", "last_name": "Lovelace"},
    )


def _seed_night(
    con,
    *,
    offset_days: int,
    cycle_id: int,
    rem_h: float = 1.8,
    deep_h: float = 1.6,
    light_h: float = 4.2,
    awake_h: float = 0.4,
    in_bed_h: float = 8.0,
    efficiency: float = 92.0,
    hrv: float = 60.0,
    rhr: int = 52,
    strain: float = 11.0,
    recovery: int = 70,
) -> None:
    """One scored night, `offset_days` before a fixed reference wake time."""
    wake = datetime(2026, 9, 13, 7, 0, 0) - timedelta(days=offset_days)
    start = wake - timedelta(hours=in_bed_h)
    sleep_id = f"sleep-{cycle_id}"
    stamp = "%Y-%m-%dT%H:%M:%S.000Z"
    db.upsert_cycles(
        con,
        [
            {
                "id": cycle_id,
                "user_id": USER_ID,
                "created_at": wake.strftime(stamp),
                "start": start.strftime(stamp),
                "end": wake.strftime(stamp),
                "timezone_offset": "+00:00",
                "score_state": "SCORED",
                "score": {"strain": strain, "kilojoule": 8000.0},
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
                "start": start.strftime(stamp),
                "end": wake.strftime(stamp),
                "timezone_offset": "+00:00",
                "nap": False,
                "score_state": "SCORED",
                "score": {
                    "sleep_performance_percentage": 85,
                    "sleep_efficiency_percentage": efficiency,
                    "sleep_consistency_percentage": 80,
                    "stage_summary": {
                        "total_in_bed_time_milli": in_bed_h * MS_PER_HOUR,
                        "total_rem_sleep_time_milli": rem_h * MS_PER_HOUR,
                        "total_slow_wave_sleep_time_milli": deep_h * MS_PER_HOUR,
                        "total_light_sleep_time_milli": light_h * MS_PER_HOUR,
                        "total_awake_time_milli": awake_h * MS_PER_HOUR,
                        "disturbance_count": 3,
                    },
                    "sleep_needed": {
                        "baseline_milli": 7.5 * MS_PER_HOUR,
                        "need_from_sleep_debt_milli": 0.3 * MS_PER_HOUR,
                        "need_from_recent_strain_milli": 0.2 * MS_PER_HOUR,
                        "need_from_recent_nap_milli": 0.0,
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
                "created_at": wake.strftime(stamp),
                "score_state": "SCORED",
                "score": {
                    "recovery_score": recovery,
                    "hrv_rmssd_milli": hrv,
                    "resting_heart_rate": rhr,
                },
            }
        ],
    )


def _seed_history(con, nights: int) -> None:
    _seed_profile(con)
    for i in range(nights):
        _seed_night(con, offset_days=nights - 1 - i, cycle_id=1000 + i)


NOW = datetime(2026, 9, 13, 12, 0, 0)


# ---------------------------------------------------------------------------
# Shape and scales
# ---------------------------------------------------------------------------


def test_three_scores_on_three_scales(tmp_db):
    _seed_history(tmp_db, 40)
    recompute(tmp_db, user_id=USER_ID, now=NOW)
    payload = compute_headline(tmp_db, now=NOW, user_id=USER_ID)

    assert [s["id"] for s in payload["scores"]] == [
        "sleep_quality",
        "runway",
        "rhythm_composition",
    ]
    by_id = {s["id"]: s for s in payload["scores"]}
    assert by_id["sleep_quality"]["scale"] == 100
    assert by_id["runway"]["scale"] == RUNWAY_MAX_DAYS
    assert by_id["rhythm_composition"]["scale"] == 1
    # One score per read group, so each is the entry point to its own tab.
    assert {s["tab"] for s in payload["scores"]} == {"sleep", "load", "rhythm"}


def test_every_score_stays_inside_its_own_scale(tmp_db):
    _seed_history(tmp_db, 40)
    recompute(tmp_db, user_id=USER_ID, now=NOW)
    for score in compute_headline(tmp_db, now=NOW, user_id=USER_ID)["scores"]:
        if score["value"] is None:
            continue
        assert 0 <= score["value"] <= score["scale"], score["id"]


def test_sleep_quality_excludes_the_non_directional_reads(tmp_db):
    """`timing_regularity`, `timing_contribution` and `stage_dependency`
    describe rather than evaluate -- they must not move a quality score."""
    _seed_history(tmp_db, 40)
    recompute(tmp_db, user_id=USER_ID, now=NOW)
    sleep = compute_headline(tmp_db, now=NOW, user_id=USER_ID)["scores"][0]
    keys = {c["key"] for c in sleep["contributors"]}
    assert keys <= {"yield", "efficiency", "need_fill", "settled"}
    assert not keys & {"timing_regularity", "timing_contribution", "stage_dependency"}


def test_sleep_quality_does_not_use_whoops_own_sleep_performance(tmp_db):
    _seed_history(tmp_db, 40)
    recompute(tmp_db, user_id=USER_ID, now=NOW)
    sleep = compute_headline(tmp_db, now=NOW, user_id=USER_ID)["scores"][0]
    assert all("performance" not in (c["key"] or "") for c in sleep["contributors"])


# ---------------------------------------------------------------------------
# Calibrating: empty stays empty
# ---------------------------------------------------------------------------


def test_short_history_calibrates_without_inventing_a_score(tmp_db):
    _seed_history(tmp_db, 5)
    payload = compute_headline(tmp_db, now=NOW, user_id=USER_ID)
    assert payload["calibrating"] is True
    for score in payload["scores"]:
        assert score["value"] is None, score["id"]
        assert score["calibrating"] is True
        assert score["contributors"] == []


def test_empty_database_calibrates_rather_than_raising(tmp_db):
    _seed_profile(tmp_db)
    payload = compute_headline(tmp_db, now=NOW, user_id=USER_ID)
    assert payload["calibrating"] is True
    assert all(s["value"] is None for s in payload["scores"])


def test_calibrating_sleep_reports_progress_towards_the_threshold(tmp_db):
    _seed_history(tmp_db, 6)
    sleep = compute_headline(tmp_db, now=NOW, user_id=USER_ID)["scores"][0]
    assert sleep["progress"] == 6
    assert sleep["progress_needed"] == CALIBRATING_NIGHTS


# ---------------------------------------------------------------------------
# Runway: no projected crossing is the best state, not a missing one
# ---------------------------------------------------------------------------


def test_runway_holding_fills_the_gauge():
    score = _runway_score(
        {"present": True, "calibrating": False, "days_remaining": None, "headline": "holding at this load", "spend": []}
    )
    assert score["holding"] is True
    assert score["value"] == RUNWAY_MAX_DAYS
    assert score["calibrating"] is False


def test_runway_days_are_clamped_to_the_gauge():
    assert _runway_score({"present": True, "days_remaining": 30, "spend": []})["value"] == RUNWAY_MAX_DAYS
    assert _runway_score({"present": True, "days_remaining": 4, "spend": []})["value"] == 4
    at_limit = _runway_score({"present": True, "days_remaining": 0, "spend": []})
    assert at_limit["value"] == 0
    assert at_limit["holding"] is False


def test_runway_calibrating_payload_stays_empty():
    score = _runway_score({"present": True, "calibrating": True, "nights": 6})
    assert score["value"] is None
    assert score["calibrating"] is True


# ---------------------------------------------------------------------------
# Sub-score banding
# ---------------------------------------------------------------------------


def test_sub_higher_is_better_rewards_your_own_good_nights():
    sample = list(range(1, 101))
    assert _sub(100, sample, higher_better=True) == 1.0
    assert _sub(1, sample, higher_better=True) == pytest.approx(0.0, abs=1e-9)
    mid = _sub(50, sample, higher_better=True)
    assert 0.0 < mid < 1.0


def test_sub_lower_is_better_inverts_the_band():
    sample = list(range(1, 101))
    assert _sub(1, sample, higher_better=False) == 1.0
    assert _sub(100, sample, higher_better=False) == pytest.approx(0.0, abs=1e-9)


def test_sub_needs_a_real_sample():
    assert _sub(5, [1, 2, 3], higher_better=True) is None
    assert _sub(None, list(range(50)), higher_better=True) is None


def test_sub_survives_a_flat_history():
    flat = [7.0] * 30
    assert _sub(7.0, flat, higher_better=True) == 1.0
    assert _sub(1.0, flat, higher_better=True) == 0.0
    assert _sub(7.0, flat, higher_better=False) == 1.0
    assert _sub(9.0, flat, higher_better=False) == 0.0


def test_settled_contributor_reads_the_flag_rate():
    settled = _settled_contributor(
        {"id": "hyperarousal", "value": 3.0, "progress": 30, "calibrating": False}
    )
    assert settled["sub"] == pytest.approx(0.9)
    calibrating = _settled_contributor(
        {"id": "hyperarousal", "value": 0.0, "progress": 4, "calibrating": True}
    )
    assert calibrating is None


# ---------------------------------------------------------------------------
# Rhythm
# ---------------------------------------------------------------------------


def test_rhythm_averages_only_the_contributors_it_has():
    reads = {
        "circadian_phase": {"id": "circadian_phase", "value": 10.0, "calibrating": False},
        "habit_persistence": {"id": "habit_persistence", "value": 3.0, "calibrating": False},
    }
    vitality = {"parts": [{"key": "rhythm", "sub": 1.0}]}
    score = _rhythm_composition(reads, vitality)
    assert score["value"] == 1.0
    assert {c["key"] for c in score["contributors"]} == {
        "midpoint_stability",
        "phase_shift",
        "habit_persistence",
    }


def test_rhythm_calibrating_when_no_read_has_landed():
    score = _rhythm_composition({}, None)
    assert score["value"] is None
    assert score["calibrating"] is True


def test_rhythm_phase_shift_falls_off_with_drift():
    near = _rhythm_composition(
        {"circadian_phase": {"value": 5.0, "calibrating": False}}, None
    )
    far = _rhythm_composition(
        {"circadian_phase": {"value": 170.0, "calibrating": False}}, None
    )
    assert near["value"] > far["value"]


# ---------------------------------------------------------------------------
# Storage and the recompute hook
# ---------------------------------------------------------------------------


def test_recompute_stores_the_headline_payload(tmp_db):
    _seed_history(tmp_db, 40)
    recompute(tmp_db, user_id=USER_ID, now=NOW)
    stored = db.get_derived_headline(tmp_db, USER_ID)
    assert stored is not None
    assert [s["id"] for s in stored["scores"]] == [
        "sleep_quality",
        "runway",
        "rhythm_composition",
    ]


def test_total_sleep_need_reaches_the_night_rows(tmp_db):
    from thaalam.services.reads_service import _load_nights

    _seed_history(tmp_db, 20)
    nights = _load_nights(tmp_db)
    assert nights
    # baseline 7.5 + debt 0.3 + strain 0.2, nap 0.
    assert nights[-1]["need_hours"] == pytest.approx(8.0)
    assert nights[-1]["debt_hours"] == pytest.approx(0.3)


def test_runway_contributors_carry_the_spend_breakdown():
    score = _runway_score(
        {
            "present": True,
            "calibrating": False,
            "days_remaining": 5,
            "headline": "≈ 5 days at this load",
            "spend": [
                {"label": "Strain above absorbable", "pct": 60, "note": "over your 28-day chronic load"},
                {"label": "Short sleep opportunity", "pct": 40, "note": "against your own need"},
            ],
        }
    )
    assert [c["name"] for c in score["contributors"]] == [
        "Strain above absorbable",
        "Short sleep opportunity",
    ]
    assert [c["actual"] for c in score["contributors"]] == [60, 40]
    assert all(c["note"] for c in score["contributors"])
