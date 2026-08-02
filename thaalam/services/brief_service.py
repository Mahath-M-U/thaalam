"""Deterministic, rule-based daily insight brief.

Synthesizes the metrics already computed in `thaalam.services.insights_service`
into a short plain-English brief plus four fixed explainer answers. There is
no AI/LLM involved and no network call: every sentence is produced by an
explicit rule (id, category, severity, condition, template) evaluated against
a `BriefSnapshot` built from already-stored/derived data. This is descriptive
local analytics only -- never a medical or diagnostic claim.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import duckdb
import pandas as pd

from thaalam import insights_thresholds as th
from thaalam.repositories import queries
from thaalam.services.insights_service import build_insights

_ROLLING_WINDOW_DAYS = 30
_ROLLING_MIN_PERIODS = 7


@dataclass
class BriefSnapshot:
    """Rounded, ready-to-render values for one user on one (latest synced) date."""

    date: str
    recovery_score: float | None
    recovery_zone: str | None
    strain: float | None
    hrv_ms: float | None
    hrv_baseline_ms: float | None
    hrv_delta_pct: float | None
    rhr_bpm: float | None
    rhr_baseline_bpm: float | None
    rhr_delta_bpm: float | None
    sleep_performance_pct: float | None
    sleep_performance_baseline_pct: float | None
    sleep_performance_delta_pct: float | None
    respiratory_rate: float | None
    respiratory_rate_baseline: float | None
    respiratory_rate_delta: float | None
    skin_temp_c: float | None
    skin_temp_baseline_c: float | None
    skin_temp_delta_c: float | None
    acwr: float | None
    strain_recovery_lag_corr: float | None
    sleep_recovery_corr: float | None
    sleep_debt_hours: float | None
    sleep_need_hours: float | None
    sleep_actual_hours: float | None
    current_streak_days: int
    current_streak_zone: str | None
    best_streak_days: int
    zone_mix_pct: dict[str, float]
    zone_mix_window: dict[str, str | None]
    behavioural_flag_text: str | None
    generated_from_days: int


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return round(f, 2)


def _zone(score: float | None) -> str | None:
    """Classify a recovery score into WHOOP-style red/yellow/green bands."""
    if score is None:
        return None
    if score < 34:
        return "red"
    if score < 67:
        return "yellow"
    return "green"


def _rolling_baseline_latest(
    daily_indexed: pd.DataFrame, col: str
) -> tuple[float | None, float | None, float | None]:
    """Latest value, 30-day baseline (mean of *prior* days), and their delta."""
    if col not in daily_indexed.columns:
        return None, None, None
    s = daily_indexed[col].dropna()
    if s.empty:
        return None, None, None
    current = _num(s.iloc[-1])
    baseline_series = s.shift(1).rolling(_ROLLING_WINDOW_DAYS, min_periods=_ROLLING_MIN_PERIODS).mean()
    baseline = baseline_series.iloc[-1] if not baseline_series.empty else None
    if baseline is None or baseline != baseline:
        return current, None, None
    baseline = _num(baseline)
    delta = round(current - baseline, 2) if current is not None and baseline is not None else None
    return current, baseline, delta


def _current_zone_streak(daily: pd.DataFrame) -> dict[str, Any] | None:
    """Current recovery-zone streak (length + zone) and the best historical run for that zone."""
    s = daily.dropna(subset=["recovery_score", "date"]).sort_values("date")
    if s.empty:
        return None

    zones = [_zone(v) for v in s["recovery_score"]]
    current_zone = zones[-1]

    current_streak = 0
    for z in reversed(zones):
        if z == current_zone:
            current_streak += 1
        else:
            break

    best = 0
    run = 0
    run_zone = None
    for z in zones:
        run = run + 1 if z == run_zone else 1
        run_zone = z
        if z == current_zone:
            best = max(best, run)

    return {"zone": current_zone, "current_streak": current_streak, "best_streak": best}


def build_snapshot(con: duckdb.DuckDBPyConnection) -> BriefSnapshot | None:
    """Assemble the single context snapshot the rule catalogue evaluates against."""
    insights = build_insights(con)
    if not insights.get("ready"):
        return None

    daily = queries.load_daily_summary(con).copy()
    daily["cycle_start"] = pd.to_datetime(daily["cycle_start"], errors="coerce", utc=True)
    daily = daily.dropna(subset=["cycle_start"]).sort_values("cycle_start")
    daily["date"] = daily["cycle_start"].dt.normalize()
    if daily.empty:
        return None

    indexed = daily.set_index("date").sort_index()
    latest = daily.iloc[-1]

    sections = insights.get("sections", {})
    hrv_latest = sections.get("hrv", {}).get("latest", {})
    rhr_latest = sections.get("rhr", {}).get("latest", {})
    load_latest = sections.get("training_load", {}).get("latest", {})
    lag = sections.get("strain_recovery_lag", {})
    sleep_corr = sections.get("sleep_recovery", {})
    debt_latest = sections.get("sleep_debt", {}).get("latest", {})
    zones = sections.get("recovery_zones", {})
    readiness = sections.get("training_readiness", {})

    sleep_perf_now, sleep_perf_base, sleep_perf_delta = _rolling_baseline_latest(
        indexed, "sleep_performance_percentage"
    )
    resp_now, resp_base, resp_delta = _rolling_baseline_latest(indexed, "respiratory_rate")
    skin_now, skin_base, skin_delta = _rolling_baseline_latest(indexed, "skin_temp_celsius")

    zone_streak = _current_zone_streak(daily) or {"zone": None, "current_streak": 0, "best_streak": 0}

    behavioural_flag_text = None
    readiness_card = readiness.get("card", {})
    if readiness_card.get("status") == "often pushes":
        behavioural_flag_text = readiness_card.get("detail")

    recovery_score = _num(latest.get("recovery_score"))

    return BriefSnapshot(
        date=daily["date"].max().date().isoformat(),
        recovery_score=recovery_score,
        recovery_zone=_zone(recovery_score),
        strain=_num(latest.get("strain")),
        hrv_ms=hrv_latest.get("hrv_ms"),
        hrv_baseline_ms=hrv_latest.get("baseline_ms"),
        hrv_delta_pct=hrv_latest.get("delta_pct"),
        rhr_bpm=rhr_latest.get("rhr_bpm"),
        rhr_baseline_bpm=rhr_latest.get("baseline_bpm"),
        rhr_delta_bpm=rhr_latest.get("delta_bpm"),
        sleep_performance_pct=sleep_perf_now,
        sleep_performance_baseline_pct=sleep_perf_base,
        sleep_performance_delta_pct=sleep_perf_delta,
        respiratory_rate=resp_now,
        respiratory_rate_baseline=resp_base,
        respiratory_rate_delta=resp_delta,
        skin_temp_c=skin_now,
        skin_temp_baseline_c=skin_base,
        skin_temp_delta_c=skin_delta,
        acwr=load_latest.get("acwr"),
        strain_recovery_lag_corr=lag.get("correlation"),
        sleep_recovery_corr=sleep_corr.get("correlation"),
        sleep_debt_hours=debt_latest.get("debt_hours"),
        sleep_need_hours=debt_latest.get("need_hours"),
        sleep_actual_hours=debt_latest.get("in_bed_hours"),
        current_streak_days=int(zone_streak.get("current_streak") or 0),
        current_streak_zone=zone_streak.get("zone"),
        best_streak_days=int(zone_streak.get("best_streak") or 0),
        zone_mix_pct=zones.get("percentages", {"red": 0, "yellow": 0, "green": 0}),
        zone_mix_window=insights.get("date_range", {"start": None, "end": None}),
        behavioural_flag_text=behavioural_flag_text,
        generated_from_days=int(insights.get("generated_from_days", 0)),
    )


# --------------------------------------------------------------------------
# Rule catalogue
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    severity: int
    condition: Callable[[BriefSnapshot], bool]
    template: Callable[[BriefSnapshot], str]


def _present(*values: Any) -> bool:
    return all(v is not None for v in values)


def _cond_illness_signature(s: BriefSnapshot) -> bool:
    if not _present(s.respiratory_rate_delta, s.skin_temp_delta_c, s.hrv_delta_pct, s.rhr_delta_bpm):
        return False
    return (
        s.respiratory_rate_delta >= th.RESPIRATORY_RATE_ELEVATION
        and s.skin_temp_delta_c >= th.SKIN_TEMP_ELEVATION_C
        and s.hrv_delta_pct <= th.HRV_SUPPRESSION_PCT
        and s.rhr_delta_bpm >= th.RHR_ELEVATION_BPM
    )


def _template_illness_signature(s: BriefSnapshot) -> str:
    return (
        f"Your respiratory rate ({s.respiratory_rate:.1f} vs {s.respiratory_rate_baseline:.1f} baseline), "
        f"skin temperature ({s.skin_temp_c:.1f}°C vs {s.skin_temp_baseline_c:.1f}°C baseline), HRV, and "
        "resting heart rate are all moving together in a pattern often linked to heavy fatigue or the "
        "body fighting something off -- extra rest, hydration, and keeping an eye on how you feel would "
        "be worthwhile."
    )


def _cond_acwr_high_risk(s: BriefSnapshot) -> bool:
    return s.acwr is not None and s.acwr >= th.ACWR_HIGH_RISK


def _template_acwr_high_risk(s: BriefSnapshot) -> str:
    return (
        f"Your training load ratio is {s.acwr:.2f}, at or above the {th.ACWR_HIGH_RISK:.1f} level often "
        "associated with higher injury risk -- an easier day would help bring it back down."
    )


def _cond_hrv_suppressed(s: BriefSnapshot) -> bool:
    return s.hrv_delta_pct is not None and s.hrv_delta_pct <= th.HRV_SUPPRESSION_PCT


def _template_hrv_suppressed(s: BriefSnapshot) -> str:
    return (
        f"HRV is {s.hrv_ms:.0f} ms today, {abs(s.hrv_delta_pct):.0f}% below your "
        f"{s.hrv_baseline_ms:.0f} ms baseline."
    )


def _cond_acwr_elevated(s: BriefSnapshot) -> bool:
    return s.acwr is not None and th.ACWR_ELEVATED <= s.acwr < th.ACWR_HIGH_RISK


def _template_acwr_elevated(s: BriefSnapshot) -> str:
    return (
        f"Your training load ratio is {s.acwr:.2f} -- trending high, though not yet in the "
        f"{th.ACWR_HIGH_RISK:.1f}+ higher-risk range."
    )


def _cond_sleep_debt_high(s: BriefSnapshot) -> bool:
    return s.sleep_debt_hours is not None and s.sleep_debt_hours >= th.SLEEP_DEBT_ALERT_HOURS


def _template_sleep_debt_high(s: BriefSnapshot) -> str:
    text = f"You're carrying about {s.sleep_debt_hours:.1f} hours of sleep debt"
    if s.sleep_recovery_corr is not None:
        text += (
            f", which matters more given the {s.sleep_recovery_corr:+.2f} correlation between your "
            "sleep performance and recovery."
        )
    else:
        text += "."
    return text


def _cond_zone_streak_down(s: BriefSnapshot) -> bool:
    return (
        s.current_streak_zone in ("yellow", "red")
        and s.current_streak_days >= th.NOTABLE_ZONE_STREAK_DAYS
    )


def _template_zone_streak_down(s: BriefSnapshot) -> str:
    return (
        f"You've had {s.current_streak_days} days in a row in the {s.current_streak_zone} recovery "
        "zone -- a lighter day or two could help reset."
    )


def _cond_pushes_through_low_recovery(s: BriefSnapshot) -> bool:
    return s.behavioural_flag_text is not None


def _template_pushes_through_low_recovery(s: BriefSnapshot) -> str:
    return s.behavioural_flag_text or ""


def _cond_zone_streak_green(s: BriefSnapshot) -> bool:
    return s.current_streak_zone == "green" and s.current_streak_days >= 2


def _template_zone_streak_green(s: BriefSnapshot) -> str:
    return (
        f"You're on a {s.current_streak_days}-day green recovery streak "
        f"(best on record: {s.best_streak_days})."
    )


def _cond_acwr_balanced(s: BriefSnapshot) -> bool:
    return s.acwr is not None and th.ACWR_LOW_BOUND <= s.acwr < th.ACWR_ELEVATED


def _template_acwr_balanced(s: BriefSnapshot) -> str:
    return f"Your training load ratio is {s.acwr:.2f}, sitting in the balanced range relative to your 4-week base."


def _cond_hrv_normal(s: BriefSnapshot) -> bool:
    return s.hrv_delta_pct is not None and s.hrv_delta_pct > th.HRV_SUPPRESSION_PCT


def _template_hrv_normal(s: BriefSnapshot) -> str:
    return f"HRV is {s.hrv_ms:.0f} ms today, close to your {s.hrv_baseline_ms:.0f} ms baseline."


RULES: list[Rule] = [
    Rule("illness_signature", "illness", 10, _cond_illness_signature, _template_illness_signature),
    Rule("acwr_high_risk", "load", 9, _cond_acwr_high_risk, _template_acwr_high_risk),
    Rule("hrv_suppressed", "recovery", 7, _cond_hrv_suppressed, _template_hrv_suppressed),
    Rule("acwr_elevated", "load", 6, _cond_acwr_elevated, _template_acwr_elevated),
    Rule("sleep_debt_high", "sleep", 6, _cond_sleep_debt_high, _template_sleep_debt_high),
    Rule("zone_streak_down", "trend", 5, _cond_zone_streak_down, _template_zone_streak_down),
    Rule(
        "pushes_through_low_recovery",
        "trend",
        4,
        _cond_pushes_through_low_recovery,
        _template_pushes_through_low_recovery,
    ),
    Rule("zone_streak_green", "trend", 3, _cond_zone_streak_green, _template_zone_streak_green),
    Rule("acwr_balanced", "load", 2, _cond_acwr_balanced, _template_acwr_balanced),
    Rule("hrv_normal", "recovery", 1, _cond_hrv_normal, _template_hrv_normal),
]

_FALLBACK_TEXT = "Your metrics are in line with your usual baseline today -- nothing notable to flag."


def evaluate_rules(snapshot: BriefSnapshot, rules: list[Rule] = RULES) -> list[Rule]:
    """Return every rule whose condition is true for this snapshot."""
    triggered = []
    for rule in rules:
        if rule.condition(snapshot):
            triggered.append(rule)
    return triggered


def compose_brief(snapshot: BriefSnapshot, max_sentences: int = 4) -> tuple[str, list[str]]:
    """Select up to `max_sentences` triggered rules (severity first, then category
    variety) and join their rendered sentences into a short paragraph."""
    triggered = evaluate_rules(snapshot)
    if not triggered:
        return _FALLBACK_TEXT, []

    triggered.sort(key=lambda r: -r.severity)

    selected: list[Rule] = []
    selected_ids: set[str] = set()
    used_categories: set[str] = set()

    # Pass 1: highest-severity rule per not-yet-used category, for variety.
    for rule in triggered:
        if len(selected) >= max_sentences:
            break
        if rule.category not in used_categories:
            selected.append(rule)
            selected_ids.add(rule.id)
            used_categories.add(rule.category)

    # Pass 2: fill any remaining slots with the next highest-severity rules.
    for rule in triggered:
        if len(selected) >= max_sentences:
            break
        if rule.id not in selected_ids:
            selected.append(rule)
            selected_ids.add(rule.id)

    selected.sort(key=lambda r: -r.severity)
    sentences = [rule.template(snapshot) for rule in selected]
    return " ".join(sentences), [rule.id for rule in selected]


# --------------------------------------------------------------------------
# Preset explainers
# --------------------------------------------------------------------------


def _explain_recovery_drivers(s: BriefSnapshot) -> str:
    if s.recovery_score is None:
        return "Recovery score isn't available yet for today."

    candidates: list[tuple[float, str]] = []
    if _present(s.hrv_delta_pct, s.hrv_ms, s.hrv_baseline_ms):
        candidates.append(
            (
                abs(s.hrv_delta_pct),
                f"HRV at {s.hrv_ms:.0f} ms ({s.hrv_delta_pct:+.0f}% vs your {s.hrv_baseline_ms:.0f} ms baseline)",
            )
        )
    if _present(s.rhr_delta_bpm, s.rhr_bpm, s.rhr_baseline_bpm):
        candidates.append(
            (
                abs(s.rhr_delta_bpm),
                f"resting heart rate at {s.rhr_bpm:.0f} bpm "
                f"({s.rhr_delta_bpm:+.1f} bpm vs your {s.rhr_baseline_bpm:.0f} bpm baseline)",
            )
        )
    if _present(s.sleep_performance_delta_pct, s.sleep_performance_pct, s.sleep_performance_baseline_pct):
        candidates.append(
            (
                abs(s.sleep_performance_delta_pct),
                f"sleep performance at {s.sleep_performance_pct:.0f}% "
                f"({s.sleep_performance_delta_pct:+.0f} pts vs your {s.sleep_performance_baseline_pct:.0f}% baseline)",
            )
        )

    if not candidates:
        return f"Recovery is {s.recovery_score:.0f} today, but there isn't enough baseline history yet to rank drivers."

    candidates.sort(key=lambda c: -c[0])
    top = [text for _, text in candidates[:2]]
    zone_txt = f" ({s.recovery_zone} zone)" if s.recovery_zone else ""
    return (
        f"Recovery is {s.recovery_score:.0f}{zone_txt} today; the biggest drivers vs your baselines are "
        + " and ".join(top)
        + "."
    )


def _explain_training_load(s: BriefSnapshot) -> str:
    if s.acwr is None:
        return "Not enough history yet to compute your training load ratio."

    if s.acwr >= th.ACWR_HIGH_RISK:
        band = "high-risk"
        dist_txt = f"{s.acwr - th.ACWR_HIGH_RISK:.2f} above the {th.ACWR_HIGH_RISK:.1f} high-risk threshold"
    elif s.acwr >= th.ACWR_ELEVATED:
        band = "elevated"
        dist_txt = f"{th.ACWR_HIGH_RISK - s.acwr:.2f} below the {th.ACWR_HIGH_RISK:.1f} high-risk threshold"
    elif s.acwr >= th.ACWR_LOW_BOUND:
        band = "balanced"
        dist_txt = f"{s.acwr - th.ACWR_LOW_BOUND:.2f} above the {th.ACWR_LOW_BOUND:.1f} balanced-range floor"
    else:
        band = "underloading"
        dist_txt = f"{th.ACWR_LOW_BOUND - s.acwr:.2f} below the {th.ACWR_LOW_BOUND:.1f} balanced-range floor"

    return f"Your training load ratio is {s.acwr:.2f}, which sits in the {band} band -- {dist_txt}."


def _explain_sleep_debt(s: BriefSnapshot) -> str:
    if s.sleep_debt_hours is None:
        return "No sleep-need/debt data available yet."

    parts = [f"You're carrying about {s.sleep_debt_hours:.1f} hours of sleep debt"]
    if s.sleep_need_hours is not None and s.sleep_actual_hours is not None:
        parts.append(f"against a need of {s.sleep_need_hours:.1f}h vs {s.sleep_actual_hours:.1f}h actually in bed")
    if s.sleep_recovery_corr is not None:
        parts.append(
            f"alongside a {s.sleep_recovery_corr:+.2f} correlation between sleep performance and recovery "
            "in your history"
        )
    return ", ".join(parts) + "."


def _explain_push_or_rest(s: BriefSnapshot) -> str:
    if s.acwr is None or s.recovery_zone is None:
        return "Not enough data yet to make a push/rest recommendation."

    if s.recovery_zone == "green" and s.acwr < th.ACWR_HIGH_RISK:
        recommendation = "a good day to push training as planned"
    elif s.recovery_zone == "red" or s.acwr >= th.ACWR_HIGH_RISK:
        recommendation = "a good day to take it easy"
    else:
        recommendation = "a fine day for moderate effort rather than a max push"

    streak_txt = ""
    if s.current_streak_zone and s.current_streak_days:
        streak_txt = f" You're {s.current_streak_days} day(s) into a {s.current_streak_zone} streak."

    return (
        f"With a training load ratio of {s.acwr:.2f} and recovery in the {s.recovery_zone} zone, "
        f"today looks like {recommendation}.{streak_txt}"
    )


EXPLAINERS: dict[str, tuple[str, Callable[[BriefSnapshot], str]]] = {
    "recovery_drivers": ("Why is my recovery at this level today?", _explain_recovery_drivers),
    "training_load": ("Am I training too much?", _explain_training_load),
    "sleep_debt": ("How is my sleep debt?", _explain_sleep_debt),
    "push_or_rest": ("Should I push hard today or take it easy?", _explain_push_or_rest),
}


def answer_explainer(snapshot: BriefSnapshot, key: str) -> str:
    """Answer one of the four fixed preset questions from `EXPLAINERS`. Raises
    `ValueError` for any key outside that fixed set."""
    if key not in EXPLAINERS:
        raise ValueError(f"Unknown explainer key: {key!r}. Must be one of: {', '.join(EXPLAINERS)}")
    _, fn = EXPLAINERS[key]
    return fn(snapshot)
