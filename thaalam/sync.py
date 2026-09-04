"""Fetch new WHOOP data since the last run and store it in DuckDB.

The first run (and OAuth connect) backfills the last `BACKFILL_DAYS`
(default 90) with `start`/`end` + `nextToken` pagination. Every later
run only fetches data since that endpoint's stored high-water mark, with
a trailing overlap window -- WHOOP scores can keep finalizing for a few
days after a cycle/sleep/workout occurs, so a small overlap re-fetch
picks up those updates. Progress is tracked in the `sync_state` table,
and upserts are keyed by WHOOP's own IDs, so re-running is always safe.

The nightly job re-fetches the last `RECONCILE_DAYS` (default 7) because
WHOOP data is editable retroactively. Manual Refresh uses this same
sync path as an override.

If every endpoint was already synced more recently than
`MIN_SYNC_INTERVAL_MINUTES` ago, the whole sync is skipped (no API
calls at all) since WHOOP only produces new data roughly once a day.
Set `MIN_SYNC_INTERVAL_MINUTES=0` to always sync. Pass `force=True` to
bypass the skip guard (Refresh / nightly / OAuth backfill).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable

import duckdb

from thaalam import db
from thaalam.whoop_client.client import WhoopClient

logger = logging.getLogger(__name__)

# First-connect / reconnect window. Later runs are incremental.
BACKFILL_DAYS = int(os.getenv("WHOOP_BACKFILL_DAYS", "90"))

# Nightly reconciliation window -- WHOOP records stay editable after the fact.
RECONCILE_DAYS = int(os.getenv("WHOOP_RECONCILE_DAYS", "7"))

# WHOOP scores can keep finalizing for a few days after a cycle occurs, so
# incremental runs re-fetch a trailing overlap window rather than starting
# exactly at the last high-water mark.
OVERLAP_BUFFER = timedelta(days=3)

# Skip the whole sync if every endpoint was already synced more recently than
# this. 0 (or negative) disables the guard and always syncs.
MIN_SYNC_INTERVAL_MINUTES = float(os.getenv("MIN_SYNC_INTERVAL_MINUTES", "60"))

_SYNC_LOCK = Lock()

# (log label, sync_state entity name) for each paginated collection endpoint.
_COLLECTIONS: list[tuple[str, str]] = [
    ("cycles", "cycles"),
    ("recovery records", "recovery"),
    ("sleep records", "sleep"),
    ("workouts", "workouts"),
]


def sync_all_historical_data(
    client: WhoopClient,
    db_path: str | Path | None = None,
    *,
    force: bool = False,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    """Fetch profile, body measurement, and any new cycles/recovery/sleep/workouts.

    First run backfills `BACKFILL_DAYS`; later runs are incremental with overlap.
    Pass `con` to reuse the API process connection instead of a second connect().
    """
    with _SYNC_LOCK:
        return _sync_locked(client, db_path, force=force, mode="auto", con=con)


def backfill_window(
    client: WhoopClient,
    db_path: str | Path | None = None,
    *,
    days: int = BACKFILL_DAYS,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    """Fetch a bounded start/end window (OAuth connect uses 90 days)."""
    with _SYNC_LOCK:
        return _sync_locked(
            client, db_path, force=True, mode="backfill", window_days=days, con=con
        )


def reconcile_recent(
    client: WhoopClient,
    db_path: str | Path | None = None,
    *,
    days: int = RECONCILE_DAYS,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    """Re-fetch the last `days` because WHOOP records can be edited after the fact."""
    with _SYNC_LOCK:
        return _sync_locked(
            client, db_path, force=True, mode="reconcile", window_days=days, con=con
        )


def _sync_locked(
    client: WhoopClient,
    db_path: str | Path | None,
    *,
    force: bool,
    mode: str,
    window_days: int | None = None,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    owns_connection = con is None
    if con is None:
        con = db.get_connection(db_path) if db_path is not None else db.get_connection()

    try:
        if not force:
            wait_minutes = _minutes_until_ready(con)
            if wait_minutes is not None:
                logger.info(
                    "Already up to date -- last sync was recent enough that new data is "
                    "unlikely yet. Skipping for now; try again in about %d minute(s) "
                    "(or set MIN_SYNC_INTERVAL_MINUTES=0 to force a sync).",
                    wait_minutes,
                )
                return {"skipped": True, "wait_minutes": wait_minutes, "records": 0}

        sync_started_at = time.monotonic()
        logger.info("Starting WHOOP sync (%s)...", mode)

        logger.info("Fetching profile...")
        profile = client.get_profile()
        db.upsert_profile(con, profile)
        user_id = profile.get("user_id")
        logger.info("Profile stored (user_id=%s)", user_id)

        logger.info("Fetching body measurement...")
        measurement = client.get_body_measurement()
        db.upsert_body_measurement(con, user_id, measurement)
        logger.info("Body measurement stored")

        fetchers: dict[str, Callable[..., list[dict[str, Any]]]] = {
            "cycles": client.get_cycle_collection,
            "recovery": client.get_recovery_collection,
            "sleep": client.get_sleep_collection,
            "workouts": client.get_workout_collection,
        }
        upserters: dict[str, Callable[[duckdb.DuckDBPyConnection, list[dict[str, Any]]], None]] = {
            "cycles": db.upsert_cycles,
            "recovery": db.upsert_recovery,
            "sleep": db.upsert_sleep,
            "workouts": db.upsert_workouts,
        }

        now = _utc_now()
        new_record_count = 0
        for label, entity in _COLLECTIONS:
            start_date, end_date = _window_for(con, entity, now, mode, window_days)
            new_record_count += _sync_collection(
                con,
                label,
                entity,
                fetchers[entity],
                upserters[entity],
                start_date,
                end_date,
            )

        elapsed = time.monotonic() - sync_started_at
        if new_record_count:
            logger.info("Sync complete in %.1fs -- %d new record(s) stored.", elapsed, new_record_count)
        else:
            logger.info("Sync complete in %.1fs -- no new data found.", elapsed)
        return {"skipped": False, "records": new_record_count, "mode": mode, "user_id": user_id}
    except Exception:
        logger.exception("Sync failed")
        raise
    finally:
        if owns_connection:
            con.close()


def _window_for(
    con: duckdb.DuckDBPyConnection,
    entity: str,
    now: datetime,
    mode: str,
    window_days: int | None,
) -> tuple[str, str | None]:
    if mode in ("backfill", "reconcile"):
        days = window_days if window_days is not None else (
            BACKFILL_DAYS if mode == "backfill" else RECONCILE_DAYS
        )
        start = now - timedelta(days=days)
        return start.isoformat(), now.isoformat()

    state = db.get_sync_state(con, entity)
    if state is None:
        start = now - timedelta(days=window_days or BACKFILL_DAYS)
        return start.isoformat(), now.isoformat()

    mark = state["high_water_mark"] or state["last_synced_at"]
    start = (mark - OVERLAP_BUFFER) if mark is not None else now - timedelta(days=BACKFILL_DAYS)
    return start.isoformat(), None


def _minutes_until_ready(con: duckdb.DuckDBPyConnection) -> int | None:
    """Minutes left before the next sync should run, or None if it's fine to run now."""
    if MIN_SYNC_INTERVAL_MINUTES <= 0:
        return None

    states = [db.get_sync_state(con, entity) for _label, entity in _COLLECTIONS]
    if any(state is None for state in states):
        return None  # at least one endpoint has never been synced -- always run

    last_synced_at = min(state["last_synced_at"] for state in states)
    elapsed_minutes = (_utc_now() - last_synced_at).total_seconds() / 60
    remaining = MIN_SYNC_INTERVAL_MINUTES - elapsed_minutes
    return int(remaining) + 1 if remaining > 0 else None


