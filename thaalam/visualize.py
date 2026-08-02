"""Chart-building functions for WHOOP metrics.

Each function takes a tidy DataFrame (see `thaalam.repositories.queries`)
and returns a base64-encoded PNG data URI, ready to drop straight into an
`<img src="...">` tag. That keeps the generated HTML report a single,
self-contained file with no separate image assets to manage or clean up.
"""

from __future__ import annotations

import base64
import io
import json
import logging

import matplotlib

matplotlib.use("Agg")  # headless: no display/GUI backend needed to save PNGs

import matplotlib.pyplot as plt
import pandas as pd

logger = logging.getLogger(__name__)

_RED = "#e2483d"
_YELLOW = "#ffde00"
_GREEN = "#3ddc84"
_BLUE = "#3d9be2"
_PURPLE = "#7c5cff"
_AMBER = "#ffb020"

# Shared, dashboard-like look for every chart: soft grid, muted axis chrome,
# and a system font stack so charts blend into the HTML report around them.
plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
        "font.size": 11,
        "axes.edgecolor": "#d0d5dd",
        "axes.labelcolor": "#344054",
        "text.color": "#344054",
        "xtick.color": "#667085",
        "ytick.color": "#667085",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "legend.frameon": False,
    }
)


def recovery_band_color(score: float) -> str:
    """Return the red/yellow/green brand color for a recovery score (0-100)."""
    if score < 34:
        return _RED
    if score < 67:
        return _YELLOW
    return _GREEN


def _style_axes(ax: plt.Axes, *, hide_spines: tuple[str, ...] = ("top", "right"), grid_axis: str = "y") -> None:
    """Strip chart-junk spines and add a subtle grid, consistent across charts."""
    for name in hide_spines:
        ax.spines[name].set_visible(False)
    ax.grid(True, axis=grid_axis, color="#e5e7eb", linewidth=0.8, linestyle="-", alpha=0.9)
    ax.set_axisbelow(True)


def _fig_to_data_uri(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close(fig)
    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _empty_chart(message: str) -> str:
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12, color="gray")
    ax.axis("off")
    return _fig_to_data_uri(fig)


def recovery_over_time(recovery_df: pd.DataFrame) -> str:
    """Recovery score over time, colored by red/yellow/green band."""
    df = recovery_df.dropna(subset=["recovery_score", "cycle_start"])
    if df.empty:
        return _empty_chart("No scored recovery data yet")

    colors = [recovery_band_color(score) for score in df["recovery_score"]]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["cycle_start"], df["recovery_score"], color="#d0d5dd", linewidth=1.5, zorder=2)
    ax.scatter(
        df["cycle_start"], df["recovery_score"], c=colors, s=30, zorder=3,
        edgecolors="white", linewidth=0.5,
    )
    ax.axhspan(0, 34, color=_RED, alpha=0.08)
    ax.axhspan(34, 67, color=_YELLOW, alpha=0.08)
    ax.axhspan(67, 100, color=_GREEN, alpha=0.08)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Recovery score")
    _style_axes(ax)
    fig.autofmt_xdate()
    return _fig_to_data_uri(fig)


def hrv_and_rhr_trends(recovery_df: pd.DataFrame) -> str:
    """HRV (ms) and resting heart rate (bpm) trends on twin axes."""
    df = recovery_df.dropna(subset=["cycle_start"])
    if df.empty or df["hrv_rmssd_milli"].dropna().empty:
        return _empty_chart("No HRV/resting heart rate data yet")

    fig, ax1 = plt.subplots(figsize=(10, 4))
    ax2 = ax1.twinx()
    ax1.plot(df["cycle_start"], df["hrv_rmssd_milli"], color=_GREEN, linewidth=2, label="HRV (ms)")
    ax2.plot(df["cycle_start"], df["resting_heart_rate"], color=_RED, linewidth=2, label="RHR (bpm)")
    ax1.set_ylabel("HRV (ms)", color=_GREEN)
    ax2.set_ylabel("Resting heart rate (bpm)", color=_RED)
    _style_axes(ax1, hide_spines=("top", "right"))
    ax2.spines["top"].set_visible(False)
    ax2.spines["left"].set_visible(False)
    ax2.tick_params(colors="#667085")
    fig.autofmt_xdate()
    return _fig_to_data_uri(fig)


def strain_over_time(cycles_df: pd.DataFrame) -> str:
    """Day strain over time."""
    df = cycles_df.dropna(subset=["strain", "start"])
    if df.empty:
        return _empty_chart("No scored strain data yet")

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(df["start"], df["strain"], color=_BLUE, linewidth=2, marker="o", markersize=3)
    ax.set_ylabel("Strain")
    _style_axes(ax)
    fig.autofmt_xdate()
    return _fig_to_data_uri(fig)


