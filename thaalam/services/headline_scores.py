"""Three headline scores, on three deliberately different scales.

WHOOP's own app leads with Recovery, Sleep and Strain as three identical
percentage rings. These three are the ones it cannot show, one per read
group: sleep quality on 0-100 (sleep), recovery runway on 0-10 days
(load), rhythm composition on 0-1 (rhythm). The scales differ on purpose --
these are different kinds of quantity, and three matching rings would imply
a comparability that is not there.

Only *directional* quantities feed a score. Three of the eleven reads are
descriptive rather than evaluative: `timing_regularity` is a ratio of
explanatory power, `timing_contribution` a percentage split, and
`stage_dependency` names whichever stage dominates variance. None has a
better and a worse end, so averaging them in would move a score for no
reason. They stay reads.

Bands come from the member's own history, not generic cutoffs -- the same
rule the reads already follow. Short history stays calibrating: no score is
invented from nights that are not there.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Any

import duckdb
import numpy as np

from thaalam import db
from thaalam.services import derived_metrics as dm
from thaalam.services import vitality_score as vs

logger = logging.getLogger(__name__)

CALIBRATING_NIGHTS = 14
HISTORY_NIGHTS = 90
DELTA_NIGHTS = 14
MIN_SAMPLE = 8

RUNWAY_MAX_DAYS = 10

# Personal-band percentiles. A night at or above your own 75th percentile
# scores full credit; one at your 10th scores nothing. Inverted for the
# metrics where lower is better.
GOOD_PCT = 75.0
POOR_PCT = 10.0

# Sleep-need fill is the one absolute band here: "did you sleep as much as
# your own sleep need said you needed" means the same thing for everyone.
FILL_FULL = 0.95
FILL_FLOOR = 0.60

# Habit persistence, in days a consistent night still shows in HRV.
HABIT_FULL_DAYS = 3.0


def compute_headline(
    con: duckdb.DuckDBPyConnection,
    *,
    now: datetime | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Build the three headline scores from stored WHOOP rows and reads."""
    from thaalam.services.reads_service import _load_nights

    now = dm._naive_utc(now)
    nights = _load_nights(con)
    reads = {row.get("id"): row for row in db.list_derived_reads(con, user_id)}
    runway = db.get_derived_runway(con, user_id)
    if runway is None:
        from thaalam.services.runway_service import compute_runway

        runway = compute_runway(con, now=now, user_id=user_id)
    vitality = db.get_latest_derived_vitality(con, user_id)

    scores = [
        _sleep_quality(nights, reads),
        _runway_score(runway),
        _rhythm_composition(reads, vitality),
    ]
    return {
        "present": True,
        "computed_at": now.isoformat(),
        "nights": len(nights),
        "calibrating": all(bool(s["calibrating"]) for s in scores),
        "scores": scores,
    }


# ---------------------------------------------------------------------------
# 1. Sleep Quality, 0-100
# ---------------------------------------------------------------------------


