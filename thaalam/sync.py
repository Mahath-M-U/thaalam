"""Fetch WHOOP data and store it in DuckDB.

Connecting an account backfills the user's **entire** WHOOP history --
every cycle, recovery, sleep and workout back to the day the strap was
first activated -- not a fixed recent window. WHOOP itself decides where
that history starts: the request floor is `WHOOP_HISTORY_START` (default
2014-01-01, before any consumer WHOOP existed), and the API simply
returns nothing before the account's first record.

That walk is thousands of requests, so it is paced and resumable:

* `WhoopClient` paces every request under WHOOP's published limits (100
  requests/minute, 10,000/day) instead of sprinting into a 429.
* Each page is stored as it arrives and the cursor for the next page is
  saved with it. A backfill stopped by the daily request budget, a
  redeploy, or a crash resumes from that cursor on the next run rather
  than starting the years over -- so the import can legitimately span
  more than one day without ever re-spending budget on data it holds.
* Any later sync (Refresh, nightly, webhook) resumes an unfinished
  backfill before doing its own incremental work.

Once the history is complete, every later run only fetches data since
that endpoint's stored high-water mark, with a trailing overlap window --
WHOOP scores can keep finalizing for a few days after a cycle/sleep/
workout occurs, so a small overlap re-fetch picks up those updates.
Progress is tracked in the `sync_state` table, and upserts are keyed by
WHOOP's own IDs, so re-running is always safe.

The nightly job re-fetches the last `RECONCILE_DAYS` (default 7) because
WHOOP data is editable retroactively. Manual Refresh uses this same
sync path as an override.

If every endpoint was already synced more recently than
`MIN_SYNC_INTERVAL_MINUTES` ago, the whole sync is skipped (no API
calls at all) since WHOOP only produces new data roughly once a day.
Set `MIN_SYNC_INTERVAL_MINUTES=0` to always sync. Pass `force=True` to
bypass the skip guard (Refresh / nightly / OAuth backfill). An
unfinished historical backfill always bypasses it.
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
from requests.exceptions import HTTPError

from thaalam import db
from thaalam.whoop_client.client import WhoopClient
from thaalam.whoop_client.rate_limit import WhoopDailyLimitReached

logger = logging.getLogger(__name__)

# Bounded first-connect window, kept for callers that explicitly want one
# (and as the opt-out below). The default connect path is full history.
BACKFILL_DAYS = int(os.getenv("WHOOP_BACKFILL_DAYS", "90"))

# Connecting an account imports everything WHOOP has for it. Set
# WHOOP_FULL_HISTORY=false to go back to the old fixed BACKFILL_DAYS window.
FULL_HISTORY = os.getenv("WHOOP_FULL_HISTORY", "true").strip().lower() not in {
    "0", "false", "no", "off",
}

# Floor for the history walk. There is no "account created" field on WHOOP's
# profile endpoint, so instead of guessing an activation date we ask from
# before any consumer WHOOP existed (the first strap shipped in 2015) and let
# the API return nothing earlier than the user's first record. Costs nothing:
# an empty prefix returns no pages, it does not walk one page per empty year.
HISTORY_START = os.getenv("WHOOP_HISTORY_START", "2014-01-01")

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

    Resumes an unfinished historical backfill first (see
    `backfill_full_history`), then fetches incrementally from each
    endpoint's high-water mark with a trailing overlap.

    Pass `con` to reuse the API process connection instead of a second connect().
    """
    with _SYNC_LOCK:
        return _sync_locked(client, db_path, force=force, mode="auto", con=con)


