"""DuckDB storage layer for WHOOP data.

Creates the local schema on first use and provides idempotent upsert
helpers keyed on each entity's natural WHOOP ID, so re-running a sync
is always safe: existing rows are replaced, never duplicated. Each
table also keeps a `raw` column with the full original API response so
no data is lost even if a field wasn't broken out into its own column.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "whoop.duckdb"

_SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS profile (
        user_id BIGINT PRIMARY KEY,
        email VARCHAR,
        first_name VARCHAR,
        last_name VARCHAR,
        synced_at TIMESTAMP,
        raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS body_measurement (
        user_id BIGINT PRIMARY KEY,
        height_meter DOUBLE,
        weight_kilogram DOUBLE,
        max_heart_rate INTEGER,
        synced_at TIMESTAMP,
        raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cycles (
        id BIGINT PRIMARY KEY,
        user_id BIGINT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        "start" TIMESTAMP,
        "end" TIMESTAMP,
        timezone_offset VARCHAR,
        score_state VARCHAR,
        strain DOUBLE,
        kilojoule DOUBLE,
        average_heart_rate INTEGER,
        max_heart_rate INTEGER,
        raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recovery (
        cycle_id BIGINT PRIMARY KEY,
        sleep_id VARCHAR,
        user_id BIGINT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        score_state VARCHAR,
        user_calibrating BOOLEAN,
        recovery_score INTEGER,
        resting_heart_rate INTEGER,
        hrv_rmssd_milli DOUBLE,
        spo2_percentage DOUBLE,
        skin_temp_celsius DOUBLE,
        raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sleep (
        id VARCHAR PRIMARY KEY,
        cycle_id BIGINT,
        v1_id BIGINT,
        user_id BIGINT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        "start" TIMESTAMP,
        "end" TIMESTAMP,
        timezone_offset VARCHAR,
        nap BOOLEAN,
        score_state VARCHAR,
        respiratory_rate DOUBLE,
        sleep_performance_percentage DOUBLE,
        sleep_consistency_percentage DOUBLE,
        sleep_efficiency_percentage DOUBLE,
        stage_summary VARCHAR,
        sleep_needed VARCHAR,
        raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workouts (
        id VARCHAR PRIMARY KEY,
        v1_id BIGINT,
        user_id BIGINT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP,
        "start" TIMESTAMP,
        "end" TIMESTAMP,
        timezone_offset VARCHAR,
        sport_id INTEGER,
        sport_name VARCHAR,
        score_state VARCHAR,
        strain DOUBLE,
        average_heart_rate INTEGER,
        max_heart_rate INTEGER,
        kilojoule DOUBLE,
        percent_recorded DOUBLE,
        distance_meter DOUBLE,
        altitude_gain_meter DOUBLE,
        altitude_change_meter DOUBLE,
        zone_durations VARCHAR,
        raw VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sync_state (
        entity VARCHAR PRIMARY KEY,
        high_water_mark TIMESTAMP,
        last_synced_at TIMESTAMP
    )
    """,
    # Rule-based daily insight brief (see thaalam.services.brief_service) --
    # logged for history/audit (which rules fire most often), not a cache,
    # since generation is free/instant and re-run on every page load.
    """
    CREATE TABLE IF NOT EXISTS insight_briefs (
        user_id BIGINT,
        brief_date DATE,
        brief_text VARCHAR,
        rule_ids VARCHAR,
        generated_at TIMESTAMP,
        PRIMARY KEY (user_id, brief_date)
    )
    """,
    # Live per-beat samples captured locally over Bluetooth from WHOOP's
    # official "HR Broadcast" feature (see thaalam.ble_stream). This is an
    # append-only telemetry log, not a synced-from-API entity, so rows have
    # a synthetic surrogate key instead of a natural WHOOP ID.
    """
    CREATE SEQUENCE IF NOT EXISTS hr_broadcast_samples_id_seq
    """,
    """
    CREATE TABLE IF NOT EXISTS hr_broadcast_samples (
        id BIGINT PRIMARY KEY DEFAULT nextval('hr_broadcast_samples_id_seq'),
        session_id VARCHAR,
        recorded_at TIMESTAMP,
        heart_rate INTEGER,
        rr_intervals_ms VARCHAR,
        sensor_contact BOOLEAN,
        energy_expended INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS derived_baselines (
        user_id BIGINT PRIMARY KEY,
        computed_at TIMESTAMP,
        n_nights INTEGER,
        n_sessions INTEGER,
        hrv_mean_90d DOUBLE,
        rhr_mean_90d DOUBLE,
        sleep_midpoint_mean_21d DOUBLE,
        calibrating BOOLEAN,
        awaiting_sleep_close BOOLEAN,
        yesterday_complete BOOLEAN,
        steps_source VARCHAR,
        weights VARCHAR
    )
    """,
    """
    CREATE SEQUENCE IF NOT EXISTS derived_recompute_log_id_seq
    """,
    """
    CREATE TABLE IF NOT EXISTS derived_recompute_log (
        id BIGINT PRIMARY KEY DEFAULT nextval('derived_recompute_log_id_seq'),
        user_id BIGINT,
        computed_at TIMESTAMP,
        trigger VARCHAR,
        n_nights INTEGER,
        n_sessions INTEGER,
        details VARCHAR
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS derived_runway (
        user_id BIGINT PRIMARY KEY,
        computed_at TIMESTAMP,
        payload VARCHAR
    )
    """,
]