def _sleep_quality(
    nights: list[dict[str, Any]], reads: dict[str, Any]
) -> dict[str, Any]:
    methodology = (
        "Sleep quality is the mean of four sub-scores, each on 0-1, scaled to 100. "
        "Restorative yield ((REM + slow-wave) minutes per hour in bed) and sleep "
        "efficiency are banded against your own last 90 nights: your 75th percentile "
        "or better scores 1, your 10th scores 0. Sleep-need fill is hours asleep over "
        "your own WHOOP sleep need, full credit at 95%. Settled nights is the share of "
        "your recent nights the hyperarousal read did not flag. WHOOP's own sleep "
        "performance score is deliberately not one of the inputs. The 14-night delta "
        "compares the three night-history sub-scores on the same bands."
    )
    series = {
        "yield": (_yield_series(nights), True),
        "efficiency": (_series(nights, "efficiency"), True),
        "need_fill": (_fill_series(nights), True),
    }
    usable = max((len(s) for s, _ in series.values()), default=0)
    if usable < CALIBRATING_NIGHTS:
        return _calibrating_score(
            "sleep_quality",
            "Sleep Quality",
            "sleep",
            scale=100,
            decimals=0,
            progress=usable,
            progress_needed=CALIBRATING_NIGHTS,
            methodology=methodology,
        )

    contributors = [
        _night_contributor("yield", "Restorative yield", "min/h", series["yield"], 0),
        _night_contributor(
            "efficiency", "Sleep efficiency", "%", series["efficiency"], 0
        ),
        _night_contributor("need_fill", "Sleep-need fill", "×", series["need_fill"], 0),
    ]
    calm = _settled_contributor(reads.get("hyperarousal"))
    if calm is not None:
        contributors.append(calm)

    subs = [c["sub"] for c in contributors if c["sub"] is not None]
    if not subs:
        return _calibrating_score(
            "sleep_quality",
            "Sleep Quality",
            "sleep",
            scale=100,
            decimals=0,
            progress=usable,
            progress_needed=CALIBRATING_NIGHTS,
            methodology=methodology,
        )

    value = 100.0 * sum(subs) / len(subs)
    delta = _sleep_delta(series, value)
    return {
        "id": "sleep_quality",
        "title": "Sleep Quality",
        "tab": "sleep",
        "value": round(value, 0),
        "scale": 100,
        "decimals": 0,
        "unit": None,
        "state": _sleep_state(value, contributors),
        "delta_14d": delta,
        "calibrating": False,
        "progress": None,
        "progress_needed": None,
        "methodology": methodology,
        "contributors": contributors,
    }


def _sleep_delta(
    series: dict[str, tuple[list[tuple[str, float]], bool]], current: float
) -> float | None:
    """Like-for-like: the night-history sub-scores now versus 14 nights back."""
    now_subs: list[float] = []
    then_subs: list[float] = []
    for values, higher in ((s, h) for s, h in series.values()):
        sample = [v for _, v in values]
        if len(sample) <= DELTA_NIGHTS:
            continue
        window = sample[-HISTORY_NIGHTS:]
        now_sub = _sub(sample[-1], window, higher_better=higher)
        then_sub = _sub(sample[-1 - DELTA_NIGHTS], window, higher_better=higher)
        if now_sub is None or then_sub is None:
            continue
        now_subs.append(now_sub)
        then_subs.append(then_sub)
    if not now_subs:
        return None
    shift = 100.0 * (sum(now_subs) / len(now_subs) - sum(then_subs) / len(then_subs))
    return round(shift, 0)


def _sleep_state(value: float, contributors: list[dict[str, Any]]) -> str:
    weakest = None
    for row in contributors:
        if row["sub"] is None:
            continue
        if weakest is None or row["sub"] < weakest["sub"]:
            weakest = row
    if value >= 80:
        return "sleeping at your own best"
    if value >= 60:
        head = "solid against your own nights"
    elif value >= 40:
        head = "below your own typical night"
    else:
        head = "well under your own typical night"
    if weakest is not None and weakest["sub"] < 0.5:
        return f"{head} — {weakest['name'].lower()} is the drag"
    return head


# ---------------------------------------------------------------------------
# 2. Runway, 0-10 days
# ---------------------------------------------------------------------------


def _runway_score(runway: dict[str, Any] | None) -> dict[str, Any]:
    methodology = (
        "Days until your fitted 7-day recovery slope is projected to cross your own "
        "90-day baseline, holding the current load and sleep pattern constant. Capped "
        "at 10 days. A flat or rising slope projects no crossing at all — that reads as "
        "a full gauge, not an empty one, and the app calls it holding."
    )
    payload = runway or {}
    if not payload or payload.get("calibrating") or not payload.get("present", True):
        return _calibrating_score(
            "runway",
            "Recovery Runway",
            "load",
            scale=RUNWAY_MAX_DAYS,
            decimals=0,
            unit="days",
            progress=payload.get("nights"),
            progress_needed=CALIBRATING_NIGHTS,
            methodology=methodology,
        )

    days = payload.get("days_remaining")
    # No projected crossing is the *best* state, not a missing one.
    holding = days is None
    value = float(RUNWAY_MAX_DAYS) if holding else float(max(0, min(RUNWAY_MAX_DAYS, days)))
    state = payload.get("headline") or ("holding at this load" if holding else "")
    # What the runway is being spent on, as the runway service already
    # apportions it: {label, pct, note}, shares summing to 100.
    contributors = [
        {
            "key": spend["label"],
            "name": spend["label"],
            "sub": None,
            "actual": spend.get("pct"),
            "unit": "%",
            "note": spend.get("note") or "",
        }
        for spend in (payload.get("spend") or [])
        if isinstance(spend, dict) and spend.get("label")
    ]
    return {
        "id": "runway",
        "title": "Recovery Runway",
        "tab": "load",
        "value": value,
        "scale": RUNWAY_MAX_DAYS,
        "decimals": 0,
        "unit": "days",
        "holding": holding,
        "state": state,
        "delta_14d": None,
        "calibrating": False,
        "progress": None,
        "progress_needed": None,
        "methodology": methodology,
        "contributors": contributors,
    }


