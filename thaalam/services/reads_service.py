"""Eleven derived reads, computed server-side from stored WHOOP rows.

The client never recomputes a baseline, slope, or projection. Empty and
calibrating states degrade explicitly — never synthetic points.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

import duckdb
import numpy as np

from thaalam import db

logger = logging.getLogger(__name__)

MS_PER_HOUR = 3_600_000.0
MS_PER_MIN = 60_000.0

CALIBRATING_NIGHTS = 14
STAGE_WINDOW = 60
SLOPE_WINDOW = 21
YIELD_WINDOW = 21
PHASE_WINDOW = 21
RUNWAY_WINDOW = 21
HABIT_MAX_LAG = 7
CALENDAR_DAYS = 35
SPARKLINE_LEN = 21
CARDIAC_MIN_MATCHED = 4
KJ_TOLERANCE = 0.08
HYPER_PERCENTILE = 75.0

READ_ORDER = [
    "restorative_yield",
    "stage_dependency",
    "hyperarousal",
    "timing_regularity",
    "strain_sensitivity",
    "cardiac_efficiency",
    "adaptation_window",
    "runway",
    "circadian_phase",
    "habit_persistence",
    "timing_contribution",
]

GROUP_SLEEP = "sleep"
GROUP_LOAD = "load"
GROUP_RHYTHM = "rhythm"


def compute_and_store_reads(
    con: duckdb.DuckDBPyConnection,
    *,
    user_id: int | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Compute the eleven reads from stored WHOOP rows and persist them."""
    now = _naive_utc(now)
    resolved_user_id = user_id if user_id is not None else _profile_user_id(con)
    nights = _load_nights(con)
    workouts = _load_workouts(con)
    baseline = db.get_derived_baseline(con, resolved_user_id) if resolved_user_id is not None else None
    hrv_mean_90d = _as_float(baseline.get("hrv_mean_90d") if baseline else None)

    reads: list[dict[str, Any]] = []
    dives: dict[str, Any] = {}

    yield_read, yield_dive = _restorative_yield(nights)
    reads.append(yield_read)
    dives["restorative_yield"] = yield_dive

    stage_read, stage_dive = _stage_dependency(nights)
    reads.append(stage_read)
    dives["stage_dependency"] = stage_dive

    hyper_read, hyper_dive = _hyperarousal(nights)
    reads.append(hyper_read)
    dives["hyperarousal"] = hyper_dive

    timing_read, timing_dive = _timing_regularity(nights)
    reads.append(timing_read)
    dives["timing_regularity"] = timing_dive

    strain_read, strain_dive = _strain_sensitivity(nights)
    reads.append(strain_read)
    dives["strain_sensitivity"] = strain_dive

    cardiac_read, cardiac_dive = _cardiac_efficiency(workouts)
    reads.append(cardiac_read)
    dives["cardiac_efficiency"] = cardiac_dive

    adapt_read, adapt_dive = _adaptation_window(nights)
    reads.append(adapt_read)
    dives["adaptation_window"] = adapt_dive

    runway_read, runway_dive = _runway(nights, hrv_mean_90d)
    reads.append(runway_read)
    dives["runway"] = runway_dive

    phase_read, phase_dive = _circadian_phase(nights)
    reads.append(phase_read)
    dives["circadian_phase"] = phase_dive

    habit_read, habit_dive = _habit_persistence(nights)
    reads.append(habit_read)
    dives["habit_persistence"] = habit_dive

    contrib_read, contrib_dive = _timing_contribution(nights)
    reads.append(contrib_read)
    dives["timing_contribution"] = contrib_dive

    if resolved_user_id is not None:
        db.replace_derived_reads(con, resolved_user_id, reads, dives, now)
        logger.info(
            "Derived reads stored (user_id=%s nights=%d workouts=%d)",
            resolved_user_id,
            len(nights),
            len(workouts),
        )
    return reads


def get_reads_payload(con: duckdb.DuckDBPyConnection, user_id: int | None = None) -> dict[str, Any]:
    """Return the eleven table rows, computing them if the store is empty."""
    rows = db.list_derived_reads(con, user_id)
    if not rows:
        compute_and_store_reads(con, user_id=user_id)
        rows = db.list_derived_reads(con, user_id)
    ordered = _order_reads(rows)
    nights = _count(con, "SELECT COUNT(*) FROM sleep WHERE COALESCE(nap, FALSE) = FALSE")
    return {
        "present": bool(ordered),
        "nights": nights,
        "calibrating": nights < CALIBRATING_NIGHTS,
        "progress": {"nights": nights, "needed": STAGE_WINDOW},
        "reads": [_public_read(row) for row in ordered],
    }


def get_read_dive_payload(
    con: duckdb.DuckDBPyConnection,
    read_id: str,
    user_id: int | None = None,
) -> dict[str, Any]:
    if read_id not in READ_ORDER:
        return {"present": False, "id": read_id, "read": None, "dive": None}
    reads = get_reads_payload(con, user_id)
    read = next((r for r in reads["reads"] if r["id"] == read_id), None)
    stored = db.get_derived_read_dive(con, read_id, user_id)
    payload = stored.get("payload") if stored else {}
    return {
        "present": read is not None,
        "id": read_id,
        "read": read,
        "dive": payload if isinstance(payload, dict) else {},
    }


def get_runway_payload(con: duckdb.DuckDBPyConnection, user_id: int | None = None) -> dict[str, Any]:
    """History + sparkline for the runway table row. Projection card is PR 5."""
    bundle = get_read_dive_payload(con, "runway", user_id)
    dive = bundle.get("dive") or {}
    read = bundle.get("read") or {}
    history = dive.get("history") if isinstance(dive, dict) else None
    return {
        "present": bundle.get("present", False),
        "calibrating": bool(read.get("calibrating")) if read else True,
        "nights": dive.get("nights") if isinstance(dive, dict) else None,
        "finding": read.get("finding") if read else None,
        "value": read.get("value") if read else None,
        "unit": read.get("unit") if read else None,
        "sparkline": read.get("sparkline") if read else [],
        "history": history if isinstance(history, list) else [],
        "hrv_mean_90d": dive.get("hrv_mean_90d") if isinstance(dive, dict) else None,
        "slope_21d": dive.get("slope_21d") if isinstance(dive, dict) else None,
        "methodology": read.get("methodology") if read else None,
    }


def _order_reads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row.get("id"): row for row in rows}
    ordered = [by_id[rid] for rid in READ_ORDER if rid in by_id]
    extras = [row for row in rows if row.get("id") not in READ_ORDER]
    return ordered + extras


def _public_read(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "group": row.get("group"),
        "title": row.get("title"),
        "finding": row.get("finding"),
        "value": _json_num(row.get("value")),
        "unit": row.get("unit"),
        "delta": _json_num(row.get("delta")),
        "sparkline": [_json_num(v) for v in (row.get("sparkline") or []) if _json_num(v) is not None],
        "flagged": bool(row.get("flagged")),
        "calibrating": bool(row.get("calibrating")),
        "favourable": bool(row.get("favourable", True)),
        "progress": row.get("progress"),
        "progress_needed": row.get("progress_needed"),
        "methodology": row.get("methodology"),
        "subtitle": row.get("subtitle"),
        "preview": row.get("preview"),
    }


