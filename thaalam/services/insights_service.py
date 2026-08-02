"""Derived insights from WHOOP daily metrics.

Goes beyond raw series charts. Metrics are grounded in common wearable /
sports-science practice (personalized baselines, rolling load, lag effects)
using only data already stored in DuckDB:

- HRV % vs 30-day baseline (single readings need personal context)
- RHR elevation vs baseline
- Acute:Chronic Workload Ratio on day strain (7d / 28d)
- Prior-day strain vs next-day recovery (lag relationship)
- Sleep performance vs same-day recovery correlation
- Weekday patterns, recovery-zone mix, green streaks
- Sleep debt / need breakdown when ``sleep_needed`` is present

These are descriptive local analytics, not medical or injury predictions.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from thaalam.repositories import queries

logger = logging.getLogger(__name__)

_MS_PER_HOUR = 3_600_000.0


def build_insights(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Compute the full insights payload for the dashboard."""
    daily = queries.load_daily_summary(con)
    sleep = queries.load_sleep(con)
    cycles = queries.load_cycles(con)
    workouts = queries.load_workouts(con)

    if daily.empty:
        return {
            "ready": False,
            "message": "Not enough data yet. Sync WHOOP history first.",
            "cards": [],
        }

    daily = daily.copy()
    daily["cycle_start"] = pd.to_datetime(daily["cycle_start"], errors="coerce", utc=True)
    daily = daily.dropna(subset=["cycle_start"]).sort_values("cycle_start")
    daily["date"] = daily["cycle_start"].dt.normalize()
    daily["weekday"] = daily["cycle_start"].dt.day_name()
    daily["weekday_num"] = daily["cycle_start"].dt.dayofweek

    cards: list[dict[str, Any]] = []
    sections: dict[str, Any] = {}

    hrv = _hrv_baseline_insights(daily)
    if hrv:
        sections["hrv"] = hrv
        cards.append(hrv["card"])

    rhr = _rhr_baseline_insights(daily)
    if rhr:
        sections["rhr"] = rhr
        cards.append(rhr["card"])

    load = _training_load_insights(daily)
    if load:
        sections["training_load"] = load
        cards.append(load["card"])

    lag = _strain_recovery_lag(daily)
    if lag:
        sections["strain_recovery_lag"] = lag
        cards.append(lag["card"])

    sleep_corr = _sleep_recovery_correlation(daily)
    if sleep_corr:
        sections["sleep_recovery"] = sleep_corr
        cards.append(sleep_corr["card"])

    zones = _recovery_zone_mix(daily)
    if zones:
        sections["recovery_zones"] = zones
        cards.append(zones["card"])

    weekdays = _weekday_patterns(daily)
    if weekdays:
        sections["weekday_patterns"] = weekdays

    streaks = _recovery_streaks(daily)
    if streaks:
        sections["streaks"] = streaks
        cards.append(streaks["card"])

    debt = _sleep_debt_insights(sleep)
    if debt:
        sections["sleep_debt"] = debt
        cards.append(debt["card"])

    series = _rolling_series(daily)
    if series:
        sections["rolling"] = series

    workout_timing = _high_strain_after_poor_recovery(daily, workouts)
    if workout_timing:
        sections["training_readiness"] = workout_timing
        cards.append(workout_timing["card"])

    return {
        "ready": True,
        "generated_from_days": int(len(daily)),
        "date_range": {
            "start": daily["date"].min().date().isoformat(),
            "end": daily["date"].max().date().isoformat(),
        },
        "cards": cards,
        "sections": sections,
        "disclaimer": (
            "Derived locally from your WHOOP history for exploration only — "
            "not medical advice or injury prediction."
        ),
    }


def _safe_corr(a: pd.Series, b: pd.Series) -> float | None:
    pair = pd.concat([a, b], axis=1).dropna()
    if len(pair) < 8:
        return None
    if pair.iloc[:, 0].std() == 0 or pair.iloc[:, 1].std() == 0:
        return None
    value = float(pair.iloc[:, 0].corr(pair.iloc[:, 1]))
    if value != value:  # NaN
        return None
    return round(value, 3)


def _pct_delta(current: float, baseline: float) -> float | None:
    if baseline == 0 or baseline != baseline or current != current:
        return None
    return round(100.0 * (current - baseline) / baseline, 1)


