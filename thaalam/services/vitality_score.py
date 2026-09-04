"""Vitality Score 0–1000 — band() + rounded component points.

The displayed total is always the arithmetic sum of rounded component
points. Weights are fractions of 1000 (0.300, 0.220, …) so the JS
`Math.round(weight * sub * 1000)` reduction ports identically.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import duckdb

from thaalam import db
from thaalam.services import derived_metrics as dm

logger = logging.getLogger(__name__)

PERSONALISE_NIGHTS = 60
TREND_DAYS = 30
DELTA_DAYS = 14
HRV_WINDOW_DAYS = 90
STRAIN_WINDOW_DAYS = 7
MIDPOINT_NIGHTS = 21
DAY_STRAIN_MAX = 21.0

# Default optimal bands (used until ≥60 nights).
DEFAULT_BANDS: dict[str, dict[str, float]] = {
    "load": {"lo": 9.5, "hi": 14.5, "floor": 4.0, "ceil": 19.0},
    "movement": {"lo": 8000.0, "hi": 13000.0, "floor": 2500.0, "ceil": 20000.0},
    "autonomic": {"lo": 0.97, "hi": 1.15, "floor": 0.80, "ceil": 1.30},
    "sleep": {"lo": 7.0, "hi": 9.0, "floor": 5.0, "ceil": 10.5},
}

RHYTHM_FULL_CREDIT_MIN = 30.0
RHYTHM_FALLOFF_MIN = 180.0

COMPONENT_ORDER = ("load", "movement", "autonomic", "sleep", "rhythm")

COMPONENT_NAMES = {
    "load": "Training load",
    "movement": "Daily movement",
    "autonomic": "Autonomic readiness",
    "sleep": "Sleep opportunity",
    "rhythm": "Rhythm consistency",
}

COMPONENT_UNITS = {
    "load": "strain",
    "movement": "steps",
    "autonomic": "ratio",
    "sleep": "hours",
    "rhythm": "minutes",
}

BAND_LADDER = (
    (0, 399, "Under-moving"),
    (400, 599, "Building"),
    (600, 799, "Balanced"),
    (800, 1000, "Optimal"),
)


def band(v: float, lo: float, hi: float, floor: float, ceil: float) -> float:
    """1 inside [lo, hi], linear falloff to 0 at floor / ceil."""
    if v >= lo and v <= hi:
        return 1
    if v < lo:
        denom = lo - floor
        if denom == 0:
            return 0
        return max(0, (v - floor) / denom)
    denom = ceil - hi
    if denom == 0:
        return 0
    return max(0, (ceil - v) / denom)


def js_round(x: float) -> int:
    """Math.round — half away from zero toward +inf for positive values."""
    if x >= 0:
        return int(math.floor(x + 0.5))
    return int(math.ceil(x - 0.5))


def apply_rounded_points(parts: list[dict[str, Any]]) -> int:
    """Port of: parts.forEach(p => p.pts = Math.round(p.weight * p.sub * 1000));
    score = parts.reduce((a, p) => a + p.pts, 0)
    """
    for part in parts:
        part["pts"] = js_round(float(part["weight"]) * float(part["sub"]) * 1000)
    return sum(int(part["pts"]) for part in parts)


def score_band_name(score: int) -> str:
    for lo, hi, name in BAND_LADDER:
        if lo <= score <= hi:
            return name
    return "Optimal" if score > 1000 else "Under-moving"


def rhythm_sub(drift_min: float) -> float:
    if drift_min < RHYTHM_FULL_CREDIT_MIN:
        return 1
    return max(0.0, 1.0 - drift_min / RHYTHM_FALLOFF_MIN)


@dataclass
class Night:
    day: date
    strain: float | None = None
    hrv: float | None = None
    rhr: float | None = None
    recovery: float | None = None
    sleep_perf: float | None = None
    tib_hours: float | None = None
    midpoint_hours: float | None = None
    steps: float | None = None


def build_vitality_payload(
    con: duckdb.DuckDBPyConnection,
    *,
    now: datetime | None = None,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the current score, parts, and 30-day trend from stored WHOOP rows."""
    now = dm._naive_utc(now)
    if baseline is None:
        baseline = db.get_derived_baseline(con) or {}

    nights = _load_nights(con)
    has_steps = any(n.steps is not None for n in nights)
    weights = _resolve_weights(baseline, has_steps=has_steps)

    if not nights:
        return _empty_payload(sleep_not_closed=False)

    last = nights[-1]
    awaiting = last.day < now.date()
    scored = _score_night(last, nights, weights, has_steps=has_steps)
    trend = _trend_for(nights, weights, has_steps=has_steps, last_day=last.day)
    delta = _delta_from_trend(trend, scored["score"])

    payload = _payload_from_scored(
        scored,
        trend=trend,
        delta_14d=delta,
        sleep_not_closed=awaiting,
        supporting=_supporting(last),
    )
    return payload