# ---------------------------------------------------------------------------
# 3. Rhythm Composition, 0-1
# ---------------------------------------------------------------------------


def _rhythm_composition(
    reads: dict[str, Any], vitality: dict[str, Any] | None
) -> dict[str, Any]:
    methodology = (
        "The mean of three sub-scores on 0-1. Midpoint stability is the Vitality "
        "Score's own rhythm component — how far your sleep midpoint drifts from your "
        "21-night mean, full credit under 30 minutes and nothing past 180. Phase shift "
        "is last night's shift against your own circular midpoint on the same curve; it "
        "is the acute reading where midpoint stability is the chronic one, so the two "
        "move apart when one night breaks an otherwise steady pattern. Habit "
        "persistence is how many days a consistent night still shows in your HRV, full "
        "credit at three."
    )
    contributors: list[dict[str, Any]] = []

    stability = _vitality_rhythm_sub(vitality)
    if stability is not None:
        contributors.append(
            {
                "key": "midpoint_stability",
                "name": "Midpoint stability",
                "sub": stability,
                "actual": None,
                "unit": None,
                "note": "drift from your own 21-night sleep midpoint",
            }
        )

    phase = reads.get("circadian_phase")
    shift = _read_value(phase)
    if shift is not None:
        contributors.append(
            {
                "key": "phase_shift",
                "name": "Phase shift",
                "sub": vs.rhythm_sub(abs(shift)),
                "actual": round(shift, 0),
                "unit": "min",
                "note": "last night against your own circular midpoint",
            }
        )

    habit = reads.get("habit_persistence")
    persist = _read_value(habit)
    if persist is not None:
        contributors.append(
            {
                "key": "habit_persistence",
                "name": "Habit persistence",
                "sub": vs.band(persist, HABIT_FULL_DAYS, math.inf, 0.0, math.inf),
                "actual": round(persist, 0),
                "unit": "days",
                "note": "days a consistent night still shows in your HRV",
            }
        )

    subs = [c["sub"] for c in contributors if c["sub"] is not None]
    if not subs:
        return _calibrating_score(
            "rhythm_composition",
            "Rhythm Composition",
            "rhythm",
            scale=1,
            decimals=2,
            progress=_read_progress(reads.get("circadian_phase")),
            progress_needed=CALIBRATING_NIGHTS,
            methodology=methodology,
        )

    value = sum(subs) / len(subs)
    return {
        "id": "rhythm_composition",
        "title": "Rhythm Composition",
        "tab": "rhythm",
        "value": round(value, 2),
        "scale": 1,
        "decimals": 2,
        "unit": None,
        "state": _rhythm_state(value),
        "delta_14d": None,
        "calibrating": False,
        "progress": None,
        "progress_needed": None,
        "methodology": methodology,
        "contributors": contributors,
    }


def _rhythm_state(value: float) -> str:
    if value >= 0.8:
        return "your days are landing on the same clock"
    if value >= 0.6:
        return "broadly regular, with some drift"
    if value >= 0.4:
        return "drifting off your own pattern"
    return "little rhythm left to hold on to"


