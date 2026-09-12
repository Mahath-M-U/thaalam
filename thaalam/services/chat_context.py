"""Assemble what the assistant is allowed to know, scoped to one page.

The chat dock is reachable from every screen, and a question asked on the
Sleep page ("is this bad?") means something different from the same question
asked on the Strain page. So the client says *where* it was asked -- a page
key, and optionally which read is open -- and this module turns that into the
grounding block that leads the prompt.

Two decisions worth keeping:

**The client sends identifiers, never figures.** A page key and a read id, not
"HRV is 48ms". Every number in the prompt is read out of DuckDB here, so the
assistant cannot be talked into a false premise by a crafted request, and it
cannot repeat a stale value the browser happened to still be holding.

**The active page leads, but the rest still travels.** The page's own section
is rendered first and in full detail, then a compact whole-picture summary.
A question on the Sleep page usually needs sleep, but "does my training
explain this?" needs strain too, and a user should not have to know which tab
to stand on to get a straight answer.

Nothing here is a medical or diagnostic claim: it is descriptive statistics
over the user's own history, and the system prompt says so.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import duckdb

from thaalam.services.brief_service import BriefSnapshot, build_snapshot, compose_brief

logger = logging.getLogger(__name__)

#: Page keys the client may send. Anything else is treated as "overview",
#: because an unknown page should degrade to the whole picture rather than
#: 400 -- a new screen added to the frontend must not break chat on it.
PAGES: tuple[str, ...] = (
    "overview",
    "insights",
    "recovery",
    "strain",
    "sleep",
    "workouts",
    "reads",
    "read",
    "runway",
    "today",
    "admin",
)

#: Which insights sections lead for each page, in order. Everything not named
#: here still reaches the model through the summary block.
_PAGE_SECTIONS: dict[str, tuple[str, ...]] = {
    "overview": ("hrv", "rhr", "training_load", "sleep_debt"),
    "insights": (
        "hrv",
        "rhr",
        "training_load",
        "strain_recovery_lag",
        "sleep_recovery",
        "sleep_debt",
        "recovery_zones",
        "weekday_patterns",
        "training_readiness",
    ),
    "recovery": ("hrv", "rhr", "recovery_zones", "strain_recovery_lag"),
    "strain": ("training_load", "strain_recovery_lag", "training_readiness"),
    "sleep": ("sleep_debt", "sleep_recovery"),
    "workouts": ("training_load", "training_readiness", "strain_recovery_lag"),
    "today": ("hrv", "rhr", "training_load", "sleep_debt"),
    "runway": ("training_load", "sleep_debt", "recovery_zones"),
    "reads": (),
    "read": (),
    "admin": (),
}

#: What each page is, in the assistant's own words. Gives the model the frame
#: the user is sitting in rather than making it guess from the data.
_PAGE_DESCRIPTION: dict[str, str] = {
    "overview": "the dashboard overview: headline stats and the daily brief",
    "insights": "the Insights page: baseline comparisons and correlations",
    "recovery": "the Recovery page: recovery score, HRV and resting heart rate trends",
    "strain": "the Strain page: daily strain, training load ratio and strain-vs-recovery",
    "sleep": "the Sleep page: sleep duration, stages, performance and sleep debt",
    "workouts": "the Workouts page: session frequency and strain by sport",
    "reads": "the Reads list: the derived findings computed from this user's baseline",
    "read": "a single derived read, opened in detail",
    "runway": "the Runway view: how many days of current load the user's recovery supports",
    "today": "the mobile Today view: vitality score, the daily brief and top reads",
    "admin": "the administration screens (accounts, sessions, audit log, system status)",
}


def normalise_page(page: str | None) -> str:
    key = (page or "").strip().lower()
    return key if key in PAGES else "overview"


@dataclass
class ChatContext:
    """The grounding block, plus what went into it."""

    page: str
    text: str
    #: Human-readable list of the data actually included, returned to the
    #: client so the UI can show what an answer was based on.
    grounded_on: list[str]
    ready: bool


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt(value: Any, unit: str = "", digits: int = 1) -> str:
    if value is None:
        return "not available"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
        return f"{text}{unit}"
    return str(value)


def _line(label: str, value: Any, unit: str = "", digits: int = 1) -> str | None:
    """A `- label: value` line, or nothing when there is no value.

    Omitting absent metrics rather than printing "not available" for all of
    them keeps the prompt short and stops the model treating a gap as a
    finding. Genuinely important gaps are called out explicitly instead.
    """
    if value is None:
        return None
    return f"- {label}: {_fmt(value, unit, digits)}"


def _block(title: str, lines: list[str | None]) -> str:
    kept = [line for line in lines if line]
    if not kept:
        return ""
    return f"{title}\n" + "\n".join(kept)


def _snapshot_block(s: BriefSnapshot) -> str:
    return _block(
        f"TODAY ({s.date}), measured against this user's own rolling baselines:",
        [
            _line("Recovery score", s.recovery_score, "%", 0),
            _line("Recovery zone", s.recovery_zone),
            _line("Day strain", s.strain, "", 1),
            _line("HRV", s.hrv_ms, " ms", 0),
            _line("HRV baseline", s.hrv_baseline_ms, " ms", 0),
            _line("HRV vs baseline", s.hrv_delta_pct, "%", 0),
            _line("Resting heart rate", s.rhr_bpm, " bpm", 0),
            _line("RHR baseline", s.rhr_baseline_bpm, " bpm", 0),
            _line("RHR vs baseline", s.rhr_delta_bpm, " bpm", 1),
            _line("Sleep performance", s.sleep_performance_pct, "%", 0),
            _line("Sleep performance baseline", s.sleep_performance_baseline_pct, "%", 0),
            _line("Respiratory rate", s.respiratory_rate, " brpm", 1),
            _line("Respiratory rate baseline", s.respiratory_rate_baseline, " brpm", 1),
            _line("Skin temperature", s.skin_temp_c, " C", 1),
            _line("Skin temperature baseline", s.skin_temp_baseline_c, " C", 1),
            _line("Training load ratio (acute:chronic)", s.acwr, "", 2),
            _line("Sleep debt", s.sleep_debt_hours, " h", 1),
            _line("Sleep need", s.sleep_need_hours, " h", 1),
            _line("Sleep actually in bed", s.sleep_actual_hours, " h", 1),
            _line(
                "Current recovery-zone streak",
                f"{s.current_streak_days} day(s) {s.current_streak_zone}"
                if s.current_streak_zone
                else None,
            ),
            _line("Best streak in that zone", s.best_streak_days, " day(s)", 0),
            _line(
                "Correlation: sleep performance vs recovery",
                s.sleep_recovery_corr,
                "",
                2,
            ),
            _line(
                "Correlation: strain vs next-day recovery",
                s.strain_recovery_lag_corr,
                "",
                2,
            ),
            _line("History this is computed from", s.generated_from_days, " day(s)", 0),
        ],
    )


def _card_lines(section: dict[str, Any]) -> list[str | None]:
    """Render an insights section's own card, which is its plain-English verdict."""
    card = section.get("card") if isinstance(section, dict) else None
    if not isinstance(card, dict):
        return []
    bits = [card.get("title"), card.get("value"), card.get("status"), card.get("detail")]
    text = " -- ".join(str(b) for b in bits if b)
    return [f"- {text}"] if text else []