def persist_vitality(
    con: duckdb.DuckDBPyConnection,
    *,
    user_id: int,
    now: datetime | None = None,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute and store daily vitality rows for the last 30 scored nights."""
    payload = build_vitality_payload(con, now=now, baseline=baseline)
    computed_at = dm._naive_utc(now)
    rows: list[dict[str, Any]] = []
    for point in payload.get("trend_30d") or []:
        rows.append(
            {
                "user_id": user_id,
                "score_date": point["date"],
                "computed_at": computed_at,
                "score": point["score"],
                "band": score_band_name(int(point["score"])),
                "parts": None,
                "calibrating": payload["calibrating"],
                "sleep_not_closed": payload["sleep_not_closed"],
                "verdict": None,
                "cause": None,
                "supporting": None,
                "delta_14d": None,
            }
        )
    if payload.get("present") and payload.get("score") is not None:
        latest_date = None
        if payload.get("trend_30d"):
            latest_date = payload["trend_30d"][-1]["date"]
        rows.append(
            {
                "user_id": user_id,
                "score_date": latest_date or computed_at.date().isoformat(),
                "computed_at": computed_at,
                "score": payload["score"],
                "band": payload["band"],
                "parts": payload["parts"],
                "calibrating": payload["calibrating"],
                "sleep_not_closed": payload["sleep_not_closed"],
                "verdict": payload["verdict"],
                "cause": payload["cause"],
                "supporting": payload["supporting"],
                "delta_14d": payload["delta_14d"],
            }
        )
    if rows:
        db.upsert_derived_vitality_rows(con, rows)
    return payload


def score_from_inputs(
    *,
    strain_7d: float | None,
    steps: float | None,
    hrv_ratio: float | None,
    tib_hours: float | None,
    drift_min: float | None,
    weights: dict[str, int],
    bands: dict[str, dict[str, float]] | None = None,
    n_nights: int = 0,
) -> dict[str, Any]:
    """Pure scoring for tests — same rounding path as the live payload."""
    has_steps = "movement" in weights and steps is not None
    actuals = {
        "load": strain_7d,
        "movement": steps,
        "autonomic": hrv_ratio,
        "sleep": tib_hours,
        "rhythm": drift_min,
    }
    used_bands = bands or dict(DEFAULT_BANDS)
    parts = _build_parts(actuals, weights, used_bands, has_steps=has_steps)
    score = apply_rounded_points(parts)
    return {
        "score": score,
        "band": score_band_name(score),
        "parts": parts,
        "calibrating": n_nights < PERSONALISE_NIGHTS,
    }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _empty_payload(*, sleep_not_closed: bool) -> dict[str, Any]:
    return {
        "present": False,
        "score": None,
        "band": None,
        "parts": [],
        "trend_30d": [],
        "calibrating": True,
        "sleep_not_closed": sleep_not_closed,
        "verdict": "Your vitality score lands here once nights are scored.",
        "cause": "",
        "delta_14d": None,
        "supporting": None,
    }


def _payload_from_scored(
    scored: dict[str, Any],
    *,
    trend: list[dict[str, Any]],
    delta_14d: int | None,
    sleep_not_closed: bool,
    supporting: dict[str, Any],
) -> dict[str, Any]:
    score = int(scored["score"])
    band_name = score_band_name(score)
    calibrating = bool(scored["calibrating"])
    cause = _cause_line(scored["parts"])
    return {
        "present": True,
        "score": score,
        "band": band_name,
        "parts": scored["parts"],
        "trend_30d": trend,
        "calibrating": calibrating,
        "sleep_not_closed": sleep_not_closed,
        "verdict": _verdict(score, band_name, delta_14d, calibrating, sleep_not_closed),
        "cause": cause,
        "delta_14d": delta_14d,
        "supporting": supporting,
    }


def _resolve_weights(baseline: dict[str, Any], *, has_steps: bool) -> dict[str, int]:
    stored = baseline.get("score_weights") or baseline.get("weights")
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except (TypeError, ValueError, json.JSONDecodeError):
            stored = None
    source = (baseline.get("steps_source") or dm.steps_source() or "none").lower()
    if not has_steps or source in ("none", "", "off"):
        if isinstance(stored, dict) and "movement" not in stored:
            return {str(k): int(v) for k, v in stored.items()}
        return dict(dm.OPTION2_WEIGHTS)
    if isinstance(stored, dict) and stored:
        return {str(k): int(v) for k, v in stored.items()}
    return dict(dm.OPTION1_WEIGHTS)


def _score_night(
    night: Night,
    history: list[Night],
    weights: dict[str, int],
    *,
    has_steps: bool,
) -> dict[str, Any]:
    prior = [n for n in history if n.day <= night.day]
    n_nights = len(prior)
    actuals = _actuals_for(night, prior)
    bands = _bands_for(prior, personalise=n_nights >= PERSONALISE_NIGHTS)
    parts = _build_parts(actuals, weights, bands, has_steps=has_steps)
    score = apply_rounded_points(parts)
    return {
        "score": score,
        "band": score_band_name(score),
        "parts": parts,
        "calibrating": n_nights < PERSONALISE_NIGHTS,
        "day": night.day,
    }


def _actuals_for(night: Night, prior: list[Night]) -> dict[str, float | None]:
    strain_window = [
        n.strain
        for n in prior
        if n.strain is not None and n.day >= night.day - timedelta(days=STRAIN_WINDOW_DAYS - 1)
    ]
    strain_7d = sum(strain_window) / len(strain_window) if strain_window else None

    hrv_window = [
        n.hrv
        for n in prior
        if n.hrv is not None and n.day >= night.day - timedelta(days=HRV_WINDOW_DAYS)
    ]
    hrv_mean = sum(hrv_window) / len(hrv_window) if hrv_window else None
    hrv_ratio = None
    if night.hrv is not None and hrv_mean not in (None, 0):
        hrv_ratio = night.hrv / hrv_mean

    midpoints = [n.midpoint_hours for n in prior if n.midpoint_hours is not None][-MIDPOINT_NIGHTS:]
    mid_mean = sum(midpoints) / len(midpoints) if midpoints else None
    drift = None
    if night.midpoint_hours is not None and mid_mean is not None:
        drift = _circular_diff_minutes(night.midpoint_hours, mid_mean)

    return {
        "load": strain_7d,
        "movement": night.steps,
        "autonomic": hrv_ratio,
        "sleep": night.tib_hours,
        "rhythm": drift,
    }


def _bands_for(prior: list[Night], *, personalise: bool) -> dict[str, dict[str, float]]:
    bands = {key: dict(vals) for key, vals in DEFAULT_BANDS.items()}
    if not personalise:
        return bands
    window = [n for n in prior if n.day >= prior[-1].day - timedelta(days=HRV_WINDOW_DAYS)]
    _personalise_from_values(
        bands, "load", _rolling_strain_means(window), DEFAULT_BANDS["load"]
    )
    _personalise_from_values(
        bands,
        "sleep",
        [n.tib_hours for n in window if n.tib_hours is not None],
        DEFAULT_BANDS["sleep"],
    )
    hrv_vals = [n.hrv for n in window if n.hrv is not None]
    hrv_mean = sum(hrv_vals) / len(hrv_vals) if hrv_vals else None
    if hrv_mean:
        ratios = [v / hrv_mean for v in hrv_vals]
        _personalise_from_values(bands, "autonomic", ratios, DEFAULT_BANDS["autonomic"])
    steps_vals = [n.steps for n in window if n.steps is not None]
    if steps_vals:
        _personalise_from_values(bands, "movement", steps_vals, DEFAULT_BANDS["movement"])
    return bands


def _rolling_strain_means(nights: list[Night]) -> list[float]:
    means: list[float] = []
    for i, night in enumerate(nights):
        window_start = night.day - timedelta(days=STRAIN_WINDOW_DAYS - 1)
        vals = [
            n.strain
            for n in nights[: i + 1]
            if n.strain is not None and n.day >= window_start
        ]
        if vals:
            means.append(sum(vals) / len(vals))
    return means


def _personalise_from_values(
    bands: dict[str, dict[str, float]],
    key: str,
    values: list[float],
    default: dict[str, float],
) -> None:
    if len(values) < PERSONALISE_NIGHTS:
        return
    lo = _percentile(values, 25)
    hi = _percentile(values, 75)
    min_width = default["hi"] - default["lo"]
    if hi - lo < min_width:
        mid = (lo + hi) / 2.0
        lo = mid - min_width / 2.0
        hi = mid + min_width / 2.0
    floor = default["floor"]
    ceil = default["ceil"]
    lo = min(max(lo, floor), ceil)
    hi = min(max(hi, floor), ceil)
    if hi <= lo:
        hi = min(ceil, lo + min_width)
    bands[key] = {"lo": lo, "hi": hi, "floor": floor, "ceil": ceil}


def _build_parts(
    actuals: dict[str, float | None],
    weights: dict[str, int],
    bands: dict[str, dict[str, float]],
    *,
    has_steps: bool,
) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for key in COMPONENT_ORDER:
        if key not in weights:
            continue
        if key == "movement" and not has_steps:
            continue
        max_pts = int(weights[key])
        actual = actuals.get(key)
        if key == "rhythm":
            band_lo, band_hi = 0.0, RHYTHM_FULL_CREDIT_MIN
            if actual is None:
                sub = 0.0
            else:
                sub = rhythm_sub(actual)
        else:
            spec = bands[key]
            band_lo, band_hi = spec["lo"], spec["hi"]
            if actual is None:
                sub = 0.0
            else:
                sub = band(actual, spec["lo"], spec["hi"], spec["floor"], spec["ceil"])
        parts.append(
            {
                "key": key,
                "name": COMPONENT_NAMES[key],
                "weight": max_pts / 1000.0,
                "max_pts": max_pts,
                "sub": sub,
                "actual": actual,
                "band_lo": band_lo,
                "band_hi": band_hi,
                "unit": COMPONENT_UNITS[key],
                "note": _component_note(key, actual, band_lo, band_hi, sub),
            }
        )
    return parts


def _component_note(
    key: str,
    actual: float | None,
    lo: float,
    hi: float,
    sub: float,
) -> str:
    name = COMPONENT_NAMES[key]
    if actual is None:
        return {
            "load": "Waiting on scored cycles.",
            "movement": "Waiting on a step source.",
            "autonomic": "Waiting on HRV from a closed recovery.",
            "sleep": "Waiting on a closed night.",
            "rhythm": "Waiting on enough nights to place your midpoint.",
        }[key]
    if sub >= 1:
        if key == "rhythm":
            return f"Midpoint drift is inside {int(hi)} minutes."
        return f"Inside the {_fmt_band(key, lo, hi)} band."
    if actual < lo:
        return f"{name} is under the {_fmt_band(key, lo, hi)} band."
    return f"{name} is over the {_fmt_band(key, lo, hi)} band."


def _fmt_band(key: str, lo: float, hi: float) -> str:
    if key == "movement":
        return f"{_fmt_steps(lo)}–{_fmt_steps(hi)}"
    if key == "autonomic":
        return f"{lo:.2f}–{hi:.2f}"
    if key == "sleep":
        return f"{lo:.1f}–{hi:.1f} h"
    if key == "rhythm":
        return f"{int(lo)}–{int(hi)} m"
    return f"{lo:.1f}–{hi:.1f}"


def _fmt_steps(value: float) -> str:
    if value >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return str(int(value))


def _cause_line(parts: list[dict[str, Any]]) -> str:
    if not parts:
        return "Waiting on scored nights."
    if all(p["sub"] >= 1 for p in parts):
        return "You are inside your bands — keep the same rhythm."

    def _fill(part: dict[str, Any]) -> float:
        max_pts = part.get("max_pts") or 0
        return (part["pts"] / max_pts) if max_pts else 0.0

    shortfalls = [p for p in parts if p["sub"] < 1]
    shortfalls.sort(key=_fill)
    worst = shortfalls[0]
    phrases = [_shortfall_phrase(p) for p in shortfalls[:2]]
    decision = _decision_for(worst)
    if len(phrases) == 1:
        text = phrases[0][0].upper() + phrases[0][1:]
        return f"{text} — {decision}"
    return f"{phrases[0][0].upper() + phrases[0][1:]} while {phrases[1]} — {decision}"


def _shortfall_phrase(part: dict[str, Any]) -> str:
    actual = part.get("actual")
    if actual is None:
        return {
            "load": "training load is still waiting on cycles",
            "movement": "steps are not connected",
            "autonomic": "autonomic readiness is waiting on HRV",
            "sleep": "sleep opportunity is waiting on a closed night",
            "rhythm": "rhythm is still settling",
        }[part["key"]]
    lo = part["band_lo"]
    if part["key"] == "load":
        return "training load is over band" if actual > part["band_hi"] else "training load is under band"
    if part["key"] == "movement":
        return "steps fall short" if actual < lo else "steps sit above band"
    if part["key"] == "autonomic":
        return "HRV is under your 90-day mean" if actual < lo else "HRV sits above your usual range"
    if part["key"] == "sleep":
        return "time in bed is short" if actual < lo else "time in bed is long"
    return "sleep midpoint is drifting"


def _decision_for(part: dict[str, Any]) -> str:
    actual = part.get("actual")
    hi = part.get("band_hi")
    high = actual is not None and hi is not None and actual > hi
    return {
        ("load", False): "a training day now would raise the score.",
        ("load", True): "two easy days now buy the load back.",
        ("movement", False): "more walking buys the score back.",
        ("movement", True): "ease the extra movement a little.",
        ("autonomic", False): "protect tonight's sleep before you stack load.",
        ("autonomic", True): "you can absorb work if the night stays long enough.",
        ("sleep", False): "getting to bed on time is the highest-leverage move.",
        ("sleep", True): "a slightly earlier wake would land you in band.",
        ("rhythm", False): "a regular bedtime lands the rhythm points.",
        ("rhythm", True): "a regular bedtime lands the rhythm points.",
    }[(part["key"], high)]


def _verdict(
    score: int,
    band_name: str,
    delta_14d: int | None,
    calibrating: bool,
    sleep_not_closed: bool,
) -> str:
    head = f"Vitality score {score} — {band_name}"
    if calibrating:
        text = f"{head}. Calibrating from your nights so far."
    elif delta_14d is None:
        text = f"{head}, and still gathering a trend."
    elif delta_14d <= -40:
        text = f"{head}, and slipping for two weeks"
    elif delta_14d <= -15:
        text = f"{head}, and easing off"
    elif delta_14d >= 40:
        text = f"{head}, and climbing over two weeks"
    elif delta_14d >= 15:
        text = f"{head}, and trending up"
    else:
        text = f"{head}, and holding"
    if sleep_not_closed:
        text = f"{text} · waiting on last night"
    return text


def _supporting(night: Night) -> dict[str, Any]:
    return {
        "day_strain": night.strain,
        "day_strain_max": DAY_STRAIN_MAX,
        "sleep_yield": night.sleep_perf,
        "resting_hr": night.rhr,
    }


def _trend_for(
    nights: list[Night],
    weights: dict[str, int],
    *,
    has_steps: bool,
    last_day: date,
) -> list[dict[str, Any]]:
    cutoff = last_day - timedelta(days=TREND_DAYS - 1)
    window = [n for n in nights if n.day >= cutoff]
    trend: list[dict[str, Any]] = []
    for night in window:
        history = [n for n in nights if n.day <= night.day]
        scored = _score_night(night, history, weights, has_steps=has_steps)
        trend.append({"date": night.day.isoformat(), "score": int(scored["score"])})
    return trend


def _delta_from_trend(trend: list[dict[str, Any]], current: int) -> int | None:
    if len(trend) < 2:
        return None
    target = None
    latest = date.fromisoformat(trend[-1]["date"])
    want = (latest - timedelta(days=DELTA_DAYS)).isoformat()
    older = [p for p in trend if p["date"] <= want]
    if older:
        target = older[-1]["score"]
    else:
        target = trend[0]["score"]
        if trend[0]["date"] == trend[-1]["date"]:
            return None
    return int(current) - int(target)


def _circular_diff_minutes(a: float, b: float) -> float:
    d = abs(a - b) % 24.0
    if d > 12.0:
        d = 24.0 - d
    return d * 60.0


def _percentile(values: list[float], p: float) -> float:
    xs = sorted(values)
    if not xs:
        raise ValueError("percentile of empty list")
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    f = int(math.floor(k))
    c = min(f + 1, len(xs) - 1)
    if f == c:
        return xs[f]
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def _load_nights(con: duckdb.DuckDBPyConnection) -> list[Night]:
    rows = con.execute(
        """
        SELECT
            s.id,
            s.cycle_id,
            s."start",
            s."end",
            s.timezone_offset,
            s.stage_summary,
            s.sleep_performance_percentage,
            c.strain,
            r.hrv_rmssd_milli,
            r.resting_heart_rate,
            r.recovery_score
        FROM sleep s
        LEFT JOIN cycles c ON c.id = s.cycle_id
        LEFT JOIN recovery r
            ON r.cycle_id = s.cycle_id
            OR CAST(r.sleep_id AS VARCHAR) = CAST(s.id AS VARCHAR)
        WHERE COALESCE(s.nap, FALSE) = FALSE
          AND s."end" IS NOT NULL
        ORDER BY s."end"
        """
    ).fetchall()

    steps_by_day = _load_steps_by_day(con)
    nights: dict[date, Night] = {}
    for row in rows:
        (
            _sleep_id,
            _cycle_id,
            sleep_start,
            sleep_end,
            tz_offset,
            stage_summary,
            sleep_perf,
            strain,
            hrv,
            rhr,
            recovery,
        ) = row
        end_dt = dm._as_datetime(sleep_end)
        if end_dt is None:
            continue
        local_end = end_dt + dm._parse_offset(tz_offset)
        day = local_end.date()
        tib = _tib_hours(sleep_start, sleep_end, stage_summary)
        midpoint = dm._sleep_midpoint_hours(sleep_start, sleep_end, tz_offset)
        night = nights.get(day) or Night(day=day)
        night.strain = _as_float(strain) if _as_float(strain) is not None else night.strain
        night.hrv = _as_float(hrv) if _as_float(hrv) is not None else night.hrv
        night.rhr = _as_float(rhr) if _as_float(rhr) is not None else night.rhr
        night.recovery = _as_float(recovery) if _as_float(recovery) is not None else night.recovery
        night.sleep_perf = _as_float(sleep_perf) if _as_float(sleep_perf) is not None else night.sleep_perf
        night.tib_hours = tib if tib is not None else night.tib_hours
        night.midpoint_hours = midpoint if midpoint is not None else night.midpoint_hours
        night.steps = steps_by_day.get(day, night.steps)
        nights[day] = night

    return [nights[k] for k in sorted(nights)]


def _tib_hours(start: Any, end: Any, stage_summary: Any) -> float | None:
    parsed = stage_summary
    if isinstance(parsed, str):
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = None
    if isinstance(parsed, dict):
        milli = parsed.get("total_in_bed_time_milli")
        if milli is not None:
            try:
                hours = float(milli) / 3_600_000.0
                if hours == hours and hours > 0:
                    return hours
            except (TypeError, ValueError):
                pass
    start_dt = dm._as_datetime(start)
    end_dt = dm._as_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    hours = (end_dt - start_dt).total_seconds() / 3600.0
    if hours <= 0:
        return None
    return hours


def _load_steps_by_day(con: duckdb.DuckDBPyConnection) -> dict[date, float]:
    if not _table_exists(con, "steps"):
        return {}
    try:
        rows = con.execute(
            """
            SELECT "date", steps
            FROM steps
            WHERE steps IS NOT NULL
            """
        ).fetchall()
    except Exception:
        logger.debug("steps table present but not readable", exc_info=True)
        return {}
    out: dict[date, float] = {}
    for raw_day, raw_steps in rows:
        day = _as_date(raw_day)
        steps = _as_float(raw_steps)
        if day is None or steps is None:
            continue
        out[day] = steps
    return out


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    row = con.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE lower(table_name) = lower(?)
        LIMIT 1
        """,
        [name],
    ).fetchone()
    return row is not None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:
        return None
    return out


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        parsed = dm._as_datetime(value)
        return parsed.date() if parsed else None
