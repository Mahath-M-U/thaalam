"""Unit tests for the deterministic rule-based daily insight brief.

Snapshots are hand-constructed (no DB) so each scenario isolates exactly the
rule(s) it's meant to exercise.
"""

from __future__ import annotations

from thaalam.services.brief_service import (
    BriefSnapshot,
    answer_explainer,
    compose_brief,
    evaluate_rules,
)


def _make_snapshot(**overrides) -> BriefSnapshot:
    base = dict(
        date="2026-08-01",
        recovery_score=70.0,
        recovery_zone="green",
        strain=10.0,
        hrv_ms=40.0,
        hrv_baseline_ms=40.0,
        hrv_delta_pct=0.0,
        rhr_bpm=55.0,
        rhr_baseline_bpm=55.0,
        rhr_delta_bpm=0.0,
        sleep_performance_pct=85.0,
        sleep_performance_baseline_pct=85.0,
        sleep_performance_delta_pct=0.0,
        respiratory_rate=15.0,
        respiratory_rate_baseline=15.0,
        respiratory_rate_delta=0.0,
        skin_temp_c=33.0,
        skin_temp_baseline_c=33.0,
        skin_temp_delta_c=0.0,
        acwr=1.0,
        strain_recovery_lag_corr=-0.1,
        sleep_recovery_corr=0.3,
        sleep_debt_hours=0.2,
        sleep_need_hours=8.0,
        sleep_actual_hours=7.8,
        current_streak_days=1,
        current_streak_zone="green",
        best_streak_days=5,
        zone_mix_pct={"red": 20.0, "yellow": 30.0, "green": 50.0},
        zone_mix_window={"start": "2026-07-01", "end": "2026-08-01"},
        behavioural_flag_text=None,
        generated_from_days=90,
    )
    base.update(overrides)
    return BriefSnapshot(**base)


def test_unremarkable_steady_state_day():
    snapshot = _make_snapshot(current_streak_days=1)
    text, rule_ids = compose_brief(snapshot)

    assert "illness_signature" not in rule_ids
    assert "acwr_high_risk" not in rule_ids
    assert "hrv_suppressed" not in rule_ids
    assert "sleep_debt_high" not in rule_ids
    # Low-severity "everything's normal" rules should carry the brief.
    assert "hrv_normal" in rule_ids
    assert "acwr_balanced" in rule_ids
    assert text != ""


def test_high_workload_ratio_day():
    snapshot = _make_snapshot(acwr=1.7)
    text, rule_ids = compose_brief(snapshot)

    assert "acwr_high_risk" in rule_ids
    assert "1.70" in text
    # High-risk band should suppress the lower-severity balanced/elevated bands.
    assert "acwr_balanced" not in rule_ids
    assert "acwr_elevated" not in rule_ids


def test_suppressed_hrv_day():
    snapshot = _make_snapshot(hrv_ms=30.0, hrv_baseline_ms=40.0, hrv_delta_pct=-25.0)
    text, rule_ids = compose_brief(snapshot)

    assert "hrv_suppressed" in rule_ids
    assert "hrv_normal" not in rule_ids
    assert "30" in text
    assert "40" in text


def test_illness_signature_day():
    snapshot = _make_snapshot(
        respiratory_rate=17.5,
        respiratory_rate_baseline=15.0,
        respiratory_rate_delta=2.5,
        skin_temp_c=34.0,
        skin_temp_baseline_c=33.0,
        skin_temp_delta_c=1.0,
        hrv_ms=30.0,
        hrv_baseline_ms=40.0,
        hrv_delta_pct=-25.0,
        rhr_bpm=62.0,
        rhr_baseline_bpm=55.0,
        rhr_delta_bpm=7.0,
    )
    triggered = {rule.id for rule in evaluate_rules(snapshot)}
    assert "illness_signature" in triggered

    text, rule_ids = compose_brief(snapshot)
    assert rule_ids[0] == "illness_signature"  # highest severity, always surfaced first
    lowered = text.lower()
    for word in ("flu", "cold", "sick", "illness", "infection", "virus", "disease"):
        assert word not in lowered


def test_high_sleep_debt_day():
    snapshot = _make_snapshot(sleep_debt_hours=2.3, sleep_need_hours=9.0, sleep_actual_hours=6.7)
    text, rule_ids = compose_brief(snapshot)

    assert "sleep_debt_high" in rule_ids
    assert "2.3" in text


def test_no_rules_triggered_returns_fallback():
    empty = _make_snapshot(
        acwr=None,
        hrv_delta_pct=None,
        sleep_debt_hours=None,
        current_streak_zone=None,
        current_streak_days=0,
        behavioural_flag_text=None,
    )
    text, rule_ids = compose_brief(empty)
    assert rule_ids == []
    assert "baseline" in text.lower()


def test_composition_prefers_category_variety():
    snapshot = _make_snapshot(
        acwr=1.7,  # load, sev 9
        hrv_ms=30.0,
        hrv_baseline_ms=40.0,
        hrv_delta_pct=-25.0,  # recovery, sev 7
        sleep_debt_hours=2.0,  # sleep, sev 6
        current_streak_zone="yellow",
        current_streak_days=4,  # trend, sev 5
    )
    _, rule_ids = compose_brief(snapshot, max_sentences=3)
    categories = {
        rule.category for rule in evaluate_rules(snapshot) if rule.id in rule_ids
    }
    assert len(categories) >= 3


def test_pushes_through_low_recovery_surfaces_flag_verbatim():
    flag_text = "On many sub-green days you still hit above-median strain."
    snapshot = _make_snapshot(behavioural_flag_text=flag_text)
    text, rule_ids = compose_brief(snapshot)
    assert "pushes_through_low_recovery" in rule_ids
    assert flag_text in text


def test_explainer_recovery_drivers_ranks_top_deviation():
    snapshot = _make_snapshot(
        hrv_ms=30.0,
        hrv_baseline_ms=40.0,
        hrv_delta_pct=-25.0,
        rhr_bpm=56.0,
        rhr_baseline_bpm=55.0,
        rhr_delta_bpm=1.0,
    )
    answer = answer_explainer(snapshot, "recovery_drivers")
    assert "HRV" in answer
    assert "30" in answer


def test_explainer_training_load_reports_band_and_distance():
    snapshot = _make_snapshot(acwr=1.4)
    answer = answer_explainer(snapshot, "training_load")
    assert "1.40" in answer
    assert "elevated" in answer


def test_explainer_sleep_debt_reports_hours_and_correlation():
    snapshot = _make_snapshot(sleep_debt_hours=1.8, sleep_need_hours=9.0, sleep_actual_hours=7.2, sleep_recovery_corr=0.4)
    answer = answer_explainer(snapshot, "sleep_debt")
    assert "1.8" in answer
    assert "0.40" in answer


def test_explainer_push_or_rest_combines_load_zone_and_streak():
    snapshot = _make_snapshot(acwr=0.9, recovery_zone="green", current_streak_zone="green", current_streak_days=3)
    answer = answer_explainer(snapshot, "push_or_rest")
    assert "0.90" in answer
    assert "green" in answer


def test_explainer_rejects_unknown_key():
    snapshot = _make_snapshot()
    try:
        answer_explainer(snapshot, "not_a_real_question")
        assert False, "expected ValueError"
    except ValueError:
        pass