def _sections_block(insights: dict[str, Any], keys: tuple[str, ...]) -> str:
    sections = insights.get("sections") or {}
    lines: list[str | None] = []
    for key in keys:
        section = sections.get(key)
        if not isinstance(section, dict):
            continue
        lines.extend(_card_lines(section))
    return _block("WHAT THIS PAGE'S ANALYTICS CURRENTLY SAY:", lines)


def _reads_block(reads_payload: dict[str, Any], *, limit: int | None = None) -> str:
    reads = reads_payload.get("reads") if isinstance(reads_payload, dict) else None
    if not isinstance(reads, list) or not reads:
        return ""
    # Flagged reads first: those are the ones the dashboard itself highlights.
    ordered = sorted(reads, key=lambda r: (not r.get("flagged"), bool(r.get("calibrating"))))
    if limit:
        ordered = ordered[:limit]
    lines: list[str | None] = []
    for read in ordered:
        if not isinstance(read, dict):
            continue
        parts = [str(read.get("title") or read.get("id") or "")]
        if read.get("value") is not None:
            parts.append(_fmt(read.get("value"), str(read.get("unit") or ""), 2))
        if read.get("finding"):
            parts.append(str(read["finding"]))
        if read.get("calibrating"):
            parts.append("(still calibrating -- not enough nights yet)")
        elif read.get("flagged"):
            parts.append("(flagged)")
        lines.append("- " + " -- ".join(p for p in parts if p))
    return _block("DERIVED READS (computed from this user's own baseline):", lines)