def _hrv_baseline_insights(daily: pd.DataFrame) -> dict[str, Any] | None:
    """HRV vs personalized 30-day baseline (rolling mean of prior days)."""
    s = daily.dropna(subset=["hrv_rmssd_milli", "date"]).copy()
    if len(s) < 7:
        return None

    s = s.set_index("date").sort_index()
    # Baseline = mean of previous up-to-30 days (exclude today)
    baseline = s["hrv_rmssd_milli"].shift(1).rolling(30, min_periods=7).mean()
    s["hrv_baseline"] = baseline
    s["hrv_delta_pct"] = (
        100.0 * (s["hrv_rmssd_milli"] - s["hrv_baseline"]) / s["hrv_baseline"]
    )

    latest = s.dropna(subset=["hrv_baseline"]).tail(1)
    if latest.empty:
        return None

    row = latest.iloc[0]
    current = float(row["hrv_rmssd_milli"])
    base = float(row["hrv_baseline"])
    delta = float(row["hrv_delta_pct"])

    if delta >= 15:
        status, tone, tip = (
            "elevated",
            "positive",
            "HRV is well above your baseline — often a sign you're primed for harder work.",
        )
    elif delta >= 10:
        status, tone, tip = (
            "above baseline",
            "positive",
            "HRV is meaningfully above your personal average.",
        )
    elif delta <= -15:
        status, tone, tip = (
            "suppressed",
            "caution",
            "HRV is well below baseline — consider easier training or extra recovery.",
        )
    elif delta <= -10:
        status, tone, tip = (
            "below baseline",
            "caution",
            "HRV is below your personal average; watch sleep and load.",
        )
    else:
        status, tone, tip = (
            "near baseline",
            "neutral",
            "HRV is close to your 30-day personal average.",
        )

    series = []
    for idx, r in s.dropna(subset=["hrv_baseline"]).iterrows():
        series.append(
            {
                "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10],
                "hrv": round(float(r["hrv_rmssd_milli"]), 2),
                "baseline": round(float(r["hrv_baseline"]), 2),
                "delta_pct": round(float(r["hrv_delta_pct"]), 1),
            }
        )

    card = {
        "id": "hrv_baseline",
        "title": "HRV vs personal baseline",
        "value": f"{delta:+.1f}%",
        "subtitle": f"{current:.0f} ms vs {base:.0f} ms (30d)",
        "status": status,
        "tone": tone,
        "detail": tip,
    }
    return {
        "card": card,
        "latest": {
            "hrv_ms": round(current, 2),
            "baseline_ms": round(base, 2),
            "delta_pct": round(delta, 1),
            "status": status,
        },
        "series": series[-90:],
    }


def _rhr_baseline_insights(daily: pd.DataFrame) -> dict[str, Any] | None:
    s = daily.dropna(subset=["resting_heart_rate", "date"]).copy()
    if len(s) < 7:
        return None

    s = s.set_index("date").sort_index()
    baseline = s["resting_heart_rate"].shift(1).rolling(30, min_periods=7).mean()
    s["rhr_baseline"] = baseline
    latest = s.dropna(subset=["rhr_baseline"]).tail(1)
    if latest.empty:
        return None

    row = latest.iloc[0]
    current = float(row["resting_heart_rate"])
    base = float(row["rhr_baseline"])
    delta_bpm = round(current - base, 1)
    # Higher RHR is generally worse (opposite of HRV)
    if delta_bpm >= 5:
        status, tone, tip = (
            "elevated",
            "caution",
            "Resting HR is elevated vs your baseline — common with fatigue, illness, or poor sleep.",
        )
    elif delta_bpm <= -3:
        status, tone, tip = (
            "lower than usual",
            "positive",
            "Resting HR is lower than your baseline — often a fitness/recovery positive.",
        )
    else:
        status, tone, tip = (
            "stable",
            "neutral",
            "Resting HR is close to your personal average.",
        )

    card = {
        "id": "rhr_baseline",
        "title": "RHR vs baseline",
        "value": f"{delta_bpm:+.1f} bpm",
        "subtitle": f"{current:.0f} vs {base:.0f} bpm (30d)",
        "status": status,
        "tone": tone,
        "detail": tip,
    }
    return {
        "card": card,
        "latest": {
            "rhr_bpm": round(current, 1),
            "baseline_bpm": round(base, 1),
            "delta_bpm": delta_bpm,
            "status": status,
        },
    }


