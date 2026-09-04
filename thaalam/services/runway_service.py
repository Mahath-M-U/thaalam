"""Recovery sustainability runway: fitted slope, 80% cone, baseline break.

The client never recomputes a baseline, slope, or projection — it reads
this payload. Short history returns a calibrating state with empty
series; we never invent points.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

import duckdb

from thaalam import db

logger = logging.getLogger(__name__)

CALIBRATING_NIGHTS = 14
HISTORY_DAYS = 21
FIT_DAYS = 7
BASELINE_DAYS = 90
CHRONIC_STRAIN_DAYS = 28
MIDPOINT_NIGHTS = 21
PROJECT_DAYS = 14
MIN_FIT_POINTS = 7
CONE_PCT = 80
# Two-sided 80% (Φ^{-1}(0.90)); residual variance of the fitted slope.
Z_80 = 1.2815515655446004
_MS_PER_HOUR = 3_600_000.0

_SPEND_STRAIN = "Strain above absorbable"
_SPEND_SLEEP = "Short sleep opportunity"
_SPEND_PHASE = "Phase drift"


def compute_runway(
    con: duckdb.DuckDBPyConnection,
    *,
    now: datetime | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Project recovery holding the current 7-day load and sleep pattern constant."""
    now = _naive_utc(now)
    until = now.date()
    nights = _nights_as_of(con, until)
    series = _recovery_series(con, until=until)
    if nights < CALIBRATING_NIGHTS or len(series) < MIN_FIT_POINTS:
        return _calibrating_payload(computed_on=until)

    last_date = series[-1]["date"]
    # Last 7 *observed* recoveries (calendar gaps are not short history).
    fit = series[-FIT_DAYS:]
    history = [p for p in series if p["date"] >= last_date - timedelta(days=HISTORY_DAYS - 1)]
    if len(fit) < MIN_FIT_POINTS:
        return _calibrating_payload(computed_on=until)

    baseline_rows = [
        p for p in series if p["date"] >= last_date - timedelta(days=BASELINE_DAYS - 1)
    ]
    if not baseline_rows:
        return _calibrating_payload(computed_on=until)
    baseline = sum(p["value"] for p in baseline_rows) / len(baseline_rows)

    _intercept, slope, sigma, xbar, sxx = _ols(
        [(p["date"] - fit[0]["date"]).days for p in fit],
        [p["value"] for p in fit],
    )
    last = history[-1]
    last_x = (last["date"] - fit[0]["date"]).days
    n_fit = len(fit)

    days_remaining, break_date = _crossing(last["value"], last["date"], slope, baseline)
    horizon = PROJECT_DAYS
    if days_remaining is not None:
        horizon = max(PROJECT_DAYS, min(21, days_remaining + 4))

    projection = _project(
        last_date=last["date"],
        last_value=last["value"],
        last_x=last_x,
        slope=slope,
        sigma=sigma,
        n_fit=n_fit,
        xbar=xbar,
        sxx=sxx,
        horizon=horizon,
    )

    spend = _spend_drivers(con, last["date"], until=until)
    window = _adaptation_window(days_remaining, slope)
    headline, subtitle, what, cta = _copy(days_remaining, spend, window["state"])

    return {
        "present": True,
        "calibrating": False,
        "headline": headline,
        "subtitle": subtitle,
        "history": [{"date": p["date"].isoformat(), "value": _r(p["value"])} for p in history],
        "projection": projection,
        "baseline": _r(baseline),
        "baseline_break_date": break_date.isoformat() if break_date is not None else None,
        "days_remaining": days_remaining,
        "as_of": last["date"].isoformat(),
        "computed_on": until.isoformat(),
        "cone_pct": CONE_PCT,
        "spend": spend,
        "adaptation_window": window,
        "methodology": (
            "Projection holds current 7-day load and sleep pattern constant. "
            f"{CONE_PCT}% cone from residual variance of the fitted slope. "
            "Baseline is your 90-day mean recovery. "
            "Crossing is the projected baseline break."
        ),
        "what_it_means": what,
        "cta": cta,
        "user_id": user_id,
    }


def compute_and_store_runway(
    con: duckdb.DuckDBPyConnection,
    *,
    now: datetime | None = None,
    user_id: int | None = None,
) -> dict[str, Any]:
    payload = compute_runway(con, now=now, user_id=user_id)
    if user_id is not None:
        db.upsert_derived_runway(con, user_id, payload, computed_at=_naive_utc(now))
    return payload


