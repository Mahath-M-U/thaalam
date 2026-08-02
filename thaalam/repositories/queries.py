"""Query helpers ("repository" pattern) for the WHOOP DuckDB database.

Each function accepts an already-open `duckdb.DuckDBPyConnection` (see
`thaalam.db.get_connection`, or a read-only connection for ad-hoc
analysis -- see `thaalam.report`) and returns a tidy `pandas.DataFrame`
for one table or a joined view. Nothing in this module mutates the
database or manages connection lifecycle; that's the caller's job.
"""

from __future__ import annotations

import logging

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def load_profile(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return the (single-row) WHOOP profile table."""
    return con.execute(
        """
        SELECT user_id, email, first_name, last_name, synced_at
        FROM profile
        """
    ).fetchdf()


def load_body_measurement(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return the (single-row) body measurement table."""
    return con.execute(
        """
        SELECT user_id, height_meter, weight_kilogram, max_heart_rate, synced_at
        FROM body_measurement
        """
    ).fetchdf()


def load_cycles(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return all physiological cycles ("days"), oldest first."""
    return con.execute(
        """
        SELECT id, user_id, created_at, updated_at, "start", "end",
               timezone_offset, score_state, strain, kilojoule,
               average_heart_rate, max_heart_rate
        FROM cycles
        ORDER BY "start"
        """
    ).fetchdf()


def load_recovery(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return all recovery records, joined to their cycle's start date."""
    return con.execute(
        """
        SELECT r.cycle_id, r.sleep_id, r.user_id, r.created_at, r.updated_at,
               r.score_state, r.user_calibrating, r.recovery_score,
               r.resting_heart_rate, r.hrv_rmssd_milli, r.spo2_percentage,
               r.skin_temp_celsius, c."start" AS cycle_start
        FROM recovery r
        LEFT JOIN cycles c ON c.id = r.cycle_id
        ORDER BY c."start"
        """
    ).fetchdf()


def load_sleep(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return all sleep records, including naps."""
    return con.execute(
        """
        SELECT id, cycle_id, v1_id, user_id, created_at, updated_at,
               "start", "end", timezone_offset, nap, score_state,
               respiratory_rate, sleep_performance_percentage,
               sleep_consistency_percentage, sleep_efficiency_percentage,
               stage_summary, sleep_needed
        FROM sleep
        ORDER BY "start"
        """
    ).fetchdf()


def load_workouts(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return all workouts, oldest first."""
    return con.execute(
        """
        SELECT id, v1_id, user_id, created_at, updated_at, "start", "end",
               timezone_offset, sport_id, sport_name, score_state, strain,
               average_heart_rate, max_heart_rate, kilojoule,
               percent_recorded, distance_meter, altitude_gain_meter,
               altitude_change_meter, zone_durations
        FROM workouts
        ORDER BY "start"
        """
    ).fetchdf()


def load_daily_summary(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return one row per cycle, joined with that cycle's recovery + sleep scores.

    Naps are excluded from the sleep join so each cycle maps to at most
    one (main) sleep record. Handy for cross-metric comparisons -- e.g.
    strain vs. recovery -- without re-joining in every chart function.
    """
    return con.execute(
        """
        SELECT
            c.id AS cycle_id,
            c."start" AS cycle_start,
            c.score_state AS cycle_score_state,
            c.strain,
            c.average_heart_rate,
            c.max_heart_rate,
            r.recovery_score,
            r.resting_heart_rate,
            r.hrv_rmssd_milli,
            s.sleep_performance_percentage,
            s.sleep_consistency_percentage,
            s.sleep_efficiency_percentage,
            s.stage_summary
        FROM cycles c
        LEFT JOIN recovery r ON r.cycle_id = c.id
        LEFT JOIN sleep s ON s.cycle_id = c.id AND COALESCE(s.nap, FALSE) = FALSE
        ORDER BY c."start"
        """
    ).fetchdf()


def load_hr_broadcast_samples(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return all locally-captured live BLE HR Broadcast samples (see `thaalam.ble_stream`).

    Unlike the other tables here, this isn't synced from the WHOOP API --
    it's per-beat data captured directly over Bluetooth from the strap's
    official HR Broadcast feature, grouped by `session_id` per capture run.
    """
    return con.execute(
        """
        SELECT id, session_id, recorded_at, heart_rate, rr_intervals_ms,
               sensor_contact, energy_expended
        FROM hr_broadcast_samples
        ORDER BY recorded_at
        """
    ).fetchdf()