def _training_load_insights(daily: pd.DataFrame) -> dict[str, Any] | None:
    """Acute (7d) vs chronic (28d) strain load — ACWR-style ratio."""
    s = daily.dropna(subset=["strain", "date"]).copy()
    if len(s) < 14:
        return None

    s = s.set_index("date").sort_index()
    # Sum of strain over windows; use trailing closed windows ending today
    acute = s["strain"].rolling(7, min_periods=5).sum()
    chronic_daily_avg = s["strain"].rolling(28, min_periods=14).mean()
    chronic = chronic_daily_avg * 7  # comparable 7-day equivalent load

    s["acute_load"] = acute
    s["chronic_load"] = chronic
    s["acwr"] = acute / chronic.replace(0, np.nan)

    latest = s.dropna(subset=["acwr"]).tail(1)
    if latest.empty:
        return None

    row = latest.iloc[0]
    acwr = float(row["acwr"])
    acute_v = float(row["acute_load"])
    chronic_v = float(row["chronic_load"])

    # Common interpretive bands (descriptive only)
    if acwr < 0.8:
        status, tone, tip = (
            "underloading",
            "neutral",
            "Recent load is below your chronic base — room to build, or deliberate deload.",
        )
    elif acwr <= 1.3:
        status, tone, tip = (
            "balanced",
            "positive",
            "Acute load sits in a commonly cited 'sweet spot' relative to your 4-week base.",
        )
    elif acwr <= 1.5:
        status, tone, tip = (
            "elevated",
            "caution",
            "Recent load is rising vs fitness base — watch recovery markers closely.",
        )
    else:
        status, tone, tip = (
            "spike",
            "caution",
            "Acute load is high vs chronic base — large spikes are often flagged as higher risk periods.",
        )

    series = []
    for idx, r in s.dropna(subset=["acwr"]).iterrows():
        series.append(
            {
                "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10],
                "acute_7d": round(float(r["acute_load"]), 2),
                "chronic_7d_eq": round(float(r["chronic_load"]), 2),
                "acwr": round(float(r["acwr"]), 3),
            }
        )

    card = {
        "id": "acwr",
        "title": "Training load ratio (ACWR)",
        "value": f"{acwr:.2f}",
        "subtitle": f"7d strain {acute_v:.1f} / chronic eq {chronic_v:.1f}",
        "status": status,
        "tone": tone,
        "detail": tip,
    }
    return {
        "card": card,
        "latest": {
            "acwr": round(acwr, 3),
            "acute_7d_strain": round(acute_v, 2),
            "chronic_7d_equivalent": round(chronic_v, 2),
            "status": status,
        },
        "bands": {
            "underload": "< 0.8",
            "sweet_spot": "0.8 – 1.3",
            "elevated": "1.3 – 1.5",
            "spike": "> 1.5",
        },
        "series": series[-90:],
    }


def _strain_recovery_lag(daily: pd.DataFrame) -> dict[str, Any] | None:
    """Does harder yesterday predict lower recovery today?"""
    s = daily.dropna(subset=["strain", "recovery_score"]).copy()
    if len(s) < 12:
        return None

    s = s.sort_values("date")
    s["prev_strain"] = s["strain"].shift(1)
    corr = _safe_corr(s["prev_strain"], s["recovery_score"])
    if corr is None:
        return None

    # Bucket prior strain and show mean next-day recovery
    s2 = s.dropna(subset=["prev_strain", "recovery_score"])
    try:
        s2 = s2.copy()
        s2["strain_bucket"] = pd.qcut(
            s2["prev_strain"], q=3, labels=["Low", "Medium", "High"], duplicates="drop"
        )
        buckets = (
            s2.groupby("strain_bucket", observed=True)["recovery_score"]
            .agg(["mean", "count"])
            .reset_index()
        )
        bucket_rows = [
            {
                "prior_strain": str(row["strain_bucket"]),
                "avg_next_recovery": round(float(row["mean"]), 1),
                "n": int(row["count"]),
            }
            for _, row in buckets.iterrows()
        ]
    except (ValueError, TypeError):
        bucket_rows = []

    if corr <= -0.25:
        tone, tip = (
            "caution",
            "Harder days tend to be followed by lower recovery — your lag effect is visible in the data.",
        )
    elif corr >= 0.15:
        tone, tip = (
            "neutral",
            "Higher prior strain does not clearly suppress next-day recovery in this sample.",
        )
    else:
        tone, tip = (
            "neutral",
            "Only a weak link between yesterday's strain and today's recovery — sleep/stress may dominate.",
        )

    card = {
        "id": "strain_recovery_lag",
        "title": "Yesterday's strain → recovery",
        "value": f"r = {corr:+.2f}",
        "subtitle": "Correlation (prior strain vs recovery)",
        "status": "lag effect" if corr <= -0.25 else "weak lag",
        "tone": tone,
        "detail": tip,
    }
    return {
        "card": card,
        "correlation": corr,
        "buckets": bucket_rows,
        "n_pairs": int(s2.shape[0]) if not s2.empty else 0,
    }