def _vitality_rhythm_sub(vitality: dict[str, Any] | None) -> float | None:
    for part in (vitality or {}).get("parts") or []:
        if isinstance(part, dict) and part.get("key") == "rhythm":
            sub = part.get("sub")
            try:
                return max(0.0, min(1.0, float(sub)))
            except (TypeError, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _series(nights: list[dict[str, Any]], key: str) -> list[tuple[str, float]]:
    out: list[tuple[str, float]] = []
    for night in nights:
        value = night.get(key)
        if value is None:
            continue
        try:
            out.append((night["date"], float(value)))
        except (TypeError, ValueError):
            continue
    return out


def _yield_series(nights: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """(REM + slow-wave) minutes per hour in bed, night by night."""
    out: list[tuple[str, float]] = []
    for night in nights:
        rem = night.get("rem_hours")
        deep = night.get("deep_hours")
        in_bed = night.get("in_bed_hours")
        if rem is None or deep is None or not in_bed:
            continue
        out.append((night["date"], (float(rem) + float(deep)) * 60.0 / float(in_bed)))
    return out


def _fill_series(nights: list[dict[str, Any]]) -> list[tuple[str, float]]:
    """Hours asleep over your own sleep need, capped at 1."""
    out: list[tuple[str, float]] = []
    for night in nights:
        asleep = night.get("asleep_hours")
        need = night.get("need_hours")
        if asleep is None or not need:
            continue
        out.append((night["date"], min(1.0, float(asleep) / float(need))))
    return out


def _sub(value: float | None, sample: list[float], *, higher_better: bool) -> float | None:
    """0-1 against the member's own distribution for that metric."""
    if value is None or len(sample) < MIN_SAMPLE:
        return None
    if higher_better:
        lo = float(np.percentile(sample, GOOD_PCT))
        floor = float(np.percentile(sample, POOR_PCT))
        if lo <= floor:
            return 1.0 if value >= lo else 0.0
        return vs.band(value, lo, math.inf, floor, math.inf)
    hi = float(np.percentile(sample, 100.0 - GOOD_PCT))
    ceil = float(np.percentile(sample, 100.0 - POOR_PCT))
    if ceil <= hi:
        return 1.0 if value <= hi else 0.0
    return vs.band(value, -math.inf, hi, -math.inf, ceil)


def _night_contributor(
    key: str,
    name: str,
    unit: str,
    series_and_direction: tuple[list[tuple[str, float]], bool],
    decimals: int,
) -> dict[str, Any]:
    series, higher = series_and_direction
    values = [v for _, v in series]
    window = values[-HISTORY_NIGHTS:]
    latest = values[-1] if values else None
    return {
        "key": key,
        "name": name,
        "sub": _sub(latest, window, higher_better=higher),
        "actual": None if latest is None else round(latest, decimals + 2),
        "unit": unit,
        "note": f"last night against your own {len(window)}-night spread",
    }


def _settled_contributor(read: dict[str, Any] | None) -> dict[str, Any] | None:
    """Share of recent nights the hyperarousal read did not flag."""
    if not read or read.get("calibrating"):
        return None
    flagged = read.get("value")
    window = read.get("progress")
    try:
        flagged = float(flagged)
        window = float(window)
    except (TypeError, ValueError):
        return None
    if window <= 0:
        return None
    settled = max(0.0, min(1.0, 1.0 - flagged / window))
    return {
        "key": "settled",
        "name": "Settled nights",
        "sub": settled,
        "actual": round(100.0 * settled, 0),
        "unit": "%",
        "note": f"{int(window - flagged)} of {int(window)} nights outside the hyperarousal quadrant",
    }


def _read_value(read: dict[str, Any] | None) -> float | None:
    if not read or read.get("calibrating"):
        return None
    try:
        return float(read.get("value"))
    except (TypeError, ValueError):
        return None


def _read_progress(read: dict[str, Any] | None) -> int | None:
    value = (read or {}).get("progress")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _calibrating_score(
    score_id: str,
    title: str,
    tab: str,
    *,
    scale: float,
    decimals: int,
    methodology: str,
    unit: str | None = None,
    progress: int | None = None,
    progress_needed: int | None = None,
) -> dict[str, Any]:
    """No score yet. Empty stays empty -- nothing here is invented."""
    return {
        "id": score_id,
        "title": title,
        "tab": tab,
        "value": None,
        "scale": scale,
        "decimals": decimals,
        "unit": unit,
        "state": "calibrating from your own nights",
        "delta_14d": None,
        "calibrating": True,
        "progress": progress,
        "progress_needed": progress_needed,
        "methodology": methodology,
        "contributors": [],
    }