def _read_detail_block(read_id: str, dive: dict[str, Any]) -> str:
    read = dive.get("read") if isinstance(dive, dict) else None
    detail = dive.get("dive") if isinstance(dive, dict) else None
    if not isinstance(read, dict):
        return ""
    lines: list[str | None] = [
        _line("Read", read.get("title") or read_id),
        _line("Finding", read.get("finding")),
        _line("Value", read.get("value"), str(read.get("unit") or ""), 2),
        _line("Change", read.get("delta"), "", 2),
        _line("Flagged", read.get("flagged")),
        _line("Still calibrating", read.get("calibrating")),
    ]
    if isinstance(detail, dict):
        for key in ("meaning", "focus", "dominant", "slope", "intercept"):
            if detail.get(key) is not None:
                lines.append(_line(key.replace("_", " ").capitalize(), detail[key], "", 3))
    return _block("THE READ THE USER HAS OPEN:", lines)


def _vitality_block(vitality: dict[str, Any]) -> str:
    if not isinstance(vitality, dict) or not vitality.get("present"):
        return ""
    lines: list[str | None] = [
        _line("Vitality score (0-1000)", vitality.get("score"), "", 0),
        _line("Band", vitality.get("band")),
        _line("Verdict", vitality.get("verdict")),
        _line("What is driving it", vitality.get("cause")),
        _line("14-day change", vitality.get("delta_14d"), "", 0),
    ]
    parts = vitality.get("parts")
    if isinstance(parts, list):
        for part in parts:
            if not isinstance(part, dict) or not part.get("name"):
                continue
            detail = (
                f"- Component {part['name']}: "
                f"{_fmt(part.get('pts'), '', 1)} of {_fmt(part.get('max_pts'), '', 1)} points"
            )
            if part.get("actual") is not None:
                detail += f" (measured {_fmt(part['actual'], str(part.get('unit') or ''), 1)})"
            if part.get("note"):
                detail += f" -- {part['note']}"
            lines.append(detail)
    return _block("VITALITY SCORE:", lines)


def _runway_block(runway: dict[str, Any]) -> str:
    if not isinstance(runway, dict) or not runway.get("present"):
        return ""
    lines: list[str | None] = [
        _line("Headline", runway.get("headline")),
        _line("Detail", runway.get("subtitle")),
        _line("Days of runway remaining", runway.get("days_remaining"), " day(s)", 0),
        _line("Recovery baseline it is measured against", runway.get("baseline"), "", 0),
        _line("Date the projection crosses that baseline", runway.get("baseline_break_date")),
        _line("Projection computed as of", runway.get("as_of")),
        _line("Still calibrating", runway.get("calibrating")),
    ]
    # What the projected decline is being spent on, when the payload carries it.
    spend = runway.get("spend")
    if isinstance(spend, list):
        for item in spend:
            if isinstance(item, dict) and item.get("label"):
                note = f" -- {item['note']}" if item.get("note") else ""
                lines.append(
                    f"- Where the decline comes from: {item['label']} "
                    f"{_fmt(item.get('pct'), '%', 0)}{note}"
                )
    return _block("RUNWAY (how long the current load is sustainable):", lines)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _safe(label: str, fn, default):
    """Run one context contributor, and let it fail without taking chat down.

    A single read that raises -- a half-migrated table, a stats edge case --
    should cost that block, not the answer.
    """
    try:
        return fn()
    except Exception:
        logger.warning("Chat context: %s unavailable", label, exc_info=True)
        return default