def _sleep_recovery_correlation(daily: pd.DataFrame) -> dict[str, Any] | None:
    s = daily.dropna(subset=["sleep_performance_percentage", "recovery_score"]).copy()
    if len(s) < 10:
        return None

    s = s.sort_values("date")
    corr = _safe_corr(s["sleep_performance_percentage"], s["recovery_score"])
    if corr is None:
        return None

    # Also compare efficiency / consistency when present
    corr_efficiency = _safe_corr(s["sleep_efficiency_percentage"], s["recovery_score"])
    corr_consistency = _safe_corr(s["sleep_consistency_percentage"], s["recovery_score"])

    # Top/bottom sleep nights → average recovery
    q_hi = s["sleep_performance_percentage"].quantile(0.75)
    q_lo = s["sleep_performance_percentage"].quantile(0.25)
    good_mask = s["sleep_performance_percentage"] >= q_hi
    poor_mask = s["sleep_performance_percentage"] <= q_lo
    good = s.loc[good_mask, "recovery_score"].mean()
    poor = s.loc[poor_mask, "recovery_score"].mean()
    mid = s.loc[~(good_mask | poor_mask), "recovery_score"].mean()
    recovery_gap = (
        round(float(good - poor), 1)
        if good == good and poor == poor
        else None
    )

    # Sleep performance buckets for comparison bar chart
    try:
        s2 = s.copy()
        s2["sleep_bucket"] = pd.qcut(
            s2["sleep_performance_percentage"],
            q=3,
            labels=["Poor", "Average", "Good"],
            duplicates="drop",
        )
        buckets = (
            s2.groupby("sleep_bucket", observed=True)
            .agg(
                avg_recovery=("recovery_score", "mean"),
                avg_sleep=("sleep_performance_percentage", "mean"),
                count=("recovery_score", "count"),
            )
            .reset_index()
        )
        bucket_rows = [
            {
                "sleep_quality": str(row["sleep_bucket"]),
                "avg_recovery": round(float(row["avg_recovery"]), 1),
                "avg_sleep_performance": round(float(row["avg_sleep"]), 1),
                "n": int(row["count"]),
            }
            for _, row in buckets.iterrows()
        ]
    except (ValueError, TypeError):
        bucket_rows = []

    # Scatter + dual time series for UI comparison charts
    scatter = []
    dual_series = []
    for _, row in s.iterrows():
        date_val = row["date"]
        date_str = (
            date_val.date().isoformat()
            if hasattr(date_val, "date")
            else str(date_val)[:10]
        )
        sleep_p = float(row["sleep_performance_percentage"])
        rec = float(row["recovery_score"])
        scatter.append(
            {
                "date": date_str,
                "sleep_performance": round(sleep_p, 1),
                "recovery_score": round(rec, 1),
                "sleep_efficiency": _num(row.get("sleep_efficiency_percentage")),
                "sleep_consistency": _num(row.get("sleep_consistency_percentage")),
            }
        )
        dual_series.append(
            {
                "date": date_str,
                "sleep_performance": round(sleep_p, 1),
                "recovery_score": round(rec, 1),
            }
        )

    if corr >= 0.3:
        tone, tip = (
            "positive",
            "Better sleep performance tracks with higher recovery — protect sleep on hard training weeks.",
        )
    elif corr <= 0.1:
        tone, tip = (
            "neutral",
            "Sleep performance and recovery are only loosely linked here; other factors may dominate.",
        )
    else:
        tone, tip = (
            "positive",
            "There is a modest positive link between sleep performance and recovery.",
        )

    card = {
        "id": "sleep_recovery",
        "title": "Sleep → recovery link",
        "value": f"r = {corr:+.2f}",
        "subtitle": (
            f"Avg recovery good sleep {good:.0f} vs poor {poor:.0f}"
            + (f" (Δ {recovery_gap:+.0f})" if recovery_gap is not None else "")
            if good == good and poor == poor
            else "Sleep performance vs recovery"
        ),
        "status": "coupled" if corr >= 0.3 else "modest",
        "tone": tone,
        "detail": tip,
    }
    return {
        "card": card,
        "correlation": corr,
        "correlation_sleep_efficiency": corr_efficiency,
        "correlation_sleep_consistency": corr_consistency,
        "avg_recovery_after_good_sleep": round(float(good), 1) if good == good else None,
        "avg_recovery_after_poor_sleep": round(float(poor), 1) if poor == poor else None,
        "avg_recovery_mid_sleep": round(float(mid), 1) if mid == mid else None,
        "recovery_gap_good_vs_poor": recovery_gap,
        "buckets": bucket_rows,
        "scatter": scatter[-120:],
        "dual_series": dual_series[-90:],
        "n_pairs": int(len(s)),
    }