def get_connection(db_path: str | Path = DEFAULT_DB_PATH) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the local WHOOP DuckDB database with its schema."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(db_path))
    for statement in _SCHEMA_STATEMENTS:
        con.execute(statement)
    logger.debug("Connected to DuckDB at %s", db_path)
    return con


def _upsert(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: list[str],
    rows: list[tuple[Any, ...]],
) -> None:
    if not rows:
        logger.debug("No rows to upsert into %s", table)
        return

    quoted_columns = ", ".join(f'"{column}"' for column in columns)
    placeholders = ", ".join(["?"] * len(columns))
    con.executemany(
        f'INSERT OR REPLACE INTO "{table}" ({quoted_columns}) VALUES ({placeholders})',
        rows,
    )
    logger.debug("Upserted %d row(s) into %s", len(rows), table)


def _as_json(value: Any) -> str | None:
    return json.dumps(value) if value is not None else None


def get_sync_state(con: duckdb.DuckDBPyConnection, entity: str) -> dict[str, Any] | None:
    """Return `{"high_water_mark": ..., "last_synced_at": ...}` for `entity`, or None.

    Returns None only if `entity` has never been synced at all (a full
    historical fetch should be done for it). Once synced at least once,
    `high_water_mark` may still be None if no records have ever been found
    for it, while `last_synced_at` is always set.
    """
    row = con.execute(
        'SELECT high_water_mark, last_synced_at FROM sync_state WHERE entity = ?',
        [entity],
    ).fetchone()
    if row is None:
        return None
    return {"high_water_mark": row[0], "last_synced_at": row[1]}


def set_sync_state(
    con: duckdb.DuckDBPyConnection,
    entity: str,
    high_water_mark: datetime | None,
    last_synced_at: datetime,
) -> None:
    """Record how far `entity` has been incrementally synced.

    `high_water_mark` may be None if `entity` has been checked but no
    records have ever been found for it yet -- `last_synced_at` is still
    recorded so the skip-guard knows this endpoint has been attempted.
    """
    _upsert(
        con,
        "sync_state",
        ["entity", "high_water_mark", "last_synced_at"],
        [(entity, high_water_mark, last_synced_at)],
    )