#: Said to the model instead of data when there is nothing to ground on, so
#: the reply is an instruction rather than an invention.
_NO_DATA = (
    "NO ANALYTICS ARE AVAILABLE YET: this account has not synced enough WHOOP "
    "history to compute baselines. Tell the user that plainly, and that "
    "connecting WHOOP and syncing history is what fixes it. Do not estimate "
    "or invent any values."
)


def build_context(
    con: duckdb.DuckDBPyConnection | None,
    *,
    page: str | None = None,
    read_id: str | None = None,
    range_days: int | None = None,
) -> ChatContext:
    """The grounding block for a question asked on `page`.

    `con` is None when no WHOOP database exists yet; the assistant still
    answers, but is told it has nothing to work from.
    """
    from thaalam.db import get_derived_runway
    from thaalam.services.insights_service import build_insights
    from thaalam.services.reads_service import READ_ORDER, get_read_dive_payload, get_reads_payload
    from thaalam.services.runway_service import compute_runway
    from thaalam.services.vitality_score import build_vitality_payload

    key = normalise_page(page)
    grounded_on: list[str] = []
    blocks: list[str] = []

    where = _PAGE_DESCRIPTION.get(key, _PAGE_DESCRIPTION["overview"])
    header = f"The user is currently looking at {where}."
    if range_days:
        header += f" The charts on screen are showing the last {range_days} days."
    blocks.append(header)

    snapshot = _safe("snapshot", lambda: build_snapshot(con), None) if con is not None else None
    if snapshot is None:
        # No usable history yet. Say so plainly instead of shipping an empty
        # prompt the model would fill with invention.
        blocks.append(_NO_DATA)
        return ChatContext(page=key, text="\n\n".join(blocks), grounded_on=[], ready=False)

    blocks.append(_snapshot_block(snapshot))
    grounded_on.append(f"today's metrics ({snapshot.date})")

    brief_text, _ = _safe("brief", lambda: compose_brief(snapshot), ("", []))
    if brief_text:
        blocks.append(f"TODAY'S RULE-BASED BRIEF (already shown to the user):\n{brief_text}")
        grounded_on.append("the daily brief")

    # The read the user opened is the most specific thing on screen, so it
    # goes above the page's sections.
    if key == "read" and read_id and read_id in READ_ORDER:
        dive = _safe("read dive", lambda: get_read_dive_payload(con, read_id), {})
        detail = _read_detail_block(read_id, dive)
        if detail:
            blocks.append(detail)
            grounded_on.append(f"the {read_id.replace('_', ' ')} read")

    insights = _safe("insights", lambda: build_insights(con), {})
    section_keys = _PAGE_SECTIONS.get(key, ())
    if section_keys:
        sections = _sections_block(insights, section_keys)
        if sections:
            blocks.append(sections)
            grounded_on.append(f"{key} analytics")

    if key in ("reads", "read", "overview", "today", "insights"):
        reads_payload = _safe("reads", lambda: get_reads_payload(con), {})
        reads = _reads_block(reads_payload, limit=None if key in ("reads", "read") else 6)
        if reads:
            blocks.append(reads)
            grounded_on.append("derived reads")

    if key in ("overview", "today", "insights"):
        vitality = _safe("vitality", lambda: build_vitality_payload(con), {})
        vit = _vitality_block(vitality)
        if vit:
            blocks.append(vit)
            grounded_on.append("vitality score")

    if key in ("runway", "overview", "today"):
        runway = _safe(
            "runway", lambda: get_derived_runway(con) or compute_runway(con), {}
        )
        run = _runway_block(runway)
        if run:
            blocks.append(run)
            grounded_on.append("runway")

    # Whole-picture tail, so a cross-cutting question still has the other
    # sections to reach for even when the page is narrow.
    if key not in ("insights",):
        rest = tuple(k for k in _PAGE_SECTIONS["insights"] if k not in section_keys)
        wider = _sections_block(insights, rest)
        if wider:
            blocks.append(wider.replace("WHAT THIS PAGE'S ANALYTICS", "THE REST OF THE ANALYTICS", 1))

    return ChatContext(
        page=key,
        text="\n\n".join(b for b in blocks if b),
        grounded_on=grounded_on,
        ready=True,
    )