def _recovery_zone_mix(daily: pd.DataFrame) -> dict[str, Any] | None:
    s = daily.dropna(subset=["recovery_score"])
    if s.empty:
        return None

    red = int((s["recovery_score"] < 34).sum())
    yellow = int(((s["recovery_score"] >= 34) & (s["recovery_score"] < 67)).sum())
    green = int((s["recovery_score"] >= 67).sum())
    total = red + yellow + green
    if total == 0:
        return None

    pct = lambda n: round(100.0 * n / total, 1)
    green_pct = pct(green)

    if green_pct >= 40:
        tone, tip = "positive", "A healthy share of days land in the green recovery band."
    elif green_pct < 20:
        tone, tip = "caution", "Few green days — consider sleep, stress, or reducing accumulated load."
    else:
        tone, tip = "neutral", "Most days sit in yellow; green days are less common."

    card = {
        "id": "recovery_zones",
        "title": "Recovery zone mix",
        "value": f"{green_pct:.0f}% green",
        "subtitle": f"{green} green · {yellow} yellow · {red} red ({total} days)",
        "status": "zone distribution",
        "tone": tone,
        "detail": tip,
    }
    return {
        "card": card,
        "counts": {"red": red, "yellow": yellow, "green": green, "total": total},
        "percentages": {"red": pct(red), "yellow": pct(yellow), "green": green_pct},
    }


def _weekday_patterns(daily: pd.DataFrame) -> dict[str, Any] | None:
    s = daily.dropna(subset=["weekday"])
    if len(s) < 14:
        return None

    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    rows = []
    for day in order:
        subset = s[s["weekday"] == day]
        if subset.empty:
            continue
        rows.append(
            {
                "weekday": day,
                "avg_recovery": _mean_round(subset["recovery_score"]),
                "avg_strain": _mean_round(subset["strain"]),
                "avg_sleep_performance": _mean_round(subset["sleep_performance_percentage"]),
                "n": int(len(subset)),
            }
        )
    if not rows:
        return None

    best_rec = max(
        (r for r in rows if r["avg_recovery"] is not None),
        key=lambda r: r["avg_recovery"] or 0,
        default=None,
    )
    hardest = max(
        (r for r in rows if r["avg_strain"] is not None),
        key=lambda r: r["avg_strain"] or 0,
        default=None,
    )
    return {
        "by_weekday": rows,
        "best_recovery_day": best_rec["weekday"] if best_rec else None,
        "hardest_strain_day": hardest["weekday"] if hardest else None,
    }


