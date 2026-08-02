"""Repository layer: read-only query helpers over the WHOOP DuckDB database.

Exposes tidy `pandas.DataFrame` loaders per table (plus a joined daily
view) so analysis/visualization code never has to hand-write SQL.
"""

from thaalam.repositories.queries import (
    load_body_measurement,
    load_cycles,
    load_daily_summary,
    load_hr_broadcast_samples,
    load_profile,
    load_recovery,
    load_sleep,
    load_workouts,
)

__all__ = [
    "load_body_measurement",
    "load_cycles",
    "load_daily_summary",
    "load_hr_broadcast_samples",
    "load_profile",
    "load_recovery",
    "load_sleep",
    "load_workouts",
]