def _calibrating_payload(*, computed_on: date | None = None) -> dict[str, Any]:
    return {
        "present": False,
        "calibrating": True,
        "headline": None,
        "subtitle": "Calibrating — need 14 nights to project a runway",
        "history": [],
        "projection": [],
        "baseline": None,
        "baseline_break_date": None,
        "days_remaining": None,
        "as_of": None,
        "computed_on": computed_on.isoformat() if computed_on is not None else None,
        "cone_pct": CONE_PCT,
        "spend": [],
        "adaptation_window": None,
        "methodology": None,
        "what_it_means": None,
        "cta": None,
    }


def _recovery_series(
    con: duckdb.DuckDBPyConnection, *, until: date
) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT r.recovery_score, r.created_at, c."start" AS cycle_start
        FROM recovery r
        LEFT JOIN cycles c ON c.id = r.cycle_id
        WHERE r.recovery_score IS NOT NULL
        """
    ).fetchall()
    by_date: dict[date, float] = {}
    for score, created_at, cycle_start in rows:
        stamped = _as_datetime(cycle_start) or _as_datetime(created_at)
        if stamped is None or stamped.date() > until:
            continue
        try:
            value = float(score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        by_date[stamped.date()] = value
    return [{"date": d, "value": by_date[d]} for d in sorted(by_date)]


def _ols(xs: list[int], ys: list[float]) -> tuple[float, float, float, float, float]:
    n = len(xs)
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    sxx = sum((x - xbar) ** 2 for x in xs)
    sxy = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    if sxx <= 0:
        sse = sum((y - ybar) ** 2 for y in ys)
        df = max(n - 1, 1)
        return ybar, 0.0, math.sqrt(sse / df), xbar, 0.0
    slope = sxy / sxx
    intercept = ybar - slope * xbar
    sse = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    df = n - 2
    sigma = math.sqrt(sse / df) if df > 0 else 0.0
    return intercept, slope, sigma, xbar, sxx


def _crossing(
    last_value: float,
    last_date: date,
    slope: float,
    baseline: float,
) -> tuple[int | None, date | None]:
    """Days until the projected path hits baseline. None if not heading there."""
    if slope >= 0:
        return None, None
    if last_value <= baseline:
        return 0, last_date
    raw = (last_value - baseline) / (-slope)
    if not math.isfinite(raw) or raw < 0:
        return 0, last_date
    days = int(round(raw))
    if days < 0:
        days = 0
    return days, last_date + timedelta(days=days)


def _project(
    *,
    last_date: date,
    last_value: float,
    last_x: int,
    slope: float,
    sigma: float,
    n_fit: int,
    xbar: float,
    sxx: float,
    horizon: int,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for k in range(0, horizon + 1):
        yhat = last_value + slope * k
        if k == 0:
            lo = hi = yhat
        else:
            x = last_x + k
            extra = 0.0 if sxx <= 0 else (x - xbar) ** 2 / sxx
            se = sigma * math.sqrt(1.0 + 1.0 / max(n_fit, 1) + extra)
            half = Z_80 * se
            lo = yhat - half
            hi = yhat + half
        points.append(
            {
                "date": (last_date + timedelta(days=k)).isoformat(),
                "yhat": _r(yhat),
                "lo": _r(lo),
                "hi": _r(hi),
            }
        )
    return points


def _spend_drivers(
    con: duckdb.DuckDBPyConnection, last_date: date, *, until: date
) -> list[dict[str, Any]]:
    end = min(last_date, until)
    start_7 = end - timedelta(days=FIT_DAYS - 1)
    start_chronic = end - timedelta(days=CHRONIC_STRAIN_DAYS - 1)
    raw: list[tuple[str, float, str]] = []

    strain_7, strain_28 = _mean_strain(con, start_7, end), _mean_strain(
        con, start_chronic, end
    )
    if strain_7 is not None and strain_28 is not None:
        excess = max(0.0, strain_7 - strain_28)
        note = (
            f"7-day strain {strain_7:.1f} vs absorbable {strain_28:.1f}"
            if excess > 0
            else "7-day strain is inside your absorbable load"
        )
        raw.append((_SPEND_STRAIN, excess, note))

    sleep_gap = _sleep_opportunity_gap(con, start_7, end)
    if sleep_gap is not None:
        gap, note = sleep_gap
        raw.append((_SPEND_SLEEP, max(0.0, gap), note))

    phase = _phase_drift_hours(con, end)
    if phase is not None:
        hours, note = phase
        raw.append((_SPEND_PHASE, max(0.0, hours), note))

    if not raw:
        return []

    total = sum(v for _l, v, _n in raw)
    if total <= 0:
        return [
            {"label": label, "pct": 0, "note": note}
            for label, _v, note in raw
        ]

    pcts = _pcts_sum_100([v / total for _l, v, _n in raw])
    return [
        {
            "label": label,
            "pct": pct,
            "note": f"{pct}% of the drain" if pct > 0 else note,
        }
        for (label, _v, note), pct in zip(raw, pcts)
    ]


def _mean_strain(
    con: duckdb.DuckDBPyConnection, start: date, end: date
) -> float | None:
    rows = con.execute(
        """
        SELECT strain, "start"
        FROM cycles
        WHERE strain IS NOT NULL
        """
    ).fetchall()
    values: list[float] = []
    for strain, stamped in rows:
        when = _as_datetime(stamped)
        if when is None:
            continue
        d = when.date()
        if d < start or d > end:
            continue
        try:
            values.append(float(strain))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return sum(values) / len(values)


def _sleep_opportunity_gap(
    con: duckdb.DuckDBPyConnection, start: date, end: date
) -> tuple[float, str] | None:
    rows = con.execute(
        """
        SELECT "start", "end", nap, stage_summary, sleep_needed
        FROM sleep
        WHERE COALESCE(nap, FALSE) = FALSE
          AND "start" IS NOT NULL
          AND "end" IS NOT NULL
        """
    ).fetchall()
    in_beds: list[float] = []
    needs: list[float] = []
    for stamped, ended, _nap, stage_raw, need_raw in rows:
        d = _sleep_date(stamped, ended)
        if d is None or d < start or d > end:
            continue
        in_bed = _in_bed_hours(stamped, ended, stage_raw)
        need = _need_hours(need_raw)
        if in_bed is None:
            continue
        in_beds.append(in_bed)
        if need is not None:
            needs.append(need)
    if not in_beds:
        return None
    actual = sum(in_beds) / len(in_beds)
    if needs:
        target = sum(needs) / len(needs)
        gap = target - actual
        note = (
            f"7-day time in bed {actual:.1f}h vs need {target:.1f}h"
            if gap > 0
            else f"7-day time in bed {actual:.1f}h meets your need"
        )
        return gap, note
    return None


def _phase_drift_hours(
    con: duckdb.DuckDBPyConnection, last_date: date
) -> tuple[float, str] | None:
    rows = con.execute(
        """
        SELECT "start", "end", timezone_offset
        FROM sleep
        WHERE COALESCE(nap, FALSE) = FALSE
          AND "start" IS NOT NULL
          AND "end" IS NOT NULL
        ORDER BY "end" DESC
        """
    ).fetchall()
    mids: list[tuple[date, float]] = []
    for stamped, ended, offset in rows:
        d = _sleep_date(stamped, ended)
        hours = _sleep_midpoint_hours(stamped, ended, offset)
        if d is None or hours is None or d > last_date:
            continue
        mids.append((d, hours))
    if not mids:
        return None
    # Newest-first from SQL; own 21-night midpoint mean.
    recent = mids[:MIDPOINT_NIGHTS]
    mean = sum(h for _d, h in recent) / len(recent)
    start_7 = last_date - timedelta(days=FIT_DAYS - 1)
    window = [h for d, h in mids if start_7 <= d <= last_date]
    if not window:
        return None
    drift = sum(abs(h - mean) for h in window) / len(window)
    note = (
        f"7-day midpoint is {drift * 60:.0f} min off your 21-night mean"
        if drift > 0
        else "Sleep midpoint is aligned with your 21-night mean"
    )
    return drift, note


def _in_bed_hours(start: Any, end: Any, stage_raw: Any) -> float | None:
    stage = _as_obj(stage_raw)
    if isinstance(stage, dict) and stage.get("total_in_bed_time_milli"):
        try:
            return float(stage["total_in_bed_time_milli"]) / _MS_PER_HOUR
        except (TypeError, ValueError):
            pass
    start_dt = _as_datetime(start)
    end_dt = _as_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    return (end_dt - start_dt).total_seconds() / 3600.0


def _need_hours(raw: Any) -> float | None:
    needed = _as_obj(raw)
    if not isinstance(needed, dict):
        return None
    parts = [
        needed.get("baseline_milli"),
        needed.get("need_from_sleep_debt_milli"),
        needed.get("need_from_recent_strain_milli"),
        needed.get("need_from_recent_nap_milli"),
    ]
    total = 0.0
    found = False
    for part in parts:
        if part is None:
            continue
        try:
            total += float(part)
            found = True
        except (TypeError, ValueError):
            continue
    if not found:
        return None
    return total / _MS_PER_HOUR


def _sleep_midpoint_hours(start: Any, end: Any, timezone_offset: Any) -> float | None:
    start_dt = _as_datetime(start)
    end_dt = _as_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    mid = start_dt + (end_dt - start_dt) / 2
    local = mid + _parse_offset(timezone_offset)
    return local.hour + local.minute / 60.0 + local.second / 3600.0


def _adaptation_window(days_remaining: int | None, slope: float) -> dict[str, Any]:
    if days_remaining is None or slope >= 0:
        state, filled = "Open", 7
        copy = "The window is open — this load still sits inside a block you can absorb."
    elif days_remaining >= 10:
        state, filled = "Open", 6
        copy = "The window is open — this load still sits inside a block you can absorb."
    elif days_remaining >= 4:
        state, filled = "Closing", 4
        copy = (
            "You can be ready to train hard today and still sit inside a block "
            "that won't absorb the load."
        )
    elif days_remaining >= 1:
        state, filled = "Closing", 2
        copy = (
            "You can be ready to train hard today and still sit inside a block "
            "that won't absorb the load."
        )
    else:
        state, filled = "Closed", 1
        copy = "The window is closed — ease load before the next block."
    cells = [
        round(max(0.0, 1.0 - i * 0.18), 2) if i < filled else 0.0 for i in range(7)
    ]
    return {"state": state, "cells": cells, "copy": copy}


def _copy(
    days_remaining: int | None,
    spend: list[dict[str, Any]],
    window_state: str,
) -> tuple[str, str, str, str]:
    if days_remaining is None:
        headline = "holding at this load"
        subtitle = "your recovery is holding or building at this load"
        what = (
            "A daily colour tells you about today. At this load your recovery "
            "is holding or building — there is no projected baseline break."
        )
        cta = "Hold this load"
    elif days_remaining == 0:
        headline = "≈ 0 days at this load"
        subtitle = "0 days before your baseline is projected to break"
        what = (
            "A daily colour tells you about today. Your recovery is already at "
            "or below your baseline at this load."
        )
        cta = "Ease the next two days"
    else:
        unit = "day" if days_remaining == 1 else "days"
        headline = f"≈ {days_remaining} {unit} at this load"
        subtitle = (
            f"{days_remaining} {unit} before your baseline is projected to break"
        )
        what = (
            "A daily colour tells you about today. This gives the decision a "
            f"deadline: you have about {days_remaining} {unit} of this before it costs you."
        )
        cta = "Ease the next two days"

    top = max(spend, key=lambda s: s.get("pct") or 0, default=None)
    if top and (top.get("pct") or 0) > 0:
        label = top["label"]
        if label == _SPEND_SLEEP:
            cta = "Protect the next two nights"
        elif label == _SPEND_PHASE:
            cta = "Lock a consistent sleep midpoint"
        elif label == _SPEND_STRAIN:
            cta = "Ease the next two days"
    if window_state == "Open" and days_remaining is None:
        cta = "Hold this load"
    return headline, subtitle, what, cta


def _pcts_sum_100(shares: list[float]) -> list[int]:
    if not shares:
        return []
    raw = [s * 100.0 for s in shares]
    rounded = [int(math.floor(v)) for v in raw]
    remainder = 100 - sum(rounded)
    order = sorted(range(len(raw)), key=lambda i: raw[i] - rounded[i], reverse=True)
    for i in order:
        if remainder <= 0:
            break
        rounded[i] += 1
        remainder -= 1
    return rounded


def _sleep_date(start: Any, end: Any) -> date | None:
    """Wake date (sleep end), matching recovery/cycle days — not the evening start."""
    when = _as_datetime(end) or _as_datetime(start)
    return when.date() if when is not None else None


def _nights_as_of(con: duckdb.DuckDBPyConnection, until: date) -> int:
    rows = con.execute(
        """
        SELECT "start", "end"
        FROM sleep
        WHERE COALESCE(nap, FALSE) = FALSE
        """
    ).fetchall()
    n = 0
    for stamped, ended in rows:
        d = _sleep_date(stamped, ended)
        if d is not None and d <= until:
            n += 1
    return n


def _as_obj(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return None


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


def _r(value: float, digits: int = 2) -> float:
    return round(float(value), digits)