def _recovery_streaks(daily: pd.DataFrame) -> dict[str, Any] | None:
    s = daily.dropna(subset=["recovery_score", "date"]).sort_values("date")
    if s.empty:
        return None

    green = (s["recovery_score"] >= 67).astype(int).tolist()
    current = 0
    best = 0
    run = 0
    for g in green:
        if g:
            run += 1
            best = max(best, run)
        else:
            run = 0
    # current streak from the end
    for g in reversed(green):
        if g:
            current += 1
        else:
            break

    latest_score = float(s.iloc[-1]["recovery_score"])
    card = {
        "id": "green_streak",
        "title": "Green recovery streak",
        "value": str(current),
        "subtitle": f"Best streak: {best} days · latest {latest_score:.0f}",
        "status": "on streak" if current > 0 else "broken",
        "tone": "positive" if current >= 2 else "neutral",
        "detail": (
            f"You are on a {current}-day green streak (recovery ≥ 67)."
            if current
            else "No current green streak — best historical green run is "
            f"{best} day(s)."
        ),
    }
    return {
        "card": card,
        "current_green_streak": current,
        "best_green_streak": best,
        "latest_recovery": round(latest_score, 1),
    }


def _sleep_debt_insights(sleep: pd.DataFrame) -> dict[str, Any] | None:
    """Parse sleep_needed JSON for recent debt / need breakdown."""
    if sleep.empty or "sleep_needed" not in sleep.columns:
        return None

    rows = []
    for _, rec in sleep.iterrows():
        if rec.get("nap"):
            continue
        raw = rec.get("sleep_needed")
        if raw is None or (isinstance(raw, float) and raw != raw):
            continue
        try:
            needed = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(needed, dict):
            continue
        start = rec.get("start")
        in_bed = None
        stage_raw = rec.get("stage_summary")
        if stage_raw is not None and not (isinstance(stage_raw, float) and stage_raw != stage_raw):
            try:
                stage = json.loads(stage_raw) if isinstance(stage_raw, str) else stage_raw
                if isinstance(stage, dict) and stage.get("total_in_bed_time_milli"):
                    in_bed = stage["total_in_bed_time_milli"] / _MS_PER_HOUR
            except (TypeError, ValueError, json.JSONDecodeError):
                pass

        total_need = (
            (needed.get("baseline_milli") or 0)
            + (needed.get("need_from_sleep_debt_milli") or 0)
            + (needed.get("need_from_recent_strain_milli") or 0)
            + (needed.get("need_from_recent_nap_milli") or 0)
        ) / _MS_PER_HOUR
        debt_h = (needed.get("need_from_sleep_debt_milli") or 0) / _MS_PER_HOUR
        strain_need_h = (needed.get("need_from_recent_strain_milli") or 0) / _MS_PER_HOUR
        baseline_h = (needed.get("baseline_milli") or 0) / _MS_PER_HOUR

        rows.append(
            {
                "date": pd.to_datetime(start, utc=True, errors="coerce"),
                "need_hours": total_need,
                "debt_hours": debt_h,
                "strain_need_hours": strain_need_h,
                "baseline_hours": baseline_h,
                "in_bed_hours": in_bed,
                "sleep_performance": rec.get("sleep_performance_percentage"),
            }
        )

    if len(rows) < 3:
        return None

    df = pd.DataFrame(rows).dropna(subset=["date"]).sort_values("date")
    latest = df.iloc[-1]
    avg_debt = float(df["debt_hours"].tail(14).mean())
    latest_debt = float(latest["debt_hours"])
    latest_need = float(latest["need_hours"])
    latest_in_bed = latest["in_bed_hours"]
    gap = None
    if latest_in_bed == latest_in_bed and latest_need == latest_need:
        gap = round(float(latest_in_bed) - latest_need, 2)

    if latest_debt >= 1.0:
        tone, tip = (
            "caution",
            "Notable sleep debt is still stacked into your sleep need — prioritize longer nights.",
        )
    elif avg_debt >= 0.5:
        tone, tip = (
            "caution",
            "Recent average sleep debt is elevated across the last two weeks.",
        )
    else:
        tone, tip = (
            "positive",
            "Sleep debt contribution to need is relatively low recently.",
        )

    series = []
    for _, r in df.tail(60).iterrows():
        series.append(
            {
                "date": r["date"].date().isoformat(),
                "need_hours": round(float(r["need_hours"]), 2),
                "debt_hours": round(float(r["debt_hours"]), 2),
                "in_bed_hours": (
                    round(float(r["in_bed_hours"]), 2)
                    if r["in_bed_hours"] == r["in_bed_hours"]
                    else None
                ),
            }
        )

    card = {
        "id": "sleep_debt",
        "title": "Sleep debt / need",
        "value": f"{latest_debt:.1f}h debt",
        "subtitle": (
            f"Need {latest_need:.1f}h"
            + (f" · in bed {float(latest_in_bed):.1f}h" if latest_in_bed == latest_in_bed else "")
            + (f" · gap {gap:+.1f}h" if gap is not None else "")
        ),
        "status": "debt present" if latest_debt >= 0.5 else "debt low",
        "tone": tone,
        "detail": tip,
    }
    return {
        "card": card,
        "latest": {
            "debt_hours": round(latest_debt, 2),
            "need_hours": round(latest_need, 2),
            "baseline_hours": round(float(latest["baseline_hours"]), 2),
            "strain_need_hours": round(float(latest["strain_need_hours"]), 2),
            "in_bed_hours": round(float(latest_in_bed), 2) if latest_in_bed == latest_in_bed else None,
            "gap_hours": gap,
        },
        "avg_debt_14d": round(avg_debt, 2),
        "series": series,
    }


