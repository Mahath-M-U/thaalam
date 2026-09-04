"""Server-side derived metrics stored in DuckDB.

The client never recomputes a baseline, slope, or projection -- it reads
the stored `derived_baselines`, vitality, reads, and runway rows.
`recompute()` stores baselines, Vitality Score, eleven reads, and runway
from real WHOOP rows.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import duckdb

from thaalam import db

logger = logging.getLogger(__name__)

CALIBRATING_NIGHTS = 14
HRV_WINDOW_DAYS = 90
RHR_WINDOW_DAYS = 90
SLEEP_MIDPOINT_NIGHTS = 21

# Option 1 (HealthKit / Health Connect steps connected) -- §4.1 weights.
OPTION1_WEIGHTS = {
    "load": 300,
    "movement": 220,
    "autonomic": 200,
    "sleep": 180,
    "rhythm": 100,
}

# Option 2 (no step source) -- §6 reweight, recorded so later score PRs can
# read it instead of inventing a step count.
OPTION2_WEIGHTS = {
    "load": 340,
    "autonomic": 250,
    "sleep": 250,
    "rhythm": 160,
}


def steps_source() -> str:
    raw = (os.getenv("STEPS_SOURCE") or "none").strip().lower()
    return raw if raw in ("healthkit", "none") else "none"


def score_weights(source: str | None = None) -> dict[str, int]:
    src = source if source is not None else steps_source()
    return dict(OPTION1_WEIGHTS if src == "healthkit" else OPTION2_WEIGHTS)


def recompute(
    con: duckdb.DuckDBPyConnection,
    *,
    trigger: str = "manual",
    user_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Recompute derived metrics from stored WHOOP rows and persist them.

    Baseline means/counts are filled in here. Band/regression slots are
    placeholders for later PRs -- we do not invent values for them.
    """
    now = _naive_utc(now)
    resolved_user_id = user_id if user_id is not None else _profile_user_id(con)
    source = steps_source()
    weights = score_weights(source)

    n_nights = _count(con, "SELECT COUNT(*) FROM sleep WHERE COALESCE(nap, FALSE) = FALSE")
    n_sessions = _count(con, "SELECT COUNT(*) FROM workouts")
    n_recovery = _count(con, "SELECT COUNT(*) FROM recovery")

    hrv_mean = _mean_in_window(con, "recovery", "hrv_rmssd_milli", "created_at", now, HRV_WINDOW_DAYS)
    rhr_mean = _mean_in_window(con, "recovery", "resting_heart_rate", "created_at", now, RHR_WINDOW_DAYS)
    midpoint_mean = _sleep_midpoint_mean(con, limit=SLEEP_MIDPOINT_NIGHTS)

    calibrating = n_nights < CALIBRATING_NIGHTS or n_recovery < CALIBRATING_NIGHTS
    awaiting_sleep_close, yesterday_complete = _sleep_close_state(con, now)

    row = {
        "user_id": resolved_user_id,
        "computed_at": now,
        "n_nights": n_nights,
        "n_sessions": n_sessions,
        "hrv_mean_90d": hrv_mean,
        "rhr_mean_90d": rhr_mean,
        "sleep_midpoint_mean_21d": midpoint_mean,
        "calibrating": calibrating,
        "awaiting_sleep_close": awaiting_sleep_close,
        "yesterday_complete": yesterday_complete,
        "steps_source": source,
        "weights": weights,
    }

    if resolved_user_id is not None:
        db.upsert_derived_baseline(con, row)
        from thaalam.services.vitality_score import persist_vitality
        from thaalam.services.runway_service import compute_and_store_runway

        persist_vitality(con, user_id=resolved_user_id, now=now, baseline=row)
        runway_payload = compute_and_store_runway(
            con, now=now, user_id=resolved_user_id
        )
        db.record_derived_recompute(
            con,
            resolved_user_id,
            trigger,
            n_nights,
            n_sessions,
            details={
                "calibrating": calibrating,
                "awaiting_sleep_close": awaiting_sleep_close,
                "bands": None,
                "regression": None,
                "runway_calibrating": bool(runway_payload.get("calibrating")),
            },
        )
        logger.info(
            "Derived baselines recomputed (trigger=%s user_id=%s nights=%d sessions=%d calibrating=%s)",
            trigger,
            resolved_user_id,
            n_nights,
            n_sessions,
            calibrating,
        )
        try:
            from thaalam.services.reads_service import compute_and_store_reads

            compute_and_store_reads(con, user_id=resolved_user_id, now=now)
        except Exception:
            logger.exception("Failed to compute derived reads")
    else:
        logger.info("No profile user_id; derived baselines not stored")

    stored = db.get_derived_baseline(con, resolved_user_id) if resolved_user_id is not None else None
    return stored or row


def _profile_user_id(con: duckdb.DuckDBPyConnection) -> int | None:
    row = con.execute("SELECT user_id FROM profile LIMIT 1").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _count(con: duckdb.DuckDBPyConnection, sql: str) -> int:
    row = con.execute(sql).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def _mean_in_window(
    con: duckdb.DuckDBPyConnection,
    table: str,
    column: str,
    time_column: str,
    now: datetime,
    days: int,
) -> float | None:
    cutoff = now - timedelta(days=days)
    rows = con.execute(
        f'SELECT "{column}", "{time_column}" FROM "{table}" WHERE "{column}" IS NOT NULL'
    ).fetchall()
    values: list[float] = []
    for value, stamped in rows:
        when = _as_datetime(stamped)
        if when is not None and when < cutoff:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    return sum(values) / len(values)


def _sleep_midpoint_mean(con: duckdb.DuckDBPyConnection, *, limit: int) -> float | None:
    rows = con.execute(
        """
        SELECT "start", "end", timezone_offset
        FROM sleep
        WHERE COALESCE(nap, FALSE) = FALSE
          AND "start" IS NOT NULL
          AND "end" IS NOT NULL
        ORDER BY "end" DESC
        LIMIT ?
        """,
        [limit],
    ).fetchall()
    hours = [h for h in (_sleep_midpoint_hours(s, e, tz) for s, e, tz in rows) if h is not None]
    if not hours:
        return None
    return sum(hours) / len(hours)


def _sleep_midpoint_hours(start: Any, end: Any, timezone_offset: Any) -> float | None:
    start_dt = _as_datetime(start)
    end_dt = _as_datetime(end)
    if start_dt is None or end_dt is None:
        return None
    mid = start_dt + (end_dt - start_dt) / 2
    local = mid + _parse_offset(timezone_offset)
    return local.hour + local.minute / 60.0 + local.second / 3600.0


def _sleep_close_state(con: duckdb.DuckDBPyConnection, now: datetime) -> tuple[bool, bool]:
    """(awaiting_sleep_close, yesterday_complete) from stored sleeps."""
    row = con.execute(
        """
        SELECT MAX("end")
        FROM sleep
        WHERE COALESCE(nap, FALSE) = FALSE AND "end" IS NOT NULL
        """
    ).fetchone()
    latest_end = _as_datetime(row[0]) if row else None
    yesterday_complete = latest_end is not None
    if latest_end is None:
        return False, False
    awaiting = latest_end.date() < now.date()
    return awaiting, yesterday_complete


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