def strain_vs_recovery(daily_df: pd.DataFrame) -> str:
    """Scatter of day strain vs. same-day recovery score."""
    df = daily_df.dropna(subset=["strain", "recovery_score"])
    if df.empty:
        return _empty_chart("No overlapping strain/recovery data yet")

    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(df["recovery_score"], df["strain"], c=_BLUE, alpha=0.75, s=35, edgecolors="white", linewidth=0.5)
    ax.set_xlabel("Recovery score")
    ax.set_ylabel("Strain")
    _style_axes(ax)
    return _fig_to_data_uri(fig)


def sleep_trends(sleep_df: pd.DataFrame) -> str:
    """Sleep performance / efficiency / consistency trends."""
    df = sleep_df.dropna(subset=["start"])
    if df.empty:
        return _empty_chart("No sleep data yet")

    fig, ax = plt.subplots(figsize=(10, 4))
    series_specs = [
        ("sleep_performance_percentage", _BLUE, "Performance"),
        ("sleep_efficiency_percentage", _GREEN, "Efficiency"),
        ("sleep_consistency_percentage", _AMBER, "Consistency"),
    ]
    plotted = False
    for column, color, label in series_specs:
        series = df.dropna(subset=[column])
        if not series.empty:
            ax.plot(
                series["start"], series[column],
                marker="o", markersize=3, linewidth=2, color=color, label=label,
            )
            plotted = True
    if not plotted:
        plt.close(fig)
        return _empty_chart("No sleep performance/efficiency/consistency data yet")

    ax.set_ylabel("%")
    ax.set_ylim(0, 100)
    _style_axes(ax)
    ax.legend()
    fig.autofmt_xdate()
    return _fig_to_data_uri(fig)


def sleep_stage_breakdown(sleep_df: pd.DataFrame) -> str:
    """Average nightly time spent in each sleep stage, as a WHOOP-style donut."""
    stage_rows = []
    for raw in sleep_df["stage_summary"].dropna():
        try:
            stage_rows.append(json.loads(raw))
        except (TypeError, ValueError):
            continue
    if not stage_rows:
        return _empty_chart("No sleep stage data yet")

    stages_df = pd.DataFrame(stage_rows)
    hours_per_ms = 1 / 3_600_000
    labeled_fields = [
        ("Light", "total_light_sleep_time_milli", "#8ecae6"),
        ("Deep (SWS)", "total_slow_wave_sleep_time_milli", "#023047"),
        ("REM", "total_rem_sleep_time_milli", _PURPLE),
        ("Awake", "total_awake_time_milli", _AMBER),
    ]
    labels, values, colors = [], [], []
    for label, field, color in labeled_fields:
        if field not in stages_df:
            continue
        avg_hours = stages_df[field].mean() * hours_per_ms
        if avg_hours == avg_hours and avg_hours > 0:  # NaN != NaN
            labels.append(label)
            values.append(avg_hours)
            colors.append(color)
    if not values:
        return _empty_chart("No sleep stage data yet")

    fig, ax = plt.subplots(figsize=(6, 5))
    wedges, _ = ax.pie(
        values,
        colors=colors,
        startangle=90,
        counterclock=False,
        wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 2},
    )
    ax.legend(
        wedges,
        [f"{label} \u2013 {value:.1f}h" for label, value in zip(labels, values)],
        loc="center left",
        bbox_to_anchor=(1.0, 0.5),
    )
    total_hours = sum(values)
    ax.text(0, 0.08, f"{total_hours:.1f}h", ha="center", va="center", fontsize=20, fontweight="bold", color="#344054")
    ax.text(0, -0.14, "time in bed", ha="center", va="center", fontsize=10, color="#667085")
    ax.set_aspect("equal")
    return _fig_to_data_uri(fig)


def workout_strain_by_sport(workouts_df: pd.DataFrame) -> str:
    """Average workout strain grouped by sport."""
    df = workouts_df.dropna(subset=["strain", "sport_name"])
    if df.empty:
        return _empty_chart("No scored workout data yet")

    by_sport = df.groupby("sport_name")["strain"].mean().sort_values(ascending=True)
    fig, ax = plt.subplots(figsize=(8, max(3, 0.4 * len(by_sport))))
    ax.barh(by_sport.index, by_sport.to_numpy(), color=_BLUE)
    ax.set_xlabel("Average strain")
    _style_axes(ax, grid_axis="x")
    return _fig_to_data_uri(fig)


def workout_frequency_over_time(workouts_df: pd.DataFrame) -> str:
    """Workout count per week over time."""
    df = workouts_df.dropna(subset=["start"])
    if df.empty:
        return _empty_chart("No workout data yet")

    weekly = df.set_index("start").resample("W").size()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(weekly.index, weekly.to_numpy(), width=5, color=_BLUE)
    ax.set_ylabel("Workouts per week")
    _style_axes(ax)
    fig.autofmt_xdate()
    return _fig_to_data_uri(fig)