def _sync_collection(
    con: duckdb.DuckDBPyConnection,
    label: str,
    entity: str,
    fetch_fn: Callable[..., list[dict[str, Any]]],
    upsert_fn: Callable[[duckdb.DuckDBPyConnection, list[dict[str, Any]]], None],
    start_date: str,
    end_date: str | None,
) -> int:
    state = db.get_sync_state(con, entity)

    if end_date:
        logger.info("Fetching %s from %s to %s...", label, start_date, end_date)
    else:
        logger.info("Fetching new %s since %s...", label, start_date)

    started_at = time.monotonic()
    records = fetch_fn(start_date, end_date)
    upsert_fn(con, records)
    elapsed = time.monotonic() - started_at

    previous_mark = state["high_water_mark"] if state else None
    high_water_mark = max((m for m in (_latest_timestamp(records), previous_mark) if m is not None), default=None)
    # Always record that this entity was checked (even with 0 new records or no
    # watermark yet) so the skip-guard knows every endpoint has been attempted.
    db.set_sync_state(con, entity, high_water_mark, _utc_now())

    logger.info("%d %s stored in %.1fs", len(records), label, elapsed)
    return len(records)


def _latest_timestamp(records: list[dict[str, Any]]) -> datetime | None:
    """Latest occurrence timestamp (`end`, falling back to `start`/`created_at`) in records."""
    timestamps = [
        _parse_whoop_datetime(raw)
        for record in records
        if (raw := record.get("end") or record.get("start") or record.get("created_at"))
    ]
    return max(timestamps) if timestamps else None


def _parse_whoop_datetime(value: str) -> datetime:
    """Parse a WHOOP timestamp string into a naive UTC `datetime`."""
    raw = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _utc_now() -> datetime:
    """Current time as a naive UTC `datetime`, matching how sync_state timestamps are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