def backfill_full_history(
    client: WhoopClient,
    db_path: str | Path | None = None,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    """Import every record WHOOP holds, back to the account's first day.

    Used when an account is connected. Safe to call repeatedly: endpoints
    whose history is already complete fall through to an incremental
    fetch, and an interrupted one picks up at its saved cursor.

    Returns `partial=True` (rather than raising) when the day's request
    budget runs out mid-walk -- everything fetched so far is stored, and
    the next run continues from there.
    """
    with _SYNC_LOCK:
        return _sync_locked(client, db_path, force=True, mode="history", con=con)


def resume_history_if_pending(
    client: WhoopClient,
    db_path: str | Path | None = None,
    *,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    """Carry an unfinished historical import forward, or do nothing.

    The nightly job calls this so a history too large for one day's
    request budget still finishes on its own, without the user having to
    press Refresh until it does.
    """
    owns_connection = con is None
    check_con = con
    if check_con is None:
        check_con = (
            db.get_connection(db_path) if db_path is not None else db.get_connection()
        )
    try:
        if not _history_pending(check_con):
            return {"skipped": True, "reason": "history_complete", "records": 0}
    finally:
        if owns_connection:
            check_con.close()

    return backfill_full_history(client, db_path, con=con)


def backfill_window(
    client: WhoopClient,
    db_path: str | Path | None = None,
    *,
    days: int = BACKFILL_DAYS,
    con: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    """Fetch a bounded start/end window, ignoring anything older than `days`."""
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
        if not force and not _history_pending(con):
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
        partial = False

        for label, entity in _COLLECTIONS:
            try:
                if _should_backfill_history(con, entity, mode):
                    # Returns what it stored even when the budget cut it
                    # short -- those records are already in the database, and
                    # a run that reports 0 after storing thousands is the
                    # kind of thing that sends someone hunting a phantom bug.
                    stored_now, stopped = _backfill_history(
                        con, label, entity, fetchers[entity], upserters[entity], now
                    )
                    new_record_count += stored_now
                    if stopped:
                        partial = True
                        break
                    continue

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
            except WhoopDailyLimitReached as exc:
                # Not a failure: the history import is designed to span days.
                # Everything fetched so far is already stored, and each
                # endpoint's cursor is saved, so the next run continues.
                logger.warning(
                    "Stopping this sync at %s -- %s", label, exc,
                )
                partial = True
                break

        elapsed = time.monotonic() - sync_started_at
        if partial:
            logger.info(
                "Sync paused in %.1fs -- %d record(s) stored before the daily WHOOP "
                "request budget ran out. It resumes on the next run.",
                elapsed, new_record_count,
            )
        elif new_record_count:
            logger.info("Sync complete in %.1fs -- %d new record(s) stored.", elapsed, new_record_count)
        else:
            logger.info("Sync complete in %.1fs -- no new data found.", elapsed)

        return {
            "skipped": False,
            "records": new_record_count,
            "mode": mode,
            "user_id": user_id,
            "partial": partial,
            "history_complete": _history_complete(con),
        }
    except Exception:
        logger.exception("Sync failed")
        raise
    finally:
        if owns_connection:
            con.close()


def _should_backfill_history(
    con: duckdb.DuckDBPyConnection, entity: str, mode: str
) -> bool:
    """Whether this endpoint still owes us a walk back through its history.

    True until that walk has finished, so it covers all three ways of
    arriving here: a freshly connected account, a walk that stopped
    part-way (any later sync carries it on), and a database from before
    full-history sync existed, whose rows have no completion flag and so
    are still missing everything older than the old 90-day window.

    `reconcile` and `backfill` are deliberately bounded windows and never
    trigger it.
    """
    if not FULL_HISTORY or mode in ("reconcile", "backfill"):
        return False
    state = db.get_sync_state(con, entity)
    return not (state and state.get("backfill_complete"))


def _history_pending(con: duckdb.DuckDBPyConnection) -> bool:
    """Whether any endpoint has history left to import.

    Such a sync must not be skipped by the every-N-minutes guard: the
    guard exists because WHOOP produces new data roughly once a day, but
    an unfinished backfill has years of *old* data still to fetch.
    """
    return FULL_HISTORY and not _history_complete(con)


def _history_complete(con: duckdb.DuckDBPyConnection) -> bool:
    """Whether every endpoint has finished its walk back through history."""
    if not FULL_HISTORY:
        return True
    return all(
        bool((db.get_sync_state(con, entity) or {}).get("backfill_complete"))
        for _label, entity in _COLLECTIONS
    )


def _backfill_history(
    con: duckdb.DuckDBPyConnection,
    label: str,
    entity: str,
    fetch_fn: Callable[..., list[dict[str, Any]]],
    upsert_fn: Callable[[duckdb.DuckDBPyConnection, list[dict[str, Any]]], None],
    now: datetime,
) -> tuple[int, bool]:
    """Walk `entity` back to the first record WHOOP has, storing as we go.

    Returns `(records stored this run, stopped by the daily budget)`.

    Each page is upserted and its cursor saved before the next one is
    requested, so this is safe to interrupt at any point: whatever caused
    the stop (the daily request budget, a redeploy, a crash), the next
    run resumes at the saved cursor instead of re-walking -- and
    re-paying for -- history already stored.
    """
    state = db.get_sync_state(con, entity)
    cursor = state.get("backfill_cursor") if state else None
    stored = int(state.get("backfill_records") or 0) if state else 0
    started_at = (state.get("backfill_started_at") if state else None) or now

    if cursor:
        logger.info(
            "Resuming %s history backfill (%d already stored)...", label, stored
        )
    else:
        logger.info("Backfilling all %s since %s...", label, HISTORY_START)

    fetched = 0
    complete = False
    high_water_mark = state.get("high_water_mark") if state else None
    started = time.monotonic()

    def handle_page(records: list[dict[str, Any]], next_token: str | None) -> None:
        nonlocal fetched, high_water_mark, complete
        upsert_fn(con, records)
        fetched += len(records)
        complete = next_token is None

        latest = _latest_timestamp(records)
        high_water_mark = max(
            (m for m in (latest, high_water_mark) if m is not None), default=None
        )
        db.set_backfill_progress(
            con,
            entity,
            cursor=next_token,
            complete=complete,
            records=stored + fetched,
            started_at=started_at,
            finished_at=_utc_now() if complete else None,
        )

    stopped = False
    try:
        try:
            fetch_fn(HISTORY_START, None, on_page=handle_page, next_token=cursor)
        except HTTPError as exc:
            if cursor is None or not _is_bad_cursor(exc):
                raise
            # WHOOP no longer accepts the cursor we saved (they are opaque and
            # need not outlive a run). Restarting the walk is the safe repair:
            # upserts are keyed by WHOOP's IDs, so re-reading pages we already
            # hold costs requests but cannot corrupt or duplicate anything.
            logger.warning(
                "Saved %s backfill cursor was rejected by WHOOP; restarting "
                "that history walk from the beginning.", label,
            )
            stored = 0
            fetch_fn(HISTORY_START, None, on_page=handle_page, next_token=None)
    except WhoopDailyLimitReached as exc:
        # Expected for a long history, and not an error: every page already
        # handed to `handle_page` is stored and its cursor saved.
        logger.warning("Paused the %s history import -- %s", label, exc)
        stopped = True
    finally:
        # Record the attempt (and any new high-water mark) even when the walk
        # is cut short, so incremental syncs have a mark to work from.
        db.set_sync_state(con, entity, high_water_mark, _utc_now())

    logger.info(
        "%d %s stored in %.1fs -- history %s (%d total).",
        fetched,
        label,
        time.monotonic() - started,
        "complete" if complete else "still incomplete",
        stored + fetched,
    )
    return fetched, stopped


def _is_bad_cursor(exc: HTTPError) -> bool:
    """Whether WHOOP rejected the request because of the `nextToken` we sent."""
    response = getattr(exc, "response", None)
    return response is not None and response.status_code in (400, 404)


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