def upsert_profile(con: duckdb.DuckDBPyConnection, profile: dict[str, Any]) -> None:
    columns = ["user_id", "email", "first_name", "last_name", "synced_at", "raw"]
    row = (
        profile.get("user_id"),
        profile.get("email"),
        profile.get("first_name"),
        profile.get("last_name"),
        datetime.now(timezone.utc),
        _as_json(profile),
    )
    _upsert(con, "profile", columns, [row])


def upsert_body_measurement(
    con: duckdb.DuckDBPyConnection, user_id: int | None, measurement: dict[str, Any]
) -> None:
    columns = ["user_id", "height_meter", "weight_kilogram", "max_heart_rate", "synced_at", "raw"]
    row = (
        user_id,
        measurement.get("height_meter"),
        measurement.get("weight_kilogram"),
        measurement.get("max_heart_rate"),
        datetime.now(timezone.utc),
        _as_json(measurement),
    )
    _upsert(con, "body_measurement", columns, [row])


def upsert_cycles(con: duckdb.DuckDBPyConnection, cycles: list[dict[str, Any]]) -> None:
    columns = [
        "id", "user_id", "created_at", "updated_at", "start", "end", "timezone_offset",
        "score_state", "strain", "kilojoule", "average_heart_rate", "max_heart_rate", "raw",
    ]
    rows = []
    for cycle in cycles:
        score = cycle.get("score") or {}
        rows.append((
            cycle["id"],
            cycle.get("user_id"),
            cycle.get("created_at"),
            cycle.get("updated_at"),
            cycle.get("start"),
            cycle.get("end"),
            cycle.get("timezone_offset"),
            cycle.get("score_state"),
            score.get("strain"),
            score.get("kilojoule"),
            score.get("average_heart_rate"),
            score.get("max_heart_rate"),
            _as_json(cycle),
        ))
    _upsert(con, "cycles", columns, rows)


def upsert_recovery(con: duckdb.DuckDBPyConnection, recoveries: list[dict[str, Any]]) -> None:
    columns = [
        "cycle_id", "sleep_id", "user_id", "created_at", "updated_at", "score_state",
        "user_calibrating", "recovery_score", "resting_heart_rate", "hrv_rmssd_milli",
        "spo2_percentage", "skin_temp_celsius", "raw",
    ]
    rows = []
    for recovery in recoveries:
        score = recovery.get("score") or {}
        rows.append((
            recovery["cycle_id"],
            recovery.get("sleep_id"),
            recovery.get("user_id"),
            recovery.get("created_at"),
            recovery.get("updated_at"),
            recovery.get("score_state"),
            score.get("user_calibrating"),
            score.get("recovery_score"),
            score.get("resting_heart_rate"),
            score.get("hrv_rmssd_milli"),
            score.get("spo2_percentage"),
            score.get("skin_temp_celsius"),
            _as_json(recovery),
        ))
    _upsert(con, "recovery", columns, rows)


def upsert_sleep(con: duckdb.DuckDBPyConnection, sleeps: list[dict[str, Any]]) -> None:
    columns = [
        "id", "cycle_id", "v1_id", "user_id", "created_at", "updated_at", "start", "end",
        "timezone_offset", "nap", "score_state", "respiratory_rate",
        "sleep_performance_percentage", "sleep_consistency_percentage",
        "sleep_efficiency_percentage", "stage_summary", "sleep_needed", "raw",
    ]
    rows = []
    for sleep in sleeps:
        score = sleep.get("score") or {}
        rows.append((
            sleep["id"],
            sleep.get("cycle_id"),
            sleep.get("v1_id"),
            sleep.get("user_id"),
            sleep.get("created_at"),
            sleep.get("updated_at"),
            sleep.get("start"),
            sleep.get("end"),
            sleep.get("timezone_offset"),
            sleep.get("nap"),
            sleep.get("score_state"),
            score.get("respiratory_rate"),
            score.get("sleep_performance_percentage"),
            score.get("sleep_consistency_percentage"),
            score.get("sleep_efficiency_percentage"),
            _as_json(score.get("stage_summary")),
            _as_json(score.get("sleep_needed")),
            _as_json(sleep),
        ))
    _upsert(con, "sleep", columns, rows)