def _rolling_series(daily: pd.DataFrame) -> dict[str, Any] | None:
    s = daily.sort_values("date").copy()
    if len(s) < 7:
        return None

    out = []
    s = s.set_index("date")
    for col, key in [
        ("recovery_score", "recovery_7d"),
        ("strain", "strain_7d"),
        ("hrv_rmssd_milli", "hrv_7d"),
        ("sleep_performance_percentage", "sleep_7d"),
    ]:
        if col not in s.columns:
            continue
        s[key] = s[col].rolling(7, min_periods=3).mean()

    for idx, row in s.iterrows():
        out.append(
            {
                "date": idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10],
                "recovery": _num(row.get("recovery_score")),
                "recovery_7d": _num(row.get("recovery_7d")),
                "strain": _num(row.get("strain")),
                "strain_7d": _num(row.get("strain_7d")),
                "hrv": _num(row.get("hrv_rmssd_milli")),
                "hrv_7d": _num(row.get("hrv_7d")),
                "sleep": _num(row.get("sleep_performance_percentage")),
                "sleep_7d": _num(row.get("sleep_7d")),
            }
        )
    return {"series": out[-120:]}


def _high_strain_after_poor_recovery(
    daily: pd.DataFrame, workouts: pd.DataFrame
) -> dict[str, Any] | None:
    """How often high strain happens on red/yellow recovery days."""
    s = daily.dropna(subset=["recovery_score", "strain"]).copy()
    if len(s) < 10:
        return None

    poor = s["recovery_score"] < 67
    high_strain = s["strain"] >= s["strain"].median()
    risky = int((poor & high_strain).sum())
    poor_days = int(poor.sum())
    if poor_days == 0:
        return None

    rate = round(100.0 * risky / poor_days, 1)
    if rate >= 50:
        tone, tip = (
            "caution",
            "On many sub-green days you still hit above-median strain — consider dialing load when recovery is yellow/red.",
        )
    else:
        tone, tip = (
            "positive",
            "You often ease off when recovery is below green — a good load-management habit.",
        )

    card = {
        "id": "training_readiness",
        "title": "Load on low-recovery days",
        "value": f"{rate:.0f}%",
        "subtitle": f"{risky}/{poor_days} yellow/red days still had high strain",
        "status": "often pushes" if rate >= 50 else "usually eases",
        "tone": tone,
        "detail": tip,
    }

    # Optional workout count on poor recovery days
    workout_note = None
    if not workouts.empty and "start" in workouts.columns:
        w = workouts.copy()
        w["start"] = pd.to_datetime(w["start"], utc=True, errors="coerce")
        w = w.dropna(subset=["start"])
        w["date"] = w["start"].dt.normalize()
        poor_dates = set(s.loc[poor, "date"].dropna().tolist())
        if poor_dates:
            on_poor = w[w["date"].isin(poor_dates)]
            workout_note = {
                "workouts_on_poor_recovery_days": int(len(on_poor)),
                "avg_workout_strain_on_poor_days": _mean_round(on_poor["strain"])
                if "strain" in on_poor
                else None,
            }

    return {
        "card": card,
        "poor_recovery_days": poor_days,
        "high_strain_on_poor_days": risky,
        "rate_pct": rate,
        "workouts": workout_note,
    }


def _mean_round(series: pd.Series, digits: int = 1) -> float | None:
    s = series.dropna()
    if s.empty:
        return None
    return round(float(s.mean()), digits)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:
        return None
    return round(f, 2)