def _row(
    *,
    id: str,
    group: str,
    title: str,
    finding: str,
    methodology: str,
    subtitle: str,
    value: float | None = None,
    unit: str | None = None,
    delta: float | None = None,
    sparkline: list[float] | None = None,
    flagged: bool = False,
    calibrating: bool = False,
    favourable: bool = True,
    progress: int | None = None,
    progress_needed: int | None = None,
    preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": id,
        "group": group,
        "title": title,
        "finding": finding,
        "value": _json_num(value),
        "unit": unit,
        "delta": _json_num(delta),
        "sparkline": [_json_num(v) for v in (sparkline or []) if _json_num(v) is not None],
        "flagged": flagged,
        "calibrating": calibrating,
        "favourable": favourable,
        "progress": progress,
        "progress_needed": progress_needed,
        "methodology": methodology,
        "subtitle": subtitle,
        "preview": preview,
    }


# ---------------------------------------------------------------------------
# 1. Restorative Yield per Hour Asleep
# ---------------------------------------------------------------------------


def _restorative_yield(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Restorative Yield per Hour Asleep"
    subtitle = "How much REM and deep sleep you get for each hour you spend in bed."
    methodology = (
        "Restorative yield is (REM + slow-wave minutes) ÷ hours in bed, night by night. "
        f"The number is last night versus your own {YIELD_WINDOW}-night mean."
    )
    series = []
    for night in nights:
        in_bed = night.get("in_bed_hours")
        rem = night.get("rem_hours")
        deep = night.get("deep_hours")
        if in_bed is None or in_bed <= 0 or rem is None or deep is None:
            continue
        series.append(
            {
                "date": night["date"],
                "yield_min_h": (rem + deep) * 60.0 / in_bed,
                "in_bed_hours": in_bed,
                "rem_hours": rem,
                "deep_hours": deep,
            }
        )
    n = len(series)
    if n < 3:
        return (
            _row(
                id="restorative_yield",
                group=GROUP_SLEEP,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, YIELD_WINDOW, "restorative yield"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=YIELD_WINDOW,
            ),
            {"series": series, "nights": n, "calibrating": True},
        )

    window = series[-YIELD_WINDOW:]
    mean_y = float(np.mean([p["yield_min_h"] for p in window]))
    latest = series[-1]["yield_min_h"]
    delta = latest - mean_y
    favourable = latest >= mean_y
    if delta >= 0:
        finding = (
            f"last night returned {latest:.0f} restorative min/h, "
            f"{delta:+.0f} vs your {len(window)}-night mean of {mean_y:.0f}"
        )
    else:
        finding = (
            f"last night sat {abs(delta):.0f} min/h below your {len(window)}-night mean "
            f"of {mean_y:.0f} — protect the next bedtime"
        )
    spark = [p["yield_min_h"] for p in series[-SPARKLINE_LEN:]]
    preview = {
        "kind": "line",
        "series": [{"date": p["date"], "value": _json_num(p["yield_min_h"])} for p in window],
        "baseline": _json_num(mean_y),
    }
    read = _row(
        id="restorative_yield",
        group=GROUP_SLEEP,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=latest,
        unit="min/h",
        delta=delta,
        sparkline=spark,
        calibrating=n < CALIBRATING_NIGHTS,
        favourable=favourable,
        progress=n,
        progress_needed=YIELD_WINDOW,
        methodology=methodology,
        preview=preview,
    )
    dive = {
        "series": series[-YIELD_WINDOW:],
        "latest": _json_num(latest),
        "baseline": _json_num(mean_y),
        "nights": n,
        "calibrating": n < CALIBRATING_NIGHTS,
        "meaning": finding[0].upper() + finding[1:] + ".",
    }
    return read, dive


# ---------------------------------------------------------------------------
# 2. Stage Dependency Profile
# ---------------------------------------------------------------------------


def _stage_dependency(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Stage Dependency Profile"
    subtitle = "Which sleep stage carries the strongest association with your own next-day autonomic state."
    methodology = (
        "Association strengths are rolling 60-night partial correlations of stage minutes "
        "against your next-morning HRV. Shares are normalised to 100% of the three-stage total."
    )
    pairs = []
    for night in nights:
        hrv = night.get("hrv")
        rem = night.get("rem_hours")
        deep = night.get("deep_hours")
        light = night.get("light_hours")
        if hrv is None or rem is None or deep is None or light is None:
            continue
        pairs.append(
            {
                "date": night["date"],
                "hrv": hrv,
                "rem_min": rem * 60.0,
                "deep_min": deep * 60.0,
                "light_min": light * 60.0,
            }
        )
    n = len(pairs)
    stacked_14 = [
        {
            "date": p["date"],
            "rem": _json_num(p["rem_min"]),
            "deep": _json_num(p["deep_min"]),
            "light": _json_num(p["light_min"]),
        }
        for p in pairs[-14:]
    ]
    dive_base = {
        "variance": [],
        "stacked_14": stacked_14,
        "nights": n,
        "needed": STAGE_WINDOW,
        "calibrating": n < STAGE_WINDOW,
        "dominant": None,
        "meaning": None,
    }
    if n < STAGE_WINDOW:
        finding = _calibrating_finding(n, STAGE_WINDOW, "stage dependency")
        return (
            _row(
                id="stage_dependency",
                group=GROUP_SLEEP,
                title=title,
                subtitle=subtitle,
                finding=finding,
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=STAGE_WINDOW,
                preview={"kind": "stacked", "series": stacked_14} if stacked_14 else None,
            ),
            dive_base,
        )

    window = pairs[-STAGE_WINDOW:]
    hrv = np.array([p["hrv"] for p in window], float)
    rem = np.array([p["rem_min"] for p in window], float)
    deep = np.array([p["deep_min"] for p in window], float)
    light = np.array([p["light_min"] for p in window], float)
    weights = {
        "REM": abs(_partial_corr(rem, hrv, np.column_stack([deep, light])) or 0.0),
        "Deep": abs(_partial_corr(deep, hrv, np.column_stack([rem, light])) or 0.0),
        "Light": abs(_partial_corr(light, hrv, np.column_stack([rem, deep])) or 0.0),
    }
    total = sum(weights.values())
    if total <= 0:
        finding = "stage minutes are not yet separating your next-morning HRV — keep logging nights"
        dive_base["meaning"] = finding[0].upper() + finding[1:] + "."
        return (
            _row(
                id="stage_dependency",
                group=GROUP_SLEEP,
                title=title,
                subtitle=subtitle,
                finding=finding,
                methodology=methodology,
                calibrating=False,
                progress=n,
                progress_needed=STAGE_WINDOW,
            ),
            dive_base,
        )

    variance = [
        {"stage": name, "pct": _json_num(100.0 * w / total), "weight": _json_num(w)}
        for name, w in weights.items()
    ]
    variance.sort(key=lambda item: item["pct"] or 0, reverse=True)
    dominant = variance[0]["stage"]
    pct = variance[0]["pct"] or 0
    finding = f"your recovery tracks {dominant} · {pct:.0f}% of the stage–HRV link on your last {STAGE_WINDOW} nights"
    meaning = (
        f"Population guidance calls deep sleep physical and REM cognitive. Your recovery tracks "
        f"{dominant} most strongly on your own nights — so the habits that feed {dominant} "
        f"matter more for you than chasing a stage that does not move your HRV."
    )
    spark = [p["rem_min"] for p in pairs[-SPARKLINE_LEN:]]
    preview = {"kind": "donut", "variance": variance, "dominant": dominant, "pct": pct}
    dive = {
        **dive_base,
        "variance": variance,
        "dominant": dominant,
        "calibrating": False,
        "meaning": meaning,
    }
    read = _row(
        id="stage_dependency",
        group=GROUP_SLEEP,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=pct,
        unit="%",
        sparkline=spark,
        flagged=False,
        calibrating=False,
        favourable=True,
        progress=n,
        progress_needed=STAGE_WINDOW,
        methodology=methodology,
        preview=preview,
    )
    return read, dive


# ---------------------------------------------------------------------------
# 3. Hyperarousal Signature
# ---------------------------------------------------------------------------


def _hyperarousal(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Hyperarousal Signature"
    subtitle = "Nights where leftover sleep debt and long time-to-sleep show up together."
    methodology = (
        "A night is flagged when sleep-debt hours and in-bed awake minutes both sit above "
        f"your own {HYPER_PERCENTILE:.0f}th percentile. WHOOP v2 does not expose sleep-onset "
        "latency; awake time in bed is the latency stand-in. Measured against your own nights, "
        "not a population cut."
    )
    points = []
    for night in nights:
        debt = night.get("debt_hours")
        latency = night.get("latency_min")
        if debt is None or latency is None:
            continue
        points.append(
            {
                "date": night["date"],
                "debt_hours": debt,
                "latency_min": latency,
                "disturbances": night.get("disturbances"),
                "efficiency": night.get("efficiency"),
            }
        )
    n = len(points)
    if n < CALIBRATING_NIGHTS:
        return (
            _row(
                id="hyperarousal",
                group=GROUP_SLEEP,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, CALIBRATING_NIGHTS, "hyperarousal"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=CALIBRATING_NIGHTS,
            ),
            {
                "scatter": points,
                "flagged_count": 0,
                "nights": n,
                "calibrating": True,
                "drivers": [],
            },
        )

    debts = np.array([p["debt_hours"] for p in points], float)
    lats = np.array([p["latency_min"] for p in points], float)
    debt_cut = float(np.percentile(debts, HYPER_PERCENTILE))
    lat_cut = float(np.percentile(lats, HYPER_PERCENTILE))
    flagged_n = 0
    for point in points:
        flag = point["debt_hours"] >= debt_cut and point["latency_min"] >= lat_cut
        point["flagged"] = flag
        if flag:
            flagged_n += 1
    last = points[-1]
    last_flagged = bool(last["flagged"])
    spark = [p["debt_hours"] * p["latency_min"] for p in points[-SPARKLINE_LEN:]]
    finding = f"{flagged_n} flagged nights in {n}"
    if last_flagged:
        finding += (
            f" — last night sat in the can't-get-to-sleep quadrant "
            f"(debt {last['debt_hours']:.1f} h and {last['latency_min']:.0f} min awake vs your own upper quartile)"
        )
    else:
        finding += (
            f" · last night was outside that quadrant versus your "
            f"{HYPER_PERCENTILE:.0f}th-percentile debt {debt_cut:.1f} h and latency {lat_cut:.0f} min"
        )

    high_debt = sum(1 for p in points if p["debt_hours"] >= debt_cut)
    long_lat = sum(1 for p in points if p["latency_min"] >= lat_cut)
    drivers = [
        {"name": "High debt nights", "count": high_debt, "pct": _json_num(100.0 * high_debt / n)},
        {"name": "Long latency nights", "count": long_lat, "pct": _json_num(100.0 * long_lat / n)},
        {"name": "Both (flagged)", "count": flagged_n, "pct": _json_num(100.0 * flagged_n / n)},
    ]
    preview = {
        "kind": "scatter",
        "points": [
            {
                "date": p["date"],
                "debt_hours": _json_num(p["debt_hours"]),
                "latency_min": _json_num(p["latency_min"]),
                "flagged": p["flagged"],
            }
            for p in points[-STAGE_WINDOW:]
        ],
        "debt_threshold": _json_num(debt_cut),
        "latency_threshold": _json_num(lat_cut),
    }
    meaning = (
        "The can't-get-to-sleep quadrant is nights where you already owed sleep and still "
        "spent a long time awake in bed — both versus your own upper quartile, not a generic cutoff."
    )
    read = _row(
        id="hyperarousal",
        group=GROUP_SLEEP,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=float(flagged_n),
        unit="nights",
        sparkline=spark,
        flagged=last_flagged,
        calibrating=False,
        favourable=not last_flagged,
        progress=n,
        progress_needed=CALIBRATING_NIGHTS,
        methodology=methodology,
        preview=preview,
    )
    dive = {
        "scatter": preview["points"],
        "debt_threshold": _json_num(debt_cut),
        "latency_threshold": _json_num(lat_cut),
        "flagged_count": flagged_n,
        "nights": n,
        "drivers": drivers,
        "calibrating": False,
        "meaning": meaning,
    }
    return read, dive


# ---------------------------------------------------------------------------
# 4. Timing Regularity vs Duration
# ---------------------------------------------------------------------------


def _timing_regularity(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Timing Regularity vs Duration"
    subtitle = "Whether bedtime regularity or time asleep better tracks your next-morning HRV."
    methodology = (
        f"On your last {STAGE_WINDOW} nights, |sleep-midpoint shift vs your {PHASE_WINDOW}-night "
        "mean| and hours asleep are each correlated with next-morning HRV. The ratio is "
        "|r_timing| ÷ |r_duration|."
    )
    pairs = _timing_duration_pairs(nights)
    n = len(pairs)
    if n < STAGE_WINDOW:
        return (
            _row(
                id="timing_regularity",
                group=GROUP_SLEEP,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, STAGE_WINDOW, "timing vs duration"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=STAGE_WINDOW,
            ),
            {"nights": n, "calibrating": True, "ratio": None},
        )

    window = pairs[-STAGE_WINDOW:]
    hrv = np.array([p["hrv"] for p in window], float)
    shift = np.array([p["shift_min"] for p in window], float)
    dur = np.array([p["asleep_hours"] for p in window], float)
    r_t = _pearson(shift, hrv)
    r_d = _pearson(dur, hrv)
    if r_t is None or r_d is None or abs(r_d) < 1e-9:
        finding = "timing and duration are not yet separating your next-morning HRV on these nights"
        return (
            _row(
                id="timing_regularity",
                group=GROUP_SLEEP,
                title=title,
                subtitle=subtitle,
                finding=finding,
                methodology=methodology,
                progress=n,
                progress_needed=STAGE_WINDOW,
            ),
            {"nights": n, "r_timing": r_t, "r_duration": r_d, "ratio": None, "calibrating": False},
        )

    ratio = abs(r_t) / abs(r_d)
    finding = (
        f"timing explains {ratio:.1f}× more of your next-morning HRV link than duration "
        f"across your last {STAGE_WINDOW} nights"
    )
    spark = [p["shift_min"] for p in pairs[-SPARKLINE_LEN:]]
    read = _row(
        id="timing_regularity",
        group=GROUP_SLEEP,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=ratio,
        unit="×",
        sparkline=spark,
        favourable=True,
        progress=n,
        progress_needed=STAGE_WINDOW,
        methodology=methodology,
        preview={"kind": "bars", "r_timing": _json_num(r_t), "r_duration": _json_num(r_d), "ratio": _json_num(ratio)},
    )
    dive = {
        "nights": n,
        "r_timing": _json_num(r_t),
        "r_duration": _json_num(r_d),
        "ratio": _json_num(ratio),
        "calibrating": False,
        "meaning": finding[0].upper() + finding[1:] + ".",
    }
    return read, dive


# ---------------------------------------------------------------------------
# 5. Strain Sensitivity Slope
# ---------------------------------------------------------------------------


def _strain_sensitivity(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Strain Sensitivity Slope"
    subtitle = "HRV cost per additional strain unit on the day before."
    methodology = (
        f"Rolling {SLOPE_WINDOW}-day ordinary least squares of next-morning HRV on prior-day "
        "strain. The 12-week trend is that same slope, recomputed at each week end on real nights only."
    )
    pairs = []
    for night in nights:
        strain = night.get("prior_strain")
        hrv = night.get("hrv")
        if strain is None or hrv is None:
            continue
        pairs.append({"date": night["date"], "strain": strain, "hrv": hrv})
    n = len(pairs)
    scatter = [{"date": p["date"], "strain": _json_num(p["strain"]), "hrv": _json_num(p["hrv"])} for p in pairs]
    trend = _rolling_slope_weeks(pairs, window=SLOPE_WINDOW)
    if n < SLOPE_WINDOW:
        return (
            _row(
                id="strain_sensitivity",
                group=GROUP_LOAD,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, SLOPE_WINDOW, "strain sensitivity"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=SLOPE_WINDOW,
                preview={"kind": "scatter", "points": scatter, "slope": None, "intercept": None} if scatter else None,
            ),
            {
                "scatter": scatter,
                "slope": None,
                "intercept": None,
                "trend_12w": trend,
                "nights": n,
                "calibrating": True,
            },
        )

    window = pairs[-SLOPE_WINDOW:]
    fit = _ols_fit([p["strain"] for p in window], [p["hrv"] for p in window])
    if fit is None:
        finding = "prior-day strain is not yet moving your next-morning HRV on these nights"
        return (
            _row(
                id="strain_sensitivity",
                group=GROUP_LOAD,
                title=title,
                subtitle=subtitle,
                finding=finding,
                methodology=methodology,
                progress=n,
                progress_needed=SLOPE_WINDOW,
            ),
            {"scatter": scatter, "slope": None, "intercept": None, "trend_12w": trend, "nights": n},
        )

    slope, intercept = fit
    prev_fit = None
    if n >= SLOPE_WINDOW + 7:
        prev_fit = _ols_fit(
            [p["strain"] for p in pairs[-(SLOPE_WINDOW + 7) : -7]],
            [p["hrv"] for p in pairs[-(SLOPE_WINDOW + 7) : -7]],
        )
    steepening = prev_fit is not None and slope < prev_fit[0]
    if slope < 0:
        finding = (
            f"{'steepening' if steepening else 'holding'} · {slope:.1f} ms per strain unit "
            f"on your last {SLOPE_WINDOW} days"
        )
    else:
        finding = (
            f"your next-morning HRV still rises {slope:.1f} ms per strain unit "
            f"on your last {SLOPE_WINDOW} days"
        )
    spark = [p["hrv"] for p in pairs[-SPARKLINE_LEN:]]
    preview = {
        "kind": "scatter",
        "points": [{"strain": _json_num(p["strain"]), "hrv": _json_num(p["hrv"]), "date": p["date"]} for p in window],
        "slope": _json_num(slope),
        "intercept": _json_num(intercept),
    }
    meaning = (
        "Each extra strain unit on the day before is associated with this change in next-morning "
        f"HRV, fitted on your last {SLOPE_WINDOW} scored days — not a population slope."
    )
    read = _row(
        id="strain_sensitivity",
        group=GROUP_LOAD,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=slope,
        unit="ms/u",
        delta=(slope - prev_fit[0]) if prev_fit else None,
        sparkline=spark,
        flagged=steepening and slope < 0,
        favourable=slope >= 0,
        progress=n,
        progress_needed=SLOPE_WINDOW,
        methodology=methodology,
        preview=preview,
    )
    dive = {
        "scatter": preview["points"],
        "slope": _json_num(slope),
        "intercept": _json_num(intercept),
        "trend_12w": trend,
        "nights": n,
        "calibrating": False,
        "meaning": meaning,
    }
    return read, dive


# ---------------------------------------------------------------------------
# 6. Cardiac Efficiency Drift by Sport
# ---------------------------------------------------------------------------


def _cardiac_efficiency(workouts: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Cardiac Efficiency Drift by Sport"
    subtitle = "Heart rate at comparable external work, grouped by sport."
    methodology = (
        "For each sport, sessions within ±8% of that sport's own median kilojoule load are kept. "
        "Drift is recent matched-session average heart rate minus earlier matched-session average, "
        "in bpm, on your own history."
    )
    by_sport: dict[str, list[dict[str, Any]]] = {}
    for session in workouts:
        name = session.get("sport_name") or f"sport {session.get('sport_id')}"
        kj = session.get("kilojoule")
        hr = session.get("average_heart_rate")
        if kj is None or hr is None or kj <= 0:
            by_sport.setdefault(name, [])
            continue
        by_sport.setdefault(name, []).append(session)

    sports_out: list[dict[str, Any]] = []
    for name, sessions in sorted(by_sport.items(), key=lambda kv: -len(kv[1])):
        scored = [s for s in sessions if s.get("kilojoule") and s.get("average_heart_rate")]
        enabled = False
        delta = None
        matched: list[dict[str, Any]] = []
        median_kj = None
        if scored:
            kjs = [float(s["kilojoule"]) for s in scored]
            median_kj = float(np.median(kjs))
            lo, hi = median_kj * (1 - KJ_TOLERANCE), median_kj * (1 + KJ_TOLERANCE)
            matched = [s for s in scored if lo <= float(s["kilojoule"]) <= hi]
            matched = sorted(matched, key=lambda s: s["start"] or "")
            enabled = len(matched) >= CARDIAC_MIN_MATCHED
            if enabled:
                half = max(CARDIAC_MIN_MATCHED // 2, 2)
                early = [float(s["average_heart_rate"]) for s in matched[:half]]
                late = [float(s["average_heart_rate"]) for s in matched[-half:]]
                delta = float(np.mean(late) - np.mean(early))
        sports_out.append(
            {
                "sport_id": matched[0].get("sport_id") if matched else (scored[0].get("sport_id") if scored else None),
                "sport_name": name,
                "enabled": enabled,
                "sessions": len(scored),
                "matched": len(matched),
                "median_kj": _json_num(median_kj),
                "delta_bpm": _json_num(delta),
                "series": [
                    {
                        "date": (s["start"] or "")[:10],
                        "hr": _json_num(s["average_heart_rate"]),
                        "kilojoule": _json_num(s["kilojoule"]),
                    }
                    for s in matched
                ],
            }
        )

    enabled_sports = [s for s in sports_out if s["enabled"] and s["delta_bpm"] is not None]
    n_sessions = sum(s["sessions"] for s in sports_out)
    if not enabled_sports:
        finding = (
            _calibrating_finding(n_sessions, CARDIAC_MIN_MATCHED, "cardiac efficiency")
            if n_sessions < CARDIAC_MIN_MATCHED
            else "no sport yet has enough sessions inside ±8% of its own median kilojoule load"
        )
        return (
            _row(
                id="cardiac_efficiency",
                group=GROUP_LOAD,
                title=title,
                subtitle=subtitle,
                finding=finding,
                methodology=methodology,
                calibrating=True,
                progress=n_sessions,
                progress_needed=CARDIAC_MIN_MATCHED,
            ),
            {"sports": sports_out, "calibrating": True, "meaning": finding[0].upper() + finding[1:] + "."},
        )

    focus = min(enabled_sports, key=lambda s: s["delta_bpm"])
    delta = focus["delta_bpm"]
    sport = focus["sport_name"]
    if delta < 0:
        finding = f"{sport} {delta:.0f} bpm at the same work versus your earlier matched sessions"
        meaning = (
            f"At a matched kilojoule load, your {sport} heart rate has drifted {delta:.0f} bpm — "
            "you are doing the same work cheaper than your own earlier sessions."
        )
    else:
        finding = f"{sport} +{delta:.0f} bpm at the same work versus your earlier matched sessions"
        meaning = (
            f"At a matched kilojoule load, your {sport} heart rate has drifted +{delta:.0f} bpm "
            "versus your own earlier sessions — same work is costing more."
        )
    spark = [p["hr"] for p in focus["series"] if p.get("hr") is not None]
    preview = {
        "kind": "line",
        "sport": sport,
        "delta_bpm": delta,
        "series": focus["series"],
        "sports": [
            {
                "sport_name": item["sport_name"],
                "delta_bpm": item["delta_bpm"],
                "enabled": item["enabled"],
            }
            for item in sports_out
        ],
    }
    read = _row(
        id="cardiac_efficiency",
        group=GROUP_LOAD,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=delta,
        unit="bpm",
        sparkline=spark[-SPARKLINE_LEN:],
        favourable=delta <= 0,
        flagged=delta > 0,
        progress=focus["matched"],
        progress_needed=CARDIAC_MIN_MATCHED,
        methodology=methodology,
        preview=preview,
    )
    dive = {"sports": sports_out, "focus": sport, "calibrating": False, "meaning": meaning}
    return read, dive


# ---------------------------------------------------------------------------
# 7. Adaptation Window Index
# ---------------------------------------------------------------------------


def _adaptation_window(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Adaptation Window Index"
    subtitle = "How many of the last seven mornings still sat inside your own recovery band after load."
    methodology = (
        "Each of the last 7 mornings is open when recovery is at or above your own 21-night median. "
        "The index is the count of open mornings (0–7)."
    )
    recovered = [n for n in nights if n.get("recovery") is not None]
    n = len(recovered)
    if n < CALIBRATING_NIGHTS:
        return (
            _row(
                id="adaptation_window",
                group=GROUP_LOAD,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, CALIBRATING_NIGHTS, "adaptation window"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=CALIBRATING_NIGHTS,
            ),
            {"days": [], "open": None, "status": None, "nights": n, "calibrating": True},
        )

    median_rec = float(np.median([n["recovery"] for n in recovered[-21:]]))
    last7 = recovered[-7:]
    days = []
    open_n = 0
    for night in last7:
        is_open = night["recovery"] >= median_rec
        if is_open:
            open_n += 1
        days.append(
            {
                "date": night["date"],
                "recovery": _json_num(night["recovery"]),
                "strain": _json_num(night.get("strain")),
                "open": is_open,
            }
        )
    if open_n >= 6:
        status = "Open"
    elif open_n >= 4:
        status = "Soft"
    elif open_n >= 2:
        status = "Closing"
    else:
        status = "Closed"
    finding = (
        f"{status.lower()} · {open_n} of the last 7 mornings sat at or above your "
        f"21-night recovery median of {median_rec:.0f}"
    )
    meaning = {
        "Open": "You still have room to absorb a hard day without leaving your own recovery band.",
        "Soft": "The window is thinning — one more heavy day will start to sit you outside your own band.",
        "Closing": "You can be ready to train hard today and still sit inside a block that will not absorb the load.",
        "Closed": "The last week has already spent the window. Two easier days buy it back.",
    }[status]
    spark = [n["recovery"] for n in recovered[-SPARKLINE_LEN:]]
    read = _row(
        id="adaptation_window",
        group=GROUP_LOAD,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=float(open_n),
        unit="of 7",
        sparkline=spark,
        flagged=status in {"Closing", "Closed"},
        favourable=status in {"Open", "Soft"},
        progress=n,
        progress_needed=CALIBRATING_NIGHTS,
        methodology=methodology,
        preview={"kind": "pills", "days": days, "status": status, "open": open_n},
    )
    dive = {
        "days": days,
        "open": open_n,
        "status": status,
        "median_recovery": _json_num(median_rec),
        "nights": n,
        "calibrating": False,
        "meaning": meaning,
    }
    return read, dive


# ---------------------------------------------------------------------------
# 8. Recovery Sustainability Runway (table row + reusable GET data)
# ---------------------------------------------------------------------------


def _runway(
    nights: list[dict[str, Any]], hrv_mean_90d: float | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Recovery Sustainability Runway"
    subtitle = "Where your recent HRV trend sits versus your own 90-day mean."
    methodology = (
        f"Sparkline is your last {RUNWAY_WINDOW} morning HRV readings. The slope is ordinary least "
        "squares on those mornings, measured against your stored 90-day HRV mean. "
        "The forward projection card lives elsewhere."
    )
    series = [
        {
            "date": n["date"],
            "hrv": n.get("hrv"),
            "recovery": n.get("recovery"),
            "strain": n.get("strain"),
        }
        for n in nights
        if n.get("hrv") is not None
    ]
    n = len(series)
    history = [
        {
            "date": p["date"],
            "hrv": _json_num(p["hrv"]),
            "recovery": _json_num(p["recovery"]),
            "strain": _json_num(p["strain"]),
        }
        for p in series[-90:]
    ]
    if n < CALIBRATING_NIGHTS:
        return (
            _row(
                id="runway",
                group=GROUP_LOAD,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, CALIBRATING_NIGHTS, "runway"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=CALIBRATING_NIGHTS,
            ),
            {
                "history": history,
                "nights": n,
                "hrv_mean_90d": _json_num(hrv_mean_90d),
                "slope_21d": None,
                "calibrating": True,
            },
        )

    window = series[-RUNWAY_WINDOW:]
    xs = list(range(len(window)))
    ys = [float(p["hrv"]) for p in window]
    fit = _ols_fit(xs, ys)
    slope = fit[0] if fit else None
    latest = ys[-1]
    spark = ys[-SPARKLINE_LEN:]
    if slope is None:
        finding = f"last morning HRV was {latest:.0f} ms versus your stored 90-day mean"
        if hrv_mean_90d is not None:
            finding += f" of {hrv_mean_90d:.0f} ms"
    else:
        weekly = slope * 7
        vs = ""
        if hrv_mean_90d is not None:
            vs = f" versus your 90-day mean of {hrv_mean_90d:.0f} ms"
        if weekly < 0:
            finding = f"your {len(window)}-day HRV trend is slipping {weekly:.1f} ms/week{vs}"
        else:
            finding = f"your {len(window)}-day HRV trend is rising {weekly:.1f} ms/week{vs}"
    favourable = True
    if hrv_mean_90d is not None:
        favourable = latest >= hrv_mean_90d * 0.97 and (slope is None or slope >= 0)
    elif slope is not None:
        favourable = slope >= 0
    read = _row(
        id="runway",
        group=GROUP_LOAD,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=slope * 7 if slope is not None else latest,
        unit="ms/week" if slope is not None else "ms",
        sparkline=spark,
        favourable=favourable,
        flagged=not favourable,
        progress=n,
        progress_needed=CALIBRATING_NIGHTS,
        methodology=methodology,
        preview={"kind": "line", "series": [{"date": p["date"], "value": _json_num(p["hrv"])} for p in window]},
    )
    dive = {
        "history": history,
        "nights": n,
        "hrv_mean_90d": _json_num(hrv_mean_90d),
        "slope_21d": _json_num(slope),
        "calibrating": False,
        "meaning": finding[0].upper() + finding[1:] + ".",
    }
    return read, dive


# ---------------------------------------------------------------------------
# 9. Circadian Phase Drift & Its Toll
# ---------------------------------------------------------------------------


def _circadian_phase(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Circadian Phase Drift & Its Toll"
    subtitle = "How far last night's midpoint sat from your own 21-night midpoint, and the HRV cost of that shift."
    methodology = (
        f"Sleep midpoint is the local clock time halfway between sleep start and end. "
        f"Drift is that midpoint minus your rolling {PHASE_WINDOW}-night mean. "
        "Penalty is the HRV change associated with shift size on your own nights, binned."
    )
    with_mid = [n for n in nights if n.get("midpoint_hours") is not None and n.get("hrv") is not None]
    n = len(with_mid)
    if n < PHASE_WINDOW:
        return (
            _row(
                id="circadian_phase",
                group=GROUP_RHYTHM,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, PHASE_WINDOW, "phase drift"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=PHASE_WINDOW,
            ),
            {"calendar": [], "penalty_bars": [], "nights": n, "calibrating": True},
        )

    shifts: list[dict[str, Any]] = []
    for i, night in enumerate(with_mid):
        window = with_mid[max(0, i - PHASE_WINDOW) : i]
        if len(window) < max(7, PHASE_WINDOW // 3):
            continue
        mean_mid = float(np.mean([w["midpoint_hours"] for w in window]))
        shift_min = (night["midpoint_hours"] - mean_mid) * 60.0
        shifts.append(
            {
                "date": night["date"],
                "midpoint_hours": night["midpoint_hours"],
                "mean_mid": mean_mid,
                "shift_min": shift_min,
                "hrv": night["hrv"],
                "weekday": night.get("weekday"),
            }
        )
    if len(shifts) < PHASE_WINDOW:
        return (
            _row(
                id="circadian_phase",
                group=GROUP_RHYTHM,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(len(shifts), PHASE_WINDOW, "phase drift"),
                methodology=methodology,
                calibrating=True,
                progress=len(shifts),
                progress_needed=PHASE_WINDOW,
            ),
            {"calendar": [], "penalty_bars": [], "nights": n, "calibrating": True},
        )

    latest = shifts[-1]
    mean_hrv = float(np.mean([s["hrv"] for s in shifts[-PHASE_WINDOW:]]))
    penalty_latest = latest["hrv"] - mean_hrv
    bars = _penalty_by_shift(shifts)
    calendar = _phase_calendar(shifts[-CALENDAR_DAYS:])
    abs_shift = abs(latest["shift_min"])
    finding = (
        f"last night's midpoint sat {latest['shift_min']:+.0f} min from your "
        f"{PHASE_WINDOW}-night mean, with morning HRV {penalty_latest:+.0f} ms versus that window"
    )
    spark = [s["shift_min"] for s in shifts[-SPARKLINE_LEN:]]
    preview = {
        "kind": "heat",
        "calendar": calendar,
        "penalty_bars": bars,
        "shift_min": _json_num(latest["shift_min"]),
    }
    meaning = (
        "Shifts are versus your own rolling midpoint, not a clock-time ideal. "
        "The bars show how morning HRV has moved with shift size on your nights."
    )
    read = _row(
        id="circadian_phase",
        group=GROUP_RHYTHM,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=latest["shift_min"],
        unit="min",
        delta=penalty_latest,
        sparkline=spark,
        flagged=abs_shift >= 60,
        favourable=abs_shift < 30,
        progress=len(shifts),
        progress_needed=PHASE_WINDOW,
        methodology=methodology,
        preview=preview,
    )
    dive = {
        "calendar": calendar,
        "penalty_bars": bars,
        "latest_shift_min": _json_num(latest["shift_min"]),
        "latest_penalty_ms": _json_num(penalty_latest),
        "midpoint_mean_21d": _json_num(latest["mean_mid"]),
        "nights": n,
        "calibrating": False,
        "meaning": meaning,
    }
    return read, dive


# ---------------------------------------------------------------------------
# 10. Habit Effect Persistence
# ---------------------------------------------------------------------------


def _habit_persistence(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Habit Effect Persistence"
    subtitle = "How many mornings a consistent night still shows up in your HRV."
    methodology = (
        "Sleep-consistency percentage is lagged 0–7 days against next-morning HRV on your own nights. "
        "Persistence is the last lag that keeps at least half of the lag-0 |correlation| and the same sign."
    )
    pairs = [
        {"date": n["date"], "consistency": n.get("consistency"), "hrv": n.get("hrv")}
        for n in nights
        if n.get("consistency") is not None and n.get("hrv") is not None
    ]
    n = len(pairs)
    if n < STAGE_WINDOW:
        return (
            _row(
                id="habit_persistence",
                group=GROUP_RHYTHM,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, STAGE_WINDOW, "habit persistence"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=STAGE_WINDOW,
            ),
            {"lags": [], "persistence_days": None, "nights": n, "calibrating": True},
        )

    cons = np.array([p["consistency"] for p in pairs], float)
    hrv = np.array([p["hrv"] for p in pairs], float)
    lags = []
    r0 = None
    persist = 0
    for lag in range(0, HABIT_MAX_LAG + 1):
        if lag == 0:
            r = _pearson(cons, hrv)
        else:
            r = _pearson(cons[:-lag], hrv[lag:])
        lags.append({"lag": lag, "r": _json_num(r)})
        if r is None:
            continue
        if lag == 0:
            r0 = r
            persist = 0
            continue
        if r0 is not None and abs(r0) > 1e-9 and (r * r0) > 0 and abs(r) >= 0.5 * abs(r0):
            persist = lag
    finding = (
        f"a consistent night still shows in your HRV for {persist} day"
        f"{'' if persist == 1 else 's'} on your last {n} mornings"
    )
    spark = [p["consistency"] for p in pairs[-SPARKLINE_LEN:]]
    read = _row(
        id="habit_persistence",
        group=GROUP_RHYTHM,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=float(persist),
        unit="days",
        sparkline=spark,
        favourable=persist >= 2,
        progress=n,
        progress_needed=STAGE_WINDOW,
        methodology=methodology,
        preview={"kind": "bars", "lags": lags, "persistence_days": persist},
    )
    dive = {
        "lags": lags,
        "persistence_days": persist,
        "r0": _json_num(r0),
        "nights": n,
        "calibrating": False,
        "meaning": finding[0].upper() + finding[1:] + ".",
    }
    return read, dive


# ---------------------------------------------------------------------------
# 11. Timing vs Duration Contribution
# ---------------------------------------------------------------------------


def _timing_contribution(nights: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    title = "Timing vs Duration Contribution"
    subtitle = "How much of the sleep–HRV link on your nights is timing versus time asleep."
    methodology = (
        f"Multiple regression of next-morning HRV on hours asleep and |midpoint shift| over "
        f"your last {STAGE_WINDOW} nights. Each share is unique R², normalised to the two-predictor total."
    )
    pairs = _timing_duration_pairs(nights)
    n = len(pairs)
    if n < STAGE_WINDOW:
        return (
            _row(
                id="timing_contribution",
                group=GROUP_RHYTHM,
                title=title,
                subtitle=subtitle,
                finding=_calibrating_finding(n, STAGE_WINDOW, "timing contribution"),
                methodology=methodology,
                calibrating=True,
                progress=n,
                progress_needed=STAGE_WINDOW,
            ),
            {"nights": n, "calibrating": True, "timing_pct": None, "duration_pct": None},
        )

    window = pairs[-STAGE_WINDOW:]
    y = np.array([p["hrv"] for p in window], float)
    timing = np.array([p["shift_min"] for p in window], float)
    duration = np.array([p["asleep_hours"] for p in window], float)
    u_t = _unique_r2(y, timing, duration)
    u_d = _unique_r2(y, duration, timing)
    u_t = max(0.0, u_t or 0.0)
    u_d = max(0.0, u_d or 0.0)
    total = u_t + u_d
    if total <= 1e-9:
        finding = "timing and duration are not yet sharing a measurable unique slice of your HRV on these nights"
        return (
            _row(
                id="timing_contribution",
                group=GROUP_RHYTHM,
                title=title,
                subtitle=subtitle,
                finding=finding,
                methodology=methodology,
                progress=n,
                progress_needed=STAGE_WINDOW,
            ),
            {"nights": n, "timing_pct": None, "duration_pct": None, "calibrating": False},
        )

    t_pct = 100.0 * u_t / total
    d_pct = 100.0 * u_d / total
    finding = (
        f"timing carries {t_pct:.0f}% of the sleep–HRV link on your last {STAGE_WINDOW} nights, "
        f"duration {d_pct:.0f}%"
    )
    spark = [p["shift_min"] for p in pairs[-SPARKLINE_LEN:]]
    read = _row(
        id="timing_contribution",
        group=GROUP_RHYTHM,
        title=title,
        subtitle=subtitle,
        finding=finding,
        value=t_pct,
        unit="%",
        sparkline=spark,
        favourable=True,
        progress=n,
        progress_needed=STAGE_WINDOW,
        methodology=methodology,
        preview={"kind": "split", "timing_pct": _json_num(t_pct), "duration_pct": _json_num(d_pct)},
    )
    dive = {
        "nights": n,
        "timing_pct": _json_num(t_pct),
        "duration_pct": _json_num(d_pct),
        "unique_r2_timing": _json_num(u_t),
        "unique_r2_duration": _json_num(u_d),
        "calibrating": False,
        "meaning": finding[0].upper() + finding[1:] + ".",
    }
    return read, dive


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _load_nights(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT
            s.id,
            s.cycle_id,
            s."start",
            s."end",
            s.timezone_offset,
            s.nap,
            s.sleep_performance_percentage,
            s.sleep_consistency_percentage,
            s.sleep_efficiency_percentage,
            s.stage_summary,
            s.sleep_needed,
            r.hrv_rmssd_milli,
            r.recovery_score,
            r.resting_heart_rate,
            c.strain,
            c."start" AS cycle_start
        FROM sleep s
        LEFT JOIN recovery r ON r.cycle_id = s.cycle_id
        LEFT JOIN cycles c ON c.id = s.cycle_id
        WHERE COALESCE(s.nap, FALSE) = FALSE
        ORDER BY s."end"
        """
    ).fetchall()
    nights: list[dict[str, Any]] = []
    prev_strain: float | None = None
    for row in rows:
        start = _as_datetime(row[2])
        end = _as_datetime(row[3])
        stage = _parse_json(row[9]) or {}
        needed = _parse_json(row[10]) or {}
        in_bed = _hours(stage.get("total_in_bed_time_milli"))
        rem = _hours(stage.get("total_rem_sleep_time_milli"))
        deep = _hours(stage.get("total_slow_wave_sleep_time_milli"))
        light = _hours(stage.get("total_light_sleep_time_milli"))
        awake = _hours(stage.get("total_awake_time_milli"))
        latency = _mins(_latency_milli(stage, needed, row))
        debt = _hours(needed.get("need_from_sleep_debt_milli"))
        midpoint = _sleep_midpoint_hours(start, end, row[4])
        date = None
        if end is not None:
            date = end.date().isoformat()
        elif start is not None:
            date = start.date().isoformat()
        strain = _as_float(row[14])
        night = {
            "id": row[0],
            "cycle_id": row[1],
            "date": date,
            "start": start,
            "end": end,
            "in_bed_hours": in_bed,
            "rem_hours": rem,
            "deep_hours": deep,
            "light_hours": light,
            "awake_hours": awake,
            "asleep_hours": _sum_optional(rem, deep, light),
            "latency_min": latency,
            "debt_hours": debt,
            "disturbances": _as_float(stage.get("disturbance_count")),
            "efficiency": _as_float(row[8]),
            "consistency": _as_float(row[7]),
            "performance": _as_float(row[6]),
            "hrv": _as_float(row[11]),
            "recovery": _as_float(row[12]),
            "rhr": _as_float(row[13]),
            "strain": strain,
            "prior_strain": prev_strain,
            "midpoint_hours": midpoint,
            "weekday": end.strftime("%A") if end is not None else None,
        }
        if strain is not None:
            prev_strain = strain
        if date:
            nights.append(night)
    return nights


def _load_workouts(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT id, sport_id, sport_name, "start", kilojoule, average_heart_rate, strain
        FROM workouts
        ORDER BY "start"
        """
    ).fetchall()
    out = []
    for row in rows:
        start = _as_datetime(row[3])
        out.append(
            {
                "id": row[0],
                "sport_id": row[1],
                "sport_name": row[2],
                "start": start.isoformat() if start is not None else None,
                "kilojoule": _as_float(row[4]),
                "average_heart_rate": _as_float(row[5]),
                "strain": _as_float(row[6]),
            }
        )
    return out


def _latency_milli(stage: dict[str, Any], needed: dict[str, Any], row: tuple[Any, ...]) -> float | None:
    for blob in (stage, needed):
        for key in ("sleep_latency_milli", "latency_milli", "sleep_onset_latency_milli"):
            if blob.get(key) is not None:
                return _as_float(blob.get(key))
    return _as_float(stage.get("total_awake_time_milli"))


# ---------------------------------------------------------------------------
# Stats helpers
# ---------------------------------------------------------------------------


def _pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if len(x) < 3 or len(y) < 3 or len(x) != len(y):
        return None
    xd = x - np.mean(x)
    yd = y - np.mean(y)
    denom = float(np.sqrt(np.sum(xd**2) * np.sum(yd**2)))
    if denom == 0 or math.isnan(denom):
        return None
    return float(np.sum(xd * yd) / denom)


def _ols_fit(x: list[float] | np.ndarray, y: list[float] | np.ndarray) -> tuple[float, float] | None:
    xa = np.asarray(x, float)
    ya = np.asarray(y, float)
    if len(xa) < 3:
        return None
    xm = float(np.mean(xa))
    ym = float(np.mean(ya))
    varx = float(np.sum((xa - xm) ** 2))
    if varx == 0:
        return None
    slope = float(np.sum((xa - xm) * (ya - ym)) / varx)
    intercept = ym - slope * xm
    return slope, intercept


def _residuals(y: np.ndarray, controls: np.ndarray) -> np.ndarray | None:
    n = len(y)
    if n < 3:
        return None
    a = np.column_stack([np.ones(n), controls])
    try:
        coef, _, _, _ = np.linalg.lstsq(a, y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    return y - a @ coef


def _partial_corr(x: np.ndarray, y: np.ndarray, controls: np.ndarray) -> float | None:
    rx = _residuals(x, controls)
    ry = _residuals(y, controls)
    if rx is None or ry is None:
        return None
    return _pearson(rx, ry)


def _r2(y: np.ndarray, yhat: np.ndarray) -> float | None:
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    if ss_tot == 0:
        return None
    return 1.0 - ss_res / ss_tot


def _unique_r2(y: np.ndarray, focus: np.ndarray, other: np.ndarray) -> float | None:
    n = len(y)
    if n < 4:
        return None
    a_full = np.column_stack([np.ones(n), focus, other])
    a_other = np.column_stack([np.ones(n), other])
    try:
        full_hat = a_full @ np.linalg.lstsq(a_full, y, rcond=None)[0]
        other_hat = a_other @ np.linalg.lstsq(a_other, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None
    r_full = _r2(y, full_hat)
    r_other = _r2(y, other_hat)
    if r_full is None or r_other is None:
        return None
    return r_full - r_other


def _rolling_slope_weeks(pairs: list[dict[str, Any]], window: int) -> list[dict[str, Any]]:
    if len(pairs) < window:
        return []
    out = []
    # One point per 7 nights, last 12 windows, real data only.
    starts = list(range(window, len(pairs) + 1, 7))
    starts = starts[-12:]
    for end in starts:
        chunk = pairs[end - window : end]
        fit = _ols_fit([p["strain"] for p in chunk], [p["hrv"] for p in chunk])
        if fit is None:
            continue
        out.append({"date": chunk[-1]["date"], "slope": _json_num(fit[0])})
    return out


def _timing_duration_pairs(nights: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with_mid = [n for n in nights if n.get("midpoint_hours") is not None]
    pairs = []
    for i, night in enumerate(with_mid):
        if night.get("hrv") is None or night.get("asleep_hours") is None:
            continue
        window = with_mid[max(0, i - PHASE_WINDOW) : i]
        if len(window) < 7:
            continue
        mean_mid = float(np.mean([w["midpoint_hours"] for w in window]))
        pairs.append(
            {
                "date": night["date"],
                "hrv": night["hrv"],
                "asleep_hours": night["asleep_hours"],
                "shift_min": abs(night["midpoint_hours"] - mean_mid) * 60.0,
            }
        )
    return pairs


def _penalty_by_shift(shifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = [-180, -90, -45, -15, 15, 45, 90, 180]
    labels = ["≤ −90", "−90 to −45", "−45 to −15", "−15 to +15", "+15 to +45", "+45 to +90", "≥ +90"]
    buckets: list[list[float]] = [[] for _ in labels]
    mean_hrv = float(np.mean([s["hrv"] for s in shifts]))
    for item in shifts:
        shift = item["shift_min"]
        idx = None
        for i in range(len(labels)):
            if edges[i] <= shift < edges[i + 1] or (i == len(labels) - 1 and shift >= edges[i]):
                idx = i
                break
        if idx is None:
            continue
        buckets[idx].append(item["hrv"] - mean_hrv)
    out = []
    for label, vals in zip(labels, buckets):
        out.append(
            {
                "bucket": label,
                "penalty_ms": _json_num(float(np.mean(vals))) if vals else None,
                "n": len(vals),
            }
        )
    return out


def _phase_calendar(shifts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for item in shifts[-CALENDAR_DAYS:]:
        day = None
        try:
            day = datetime.fromisoformat(item["date"]).date()
        except (TypeError, ValueError):
            pass
        out.append(
            {
                "date": item["date"],
                "shift_min": _json_num(item["shift_min"]),
                "hrv": _json_num(item["hrv"]),
                "weekday": item.get("weekday") or (day.strftime("%A") if day else None),
                "iso_week": day.isocalendar()[1] if day else None,
            }
        )
    return out


def _calibrating_finding(have: int, needed: int, label: str) -> str:
    return f"{have} of {needed} nights — still calibrating {label} against your own history"


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _profile_user_id(con: duckdb.DuckDBPyConnection) -> int | None:
    row = con.execute("SELECT user_id FROM profile LIMIT 1").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _parse_json(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _hours(value: Any) -> float | None:
    num = _as_float(value)
    if num is None:
        return None
    return num / MS_PER_HOUR


def _mins(value: Any) -> float | None:
    num = _as_float(value)
    if num is None:
        return None
    return num / MS_PER_MIN


def _sum_optional(*values: float | None) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return float(sum(present))


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _json_num(value: Any) -> float | None:
    num = _as_float(value)
    if num is None:
        return None
    return round(num, 4)


def _sleep_midpoint_hours(start: datetime | None, end: datetime | None, timezone_offset: Any) -> float | None:
    if start is None or end is None:
        return None
    mid = start + (end - start) / 2
    local = mid + _parse_offset(timezone_offset)
    return local.hour + local.minute / 60.0 + local.second / 3600.0


def _parse_offset(offset: Any) -> timedelta:
    if not offset or not isinstance(offset, str):
        return timedelta(0)
    text = offset.strip()
    if not text or text in ("Z", "UTC"):
        return timedelta(0)
    sign = -1 if text.startswith("-") else 1
    rest = text[1:] if text[0] in "+-" else text
    parts = rest.split(":")
    try:
        hours = int(parts[0])
        minutes = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return timedelta(0)
    return sign * timedelta(hours=hours, minutes=minutes)


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        raw = f"{text[:-1]}+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _naive_utc(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        return now.astimezone(timezone.utc).replace(tzinfo=None)
    return now