def insert_hr_broadcast_samples(
    con: duckdb.DuckDBPyConnection, samples: list[dict[str, Any]]
) -> None:
    """Append live BLE HR Broadcast samples (append-only; never deduped/replaced).

    Each sample is one Bluetooth Heart Rate Measurement notification --
    instantaneous BPM plus zero or more RR-intervals (ms), present only if
    the sensor included them. RR-intervals are the raw beat-to-beat data
    HRV/rmssd is derived from; WHOOP's own recovery HRV is a separate
    proprietary calculation, not reproduced here.
    """
    if not samples:
        logger.debug("No live HR broadcast samples to insert")
        return

    rows = [
        (
            sample["session_id"],
            sample["recorded_at"],
            sample["heart_rate"],
            _as_json(sample.get("rr_intervals_ms")),
            sample.get("sensor_contact"),
            sample.get("energy_expended"),
        )
        for sample in samples
    ]
    con.executemany(
        "INSERT INTO hr_broadcast_samples "
        "(session_id, recorded_at, heart_rate, rr_intervals_ms, sensor_contact, energy_expended) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
    logger.debug("Inserted %d live HR broadcast sample(s)", len(rows))


def record_insight_brief(
    con: duckdb.DuckDBPyConnection,
    user_id: int,
    brief_date: str,
    brief_text: str,
    rule_ids: list[str],
) -> None:
    """Log a generated daily brief for history/audit -- not a cache."""
    _upsert(
        con,
        "insight_briefs",
        ["user_id", "brief_date", "brief_text", "rule_ids", "generated_at"],
        [(user_id, brief_date, brief_text, _as_json(rule_ids), datetime.now(timezone.utc))],
    )


def delete_sleep(con: duckdb.DuckDBPyConnection, sleep_id: Any) -> None:
    con.execute("DELETE FROM sleep WHERE CAST(id AS VARCHAR) = ?", [str(sleep_id)])


def delete_workout(con: duckdb.DuckDBPyConnection, workout_id: Any) -> None:
    con.execute("DELETE FROM workouts WHERE CAST(id AS VARCHAR) = ?", [str(workout_id)])


def delete_recovery(con: duckdb.DuckDBPyConnection, resource_id: Any) -> None:
    """Delete a recovery by sleep UUID (v2) or cycle id (v1). Missing rows are a no-op."""
    con.execute("DELETE FROM recovery WHERE CAST(sleep_id AS VARCHAR) = ?", [str(resource_id)])
    try:
        cycle_id = int(resource_id)
    except (TypeError, ValueError):
        return
    con.execute("DELETE FROM recovery WHERE cycle_id = ?", [cycle_id])


def upsert_derived_baseline(con: duckdb.DuckDBPyConnection, row: dict[str, Any]) -> None:
    columns = [
        "user_id",
        "computed_at",
        "n_nights",
        "n_sessions",
        "hrv_mean_90d",
        "rhr_mean_90d",
        "sleep_midpoint_mean_21d",
        "calibrating",
        "awaiting_sleep_close",
        "yesterday_complete",
        "steps_source",
        "weights",
    ]
    values = (
        row.get("user_id"),
        row.get("computed_at"),
        row.get("n_nights"),
        row.get("n_sessions"),
        row.get("hrv_mean_90d"),
        row.get("rhr_mean_90d"),
        row.get("sleep_midpoint_mean_21d"),
        row.get("calibrating"),
        row.get("awaiting_sleep_close"),
        row.get("yesterday_complete"),
        row.get("steps_source"),
        row.get("weights") if isinstance(row.get("weights"), str) else _as_json(row.get("weights")),
    )
    _upsert(con, "derived_baselines", columns, [values])


def get_derived_baseline(
    con: duckdb.DuckDBPyConnection, user_id: int | None = None
) -> dict[str, Any] | None:
    sql = """
        SELECT user_id, computed_at, n_nights, n_sessions,
               hrv_mean_90d, rhr_mean_90d, sleep_midpoint_mean_21d,
               calibrating, awaiting_sleep_close, yesterday_complete,
               steps_source, weights
        FROM derived_baselines
    """
    params: list[Any] = []
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params.append(user_id)
    sql += " LIMIT 1"
    row = con.execute(sql, params).fetchone()
    if row is None:
        return None
    weights = row[11]
    if isinstance(weights, str):
        try:
            weights = json.loads(weights)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return {
        "user_id": row[0],
        "computed_at": row[1],
        "n_nights": row[2],
        "n_sessions": row[3],
        "hrv_mean_90d": row[4],
        "rhr_mean_90d": row[5],
        "sleep_midpoint_mean_21d": row[6],
        "calibrating": bool(row[7]) if row[7] is not None else None,
        "awaiting_sleep_close": bool(row[8]) if row[8] is not None else None,
        "yesterday_complete": bool(row[9]) if row[9] is not None else None,
        "steps_source": row[10],
        "weights": weights,
    }


def record_derived_recompute(
    con: duckdb.DuckDBPyConnection,
    user_id: int | None,
    trigger: str,
    n_nights: int,
    n_sessions: int,
    details: dict[str, Any] | None = None,
) -> None:
    con.execute(
        "INSERT INTO derived_recompute_log "
        "(user_id, computed_at, trigger, n_nights, n_sessions, details) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            user_id,
            datetime.now(timezone.utc).replace(tzinfo=None),
            trigger,
            n_nights,
            n_sessions,
            _as_json(details),
        ],
    )


