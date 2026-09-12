"""Page scoping, and the guarantees the grounding block has to keep.

The claims being defended: the assistant is told which page it is answering
from, it is never handed a figure the client supplied, and with no data it is
told to say so rather than left to invent one.
"""

from __future__ import annotations

import pytest

from thaalam.services import chat_context
from thaalam.services.brief_service import BriefSnapshot


def _snapshot(**overrides) -> BriefSnapshot:
    base = dict(
        date="2026-09-11",
        recovery_score=41.0,
        recovery_zone="yellow",
        strain=12.4,
        hrv_ms=48.0,
        hrv_baseline_ms=55.0,
        hrv_delta_pct=-12.7,
        rhr_bpm=58.0,
        rhr_baseline_bpm=54.0,
        rhr_delta_bpm=4.0,
        sleep_performance_pct=72.0,
        sleep_performance_baseline_pct=85.0,
        sleep_performance_delta_pct=-13.0,
        respiratory_rate=15.1,
        respiratory_rate_baseline=14.4,
        respiratory_rate_delta=0.7,
        skin_temp_c=33.6,
        skin_temp_baseline_c=33.2,
        skin_temp_delta_c=0.4,
        acwr=1.42,
        strain_recovery_lag_corr=-0.38,
        sleep_recovery_corr=0.51,
        sleep_debt_hours=6.2,
        sleep_need_hours=8.4,
        sleep_actual_hours=6.9,
        current_streak_days=3,
        current_streak_zone="yellow",
        best_streak_days=9,
        zone_mix_pct={"red": 10.0, "yellow": 45.0, "green": 45.0},
        zone_mix_window={"start": "2026-06-01", "end": "2026-09-11"},
        behavioural_flag_text=None,
        generated_from_days=102,
    )
    base.update(overrides)
    return BriefSnapshot(**base)


# ---------------------------------------------------------------------------
# Page keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", chat_context.PAGES)
def test_every_advertised_page_survives_normalisation(page):
    """The list the API hands the client must be entirely usable."""
    assert chat_context.normalise_page(page) == page


@pytest.mark.parametrize("value", ["", None, "   ", "nonsense", "../etc/passwd", "SLEEP!"])
def test_an_unknown_page_degrades_to_the_overview(value):
    """A screen added to the frontend must not break chat before the backend
    catches up, and a crafted value must not reach a lookup."""
    assert chat_context.normalise_page(value) == "overview"


def test_page_keys_are_case_insensitive():
    assert chat_context.normalise_page("Sleep") == "sleep"


@pytest.mark.parametrize("page", chat_context.PAGES)
def test_every_page_offers_starter_questions(page):
    suggestions = chat_context.suggestions_for(page)
    assert suggestions, f"{page} offers nothing to click"
    assert all(q.strip().endswith("?") or q.strip().endswith(".") for q in suggestions)


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def test_no_database_tells_the_model_to_say_so(monkeypatch):
    """With nothing to ground on, the prompt must forbid inventing figures."""
    context = chat_context.build_context(None, page="sleep")
    assert context.ready is False
    assert context.grounded_on == []
    assert "NO ANALYTICS ARE AVAILABLE YET" in context.text
    assert "Do not estimate or invent any values" in context.text


def test_the_active_page_is_named_in_the_prompt(monkeypatch):
    monkeypatch.setattr(chat_context, "build_snapshot", lambda _con: None)
    context = chat_context.build_context(object(), page="strain", range_days=30)
    assert "Strain page" in context.text
    assert "last 30 days" in context.text


def test_todays_figures_and_their_baselines_both_reach_the_prompt(monkeypatch):
    """A value without the user's own baseline beside it means nothing, so
    both have to travel."""
    monkeypatch.setattr(chat_context, "build_snapshot", lambda _con: _snapshot())
    monkeypatch.setattr(
        chat_context, "compose_brief", lambda _s: ("HRV is below baseline.", ["hrv_suppressed"])
    )
    context = chat_context.build_context(_FakeCon(), page="recovery")

    assert context.ready is True
    assert "48 ms" in context.text and "55 ms" in context.text
    assert "58 bpm" in context.text and "54 bpm" in context.text
    assert "1.42" in context.text
    assert "2026-09-11" in context.text
    assert "HRV is below baseline." in context.text
    assert "today's metrics (2026-09-11)" in context.grounded_on


def test_absent_metrics_are_omitted_rather_than_reported_as_findings(monkeypatch):
    """Printing "not available" for every gap invites the model to treat a
    missing metric as a result."""
    monkeypatch.setattr(
        chat_context,
        "build_snapshot",
        lambda _con: _snapshot(acwr=None, sleep_debt_hours=None, skin_temp_c=None),
    )
    monkeypatch.setattr(chat_context, "compose_brief", lambda _s: ("", []))
    context = chat_context.build_context(_FakeCon(), page="strain")
    assert "not available" not in context.text
    assert "Training load ratio" not in context.text
    assert "Sleep debt" not in context.text


def test_one_failing_contributor_does_not_take_the_answer_down(monkeypatch):
    """A half-migrated table should cost its block, not the reply."""

    def _boom(_con):
        raise RuntimeError("derived_reads is missing")

    monkeypatch.setattr(chat_context, "build_snapshot", lambda _con: _snapshot())
    monkeypatch.setattr(chat_context, "compose_brief", lambda _s: ("Fine today.", []))
    monkeypatch.setattr(
        "thaalam.services.reads_service.get_reads_payload", _boom, raising=False
    )
    context = chat_context.build_context(_FakeCon(), page="overview")
    assert context.ready is True
    assert "48 ms" in context.text


def test_the_system_prompt_forbids_invention_and_medical_claims():
    """Two properties this feature is not allowed to ship without."""
    prompt = chat_context.SYSTEM_PROMPT
    assert "Never invent or estimate a number" in prompt
    assert "never medical" in prompt
    assert "ONLY from the DATA block" in prompt


class _FakeCon:
    """Stands in for a DuckDB cursor; the real reads are monkeypatched out."""

    def execute(self, *_args, **_kwargs):
        raise AssertionError("the context builder should not query directly")
