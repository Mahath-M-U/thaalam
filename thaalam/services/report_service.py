"""Service layer: turn repository DataFrames into report-ready content.

Sits between `thaalam.repositories` (pure DB access, no business logic)
and `thaalam.report` (I/O: DB connection lifecycle + template rendering).
This module owns the domain logic of *what* a report contains -- which
DataFrames it needs, which charts to build from them, and which headline
numbers to summarize -- so neither of the other two layers has to.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import duckdb
import pandas as pd

from thaalam import visualize
from thaalam.repositories import queries

logger = logging.getLogger(__name__)


@dataclass
class ReportData:
    """Tidy DataFrames for a single report run, loaded via the repositories layer."""

    cycles: pd.DataFrame
    recovery: pd.DataFrame
    sleep: pd.DataFrame
    workouts: pd.DataFrame
    daily: pd.DataFrame


def load_report_data(con: duckdb.DuckDBPyConnection) -> ReportData:
    """Load every DataFrame the report needs via the repositories layer."""
    data = ReportData(
        cycles=queries.load_cycles(con),
        recovery=queries.load_recovery(con),
        sleep=queries.load_sleep(con),
        workouts=queries.load_workouts(con),
        daily=queries.load_daily_summary(con),
    )
    logger.info(
        "Loaded %d cycle(s), %d recovery record(s), %d sleep record(s), %d workout(s)",
        len(data.cycles), len(data.recovery), len(data.sleep), len(data.workouts),
    )
    return data


def _format_stat(value: float | None, suffix: str = "") -> str:
    return f"{value:.1f}{suffix}" if value is not None and value == value else "N/A"  # NaN != NaN


# Accent colors for the summary/category cards -- kept local to this (presentation)
# layer rather than reaching into visualize's internals, even though a couple of
# values intentionally match visualize's own palette for a consistent look.
_SLATE = "#64748b"
_BLUE = "#3d9be2"
_PURPLE = "#7c5cff"
_GREEN = "#3ddc84"
_AMBER = "#ffb020"


def build_summary_stats(data: ReportData) -> list[dict[str, str]]:
    """Headline numbers shown at the top of the report, each tagged with an
    accent color so the card grid reads like a dashboard -- the recovery card
    even matches the live red/yellow/green band from the recovery chart."""
    avg_recovery = data.recovery["recovery_score"].dropna().mean() if not data.recovery.empty else None
    avg_strain = data.cycles["strain"].dropna().mean() if not data.cycles.empty else None
    avg_sleep_perf = (
        data.sleep["sleep_performance_percentage"].dropna().mean() if not data.sleep.empty else None
    )
    recovery_accent = (
        visualize.recovery_band_color(avg_recovery)
        if avg_recovery is not None and avg_recovery == avg_recovery  # NaN != NaN
        else _SLATE
    )
    return [
        {"label": "Cycles tracked", "value": str(len(data.cycles)), "accent": _SLATE},
        {"label": "Sleep records", "value": str(len(data.sleep)), "accent": _PURPLE},
        {"label": "Workouts logged", "value": str(len(data.workouts)), "accent": _BLUE},
        {"label": "Avg recovery score", "value": _format_stat(avg_recovery), "accent": recovery_accent},
        {"label": "Avg day strain", "value": _format_stat(avg_strain), "accent": _BLUE},
        {"label": "Avg sleep performance", "value": _format_stat(avg_sleep_perf, "%"), "accent": _PURPLE},
    ]


def build_charts(data: ReportData) -> list[dict[str, object]]:
    """Chart definitions grouped by theme for the report template.

    Each group carries a `category` heading and matching `accent` color plus
    a `charts` list of {title, description, image} -- mirrors how WHOOP's own
    app separates Recovery/Sleep/Strain into distinct sections instead of one
    long undifferentiated feed of charts.
    """
    return [
        {
            "category": "Recovery",
            "accent": _GREEN,
            "charts": [
                {
                    "title": "Recovery Score Over Time",
                    "description": "Daily recovery score (0-100), colored by red/yellow/green band.",
                    "image": visualize.recovery_over_time(data.recovery),
                },
                {
                    "title": "HRV & Resting Heart Rate Trends",
                    "description": "Heart rate variability (ms) and resting heart rate (bpm) over time.",
                    "image": visualize.hrv_and_rhr_trends(data.recovery),
                },
            ],
        },
        {
            "category": "Strain",
            "accent": _BLUE,
            "charts": [
                {
                    "title": "Day Strain Over Time",
                    "description": "WHOOP's daily strain score per cycle.",
                    "image": visualize.strain_over_time(data.cycles),
                },
                {
                    "title": "Strain vs. Recovery",
                    "description": "Same-day strain plotted against recovery score.",
                    "image": visualize.strain_vs_recovery(data.daily),
                },
            ],
        },
        {
            "category": "Sleep",
            "accent": _PURPLE,
            "charts": [
                {
                    "title": "Sleep Performance, Efficiency & Consistency",
                    "description": "Key sleep quality percentages over time.",
                    "image": visualize.sleep_trends(data.sleep),
                },
                {
                    "title": "Average Sleep Stage Breakdown",
                    "description": "Average nightly time in bed, split by sleep stage.",
                    "image": visualize.sleep_stage_breakdown(data.sleep),
                },
            ],
        },
        {
            "category": "Workouts",
            "accent": _AMBER,
            "charts": [
                {
                    "title": "Average Workout Strain by Sport",
                    "description": "Mean strain score grouped by sport/activity type.",
                    "image": visualize.workout_strain_by_sport(data.workouts),
                },
                {
                    "title": "Workout Frequency Over Time",
                    "description": "Number of workouts logged per week.",
                    "image": visualize.workout_frequency_over_time(data.workouts),
                },
            ],
        },
    ]