# ---------------------------------------------------------------------------
# System prompt and starter questions
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are the assistant built into Thaalam, a personal WHOOP analytics \
dashboard. You are answering a question the user asked from a chat dock on a \
specific page of their own dashboard.

Ground rules:
1. Answer ONLY from the DATA block below. It is this user's real, current \
data, computed from their own history.
2. Never invent or estimate a number. If the data needed to answer is not in \
the block, say which metric is missing and what would produce it (usually \
syncing more WHOOP history).
3. Lead with the page the user is on. Their question is almost always about \
what is in front of them. Bring in other sections only when they genuinely \
explain it, and say when you do.
4. Quote the figures you use, with the baseline they are measured against -- \
"HRV 48 ms, 12% below your 55 ms baseline" beats "your HRV is low". A value \
only means something next to this user's own baseline.
5. Be short. Two to four sentences for a simple question; a few compact \
bullets when comparing several metrics. No preamble, no restating the \
question, no sign-off.
6. This is descriptive analytics on the user's own history, never medical \
advice, diagnosis, or treatment. You may describe what the numbers do and \
what is commonly associated with such patterns. Do not diagnose, and for \
anything that sounds clinical say plainly that it is worth raising with a \
clinician.
7. Plain text with '-' bullets. No markdown headings, no tables, no code \
blocks, no emoji.\
"""

#: Page-specific openers, so the dock offers something worth clicking wherever
#: it is opened. Deliberately answerable from that page's own context.
_SUGGESTIONS: dict[str, tuple[str, ...]] = {
    "overview": (
        "What stands out in my data today?",
        "Should I train hard today or take it easy?",
        "What is driving my recovery score right now?",
    ),
    "today": (
        "Summarise my day in two sentences.",
        "What is my vitality score telling me?",
        "Should I push today?",
    ),
    "insights": (
        "Which of these correlations actually matters for me?",
        "What has changed most against my baseline?",
        "Which number here should I act on first?",
    ),
    "recovery": (
        "Why is my recovery where it is today?",
        "Is my HRV trend normal for me?",
        "How does my resting heart rate compare to my baseline?",
    ),
    "strain": (
        "Is my training load too high right now?",
        "How does yesterday's strain show up in today's recovery?",
        "What would a sensible strain target be today?",
    ),
    "sleep": (
        "How bad is my sleep debt?",
        "Does my sleep actually predict my recovery?",
        "What would one extra hour of sleep be worth to me?",
    ),
    "workouts": (
        "Which sport costs me the most recovery?",
        "Am I training often enough to be progressing?",
        "Does my session frequency match my recovery?",
    ),
    "reads": (
        "Which of these reads should I care about most?",
        "Which reads are flagged, and why?",
        "What do the calibrating reads still need?",
    ),
    "read": (
        "What does this read actually mean for me?",
        "What would move this number?",
        "Is this normal for me or unusual?",
    ),
    "runway": (
        "What is limiting my runway right now?",
        "What would extend it?",
        "Can I sustain this week's load?",
    ),
    "admin": (
        "What stands out in my data today?",
        "Should I train hard today or take it easy?",
    ),
}


def suggestions_for(page: str | None) -> list[str]:
    key = normalise_page(page)
    return list(_SUGGESTIONS.get(key, _SUGGESTIONS["overview"]))
