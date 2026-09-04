"""JSON data endpoints for the React dashboard.

Each route opens a read-only DuckDB connection and returns tidy records
from `thaalam.repositories.queries`. Charts are built on the client from
this raw-ish metric data (no server-side matplotlib images).
"""

from __future__ import annotations

import json
import logging
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException

from thaalam.api.deps import (
    acquire_writable_connection,
    build_whoop_client,
    get_readonly_connection,
    is_whoop_connected,
)
from thaalam.api.serializers import dataframe_to_records, first_record
from thaalam.repositories import queries
from thaalam.services import report_service
from thaalam.services.derived_metrics import recompute
from thaalam.services.insights_service import build_insights
from thaalam.sync import sync_all_historical_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["data"])


@router.get("/profile")
def get_profile(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """WHOOP user profile + body measurement (single-row tables)."""
    profile = first_record(queries.load_profile(con)) or {}
    body = first_record(queries.load_body_measurement(con)) or {}
    return {"profile": profile, "body_measurement": body}


@router.get("/summary")
def get_summary(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Headline dashboard stats (counts + averages)."""
    data = report_service.load_report_data(con)
    stats = report_service.build_summary_stats(data)

    latest: dict[str, Any] = {}
    if not data.daily.empty:
        last = data.daily.dropna(subset=["cycle_start"]).tail(1)
        if not last.empty:
            row = last.iloc[0]
            latest = {
                "cycle_start": str(row["cycle_start"]) if row["cycle_start"] == row["cycle_start"] else None,
                "recovery_score": _num(row.get("recovery_score")),
                "strain": _num(row.get("strain")),
                "hrv_rmssd_milli": _num(row.get("hrv_rmssd_milli")),
                "resting_heart_rate": _num(row.get("resting_heart_rate")),
                "sleep_performance_percentage": _num(row.get("sleep_performance_percentage")),
            }

    return {"stats": stats, "latest": latest}


@router.get("/recovery")
def get_recovery(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Recovery score, HRV, RHR over time."""
    records = dataframe_to_records(queries.load_recovery(con))
    return {"count": len(records), "records": records}


@router.get("/cycles")
def get_cycles(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Physiological cycles (day strain, etc.)."""
    records = dataframe_to_records(queries.load_cycles(con))
    return {"count": len(records), "records": records}


@router.get("/daily")
def get_daily(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Joined daily view: cycle + recovery + main sleep."""
    records = dataframe_to_records(queries.load_daily_summary(con))
    return {"count": len(records), "records": records}


_MS_PER_HOUR = 3_600_000.0
_MS_PER_MIN = 60_000.0


def _hours_from_ms(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(f / _MS_PER_HOUR, 3)


def _mins_from_ms(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(f / _MS_PER_MIN, 1)


def _enrich_sleep_record(rec: dict[str, Any]) -> dict[str, Any]:
    """Attach human-readable stage hours, sleep need/debt, and duration."""
    raw = rec.get("stage_summary")
    if isinstance(raw, str):
        try:
            rec["stage_summary"] = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            rec["stage_summary"] = None
    stage = rec.get("stage_summary") if isinstance(rec.get("stage_summary"), dict) else {}

    needed_raw = rec.get("sleep_needed")
    if isinstance(needed_raw, str):
        try:
            rec["sleep_needed"] = json.loads(needed_raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            rec["sleep_needed"] = None
    needed = rec.get("sleep_needed") if isinstance(rec.get("sleep_needed"), dict) else {}

    light_h = _hours_from_ms(stage.get("total_light_sleep_time_milli"))
    deep_h = _hours_from_ms(stage.get("total_slow_wave_sleep_time_milli"))
    rem_h = _hours_from_ms(stage.get("total_rem_sleep_time_milli"))
    awake_h = _hours_from_ms(stage.get("total_awake_time_milli"))
    in_bed_h = _hours_from_ms(stage.get("total_in_bed_time_milli"))
    no_data_h = _hours_from_ms(stage.get("total_no_data_time_milli"))

    asleep_parts = [x for x in (light_h, deep_h, rem_h) if x is not None]
    asleep_h = round(sum(asleep_parts), 3) if asleep_parts else None

    baseline_h = _hours_from_ms(needed.get("baseline_milli"))
    debt_h = _hours_from_ms(needed.get("need_from_sleep_debt_milli"))
    strain_need_h = _hours_from_ms(needed.get("need_from_recent_strain_milli"))
    nap_credit_h = _hours_from_ms(needed.get("need_from_recent_nap_milli"))
    need_parts = [x for x in (baseline_h, debt_h, strain_need_h, nap_credit_h) if x is not None]
    total_need_h = round(sum(need_parts), 3) if need_parts else None

    gap_h = None
    if in_bed_h is not None and total_need_h is not None:
        gap_h = round(in_bed_h - total_need_h, 3)

    # Duration from start/end if available
    duration_h = None
    start, end = rec.get("start"), rec.get("end")
    if start and end:
        try:
            from datetime import datetime

            s_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            e_dt = datetime.fromisoformat(str(end).replace("Z", "+00:00"))
            duration_h = round((e_dt - s_dt).total_seconds() / 3600.0, 3)
        except (TypeError, ValueError):
            duration_h = in_bed_h

    rec["detail"] = {
        "duration_hours": duration_h if duration_h is not None else in_bed_h,
        "in_bed_hours": in_bed_h,
        "asleep_hours": asleep_h,
        "light_hours": light_h,
        "deep_hours": deep_h,
        "rem_hours": rem_h,
        "awake_hours": awake_h,
        "awake_minutes": _mins_from_ms(stage.get("total_awake_time_milli")),
        "no_data_hours": no_data_h,
        "sleep_cycles": stage.get("sleep_cycle_count"),
        "disturbances": stage.get("disturbance_count"),
        "need_hours": total_need_h,
        "baseline_need_hours": baseline_h,
        "debt_hours": debt_h,
        "strain_need_hours": strain_need_h,
        "nap_credit_hours": nap_credit_h,
        "need_gap_hours": gap_h,
    }
    return rec


@router.get("/sleep")
def get_sleep(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Sleep sessions with stages, need/debt, and computed duration detail."""
    df = queries.load_sleep(con)
    records = [_enrich_sleep_record(rec) for rec in dataframe_to_records(df)]
    return {"count": len(records), "records": records}


@router.get("/workouts")
def get_workouts(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Workouts with zone durations parsed when possible."""
    records = dataframe_to_records(queries.load_workouts(con))
    for rec in records:
        zones = rec.get("zone_durations")
        if isinstance(zones, str):
            try:
                rec["zone_durations"] = json.loads(zones)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
    return {"count": len(records), "records": records}


@router.get("/sleep/stages/average")
def get_avg_sleep_stages(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Average nightly time (hours) in each sleep stage."""
    df = queries.load_sleep(con)
    stage_rows: list[dict[str, Any]] = []
    for raw in df["stage_summary"].dropna():
        try:
            stage_rows.append(json.loads(raw) if isinstance(raw, str) else raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    if not stage_rows:
        return {"stages": []}

    hours_per_ms = 1 / 3_600_000
    fields = [
        ("Light", "total_light_sleep_time_milli"),
        ("Deep (SWS)", "total_slow_wave_sleep_time_milli"),
        ("REM", "total_rem_sleep_time_milli"),
        ("Awake", "total_awake_time_milli"),
    ]
    stages: list[dict[str, Any]] = []
    for label, field in fields:
        values = [row[field] for row in stage_rows if field in row and row[field] is not None]
        if not values:
            continue
        avg_hours = (sum(values) / len(values)) * hours_per_ms
        if avg_hours > 0:
            stages.append({"stage": label, "hours": round(avg_hours, 3)})

    return {"stages": stages, "nights": len(stage_rows)}


@router.get("/workouts/by-sport")
def get_workouts_by_sport(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Average workout strain grouped by sport."""
    df = queries.load_workouts(con)
    scored = df.dropna(subset=["strain", "sport_name"])
    if scored.empty:
        return {"sports": []}

    grouped = (
        scored.groupby("sport_name", as_index=False)
        .agg(avg_strain=("strain", "mean"), count=("strain", "count"))
        .sort_values("avg_strain", ascending=False)
    )
    sports = [
        {
            "sport_name": row["sport_name"],
            "avg_strain": round(float(row["avg_strain"]), 2),
            "count": int(row["count"]),
        }
        for _, row in grouped.iterrows()
    ]
    return {"sports": sports}


@router.get("/insights")
def get_insights(
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Derived insights: HRV baseline, ACWR, sleep-recovery links, etc."""
    return build_insights(con)


@router.post("/sync")
def post_sync() -> dict[str, Any]:
    """Manual Refresh override: run the same server-side WHOOP sync as nightly."""
    if not is_whoop_connected():
        raise HTTPException(status_code=409, detail="WHOOP is not connected")
    client = build_whoop_client()
    con = acquire_writable_connection()
    try:
        result = sync_all_historical_data(client, force=True, con=con)
        recompute(con, trigger="manual")
    finally:
        con.close()
        client.close()
    return {"ok": True, "skipped": bool(result.get("skipped")), "records": result.get("records", 0)}


def _num(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except (TypeError, ValueError):
        return None
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float):
        return round(value, 2)
    return value