def upsert_derived_runway(
    con: duckdb.DuckDBPyConnection,
    user_id: int,
    payload: dict[str, Any],
    computed_at: datetime | None = None,
) -> None:
    stamped = computed_at or datetime.now(timezone.utc).replace(tzinfo=None)
    _upsert(
        con,
        "derived_runway",
        ["user_id", "computed_at", "payload"],
        [(user_id, stamped, _as_json(payload))],
    )


def get_derived_runway(
    con: duckdb.DuckDBPyConnection, user_id: int | None = None
) -> dict[str, Any] | None:
    sql = "SELECT payload FROM derived_runway"
    params: list[Any] = []
    if user_id is not None:
        sql += " WHERE user_id = ?"
        params.append(user_id)
    sql += " LIMIT 1"
    row = con.execute(sql, params).fetchone()
    if row is None or row[0] is None:
        return None
    payload = row[0]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
    return payload if isinstance(payload, dict) else None


def upsert_workouts(con: duckdb.DuckDBPyConnection, workouts: list[dict[str, Any]]) -> None:
    columns = [
        "id", "v1_id", "user_id", "created_at", "updated_at", "start", "end", "timezone_offset",
        "sport_id", "sport_name", "score_state", "strain", "average_heart_rate", "max_heart_rate",
        "kilojoule", "percent_recorded", "distance_meter", "altitude_gain_meter",
        "altitude_change_meter", "zone_durations", "raw",
    ]
    rows = []
    for workout in workouts:
        score = workout.get("score") or {}
        rows.append((
            workout["id"],
            workout.get("v1_id"),
            workout.get("user_id"),
            workout.get("created_at"),
            workout.get("updated_at"),
            workout.get("start"),
            workout.get("end"),
            workout.get("timezone_offset"),
            workout.get("sport_id"),
            workout.get("sport_name"),
            workout.get("score_state"),
            score.get("strain"),
            score.get("average_heart_rate"),
            score.get("max_heart_rate"),
            score.get("kilojoule"),
            score.get("percent_recorded"),
            score.get("distance_meter"),
            score.get("altitude_gain_meter"),
            score.get("altitude_change_meter"),
            _as_json(score.get("zone_durations")),
            _as_json(workout),
        ))
    _upsert(con, "workouts", columns, rows)
