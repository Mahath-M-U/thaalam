"""Rule-based daily insight brief endpoints.

Deterministic only: composes an existing-metrics snapshot into a short brief
via `thaalam.services.brief_service`. No AI/LLM call, no outbound network
request of any kind.
"""

from __future__ import annotations

import logging
from typing import Any

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query

from thaalam.api.deps import get_readonly_connection, get_writable_connection
from thaalam.db import record_insight_brief
from thaalam.repositories import queries
from thaalam.services.brief_service import EXPLAINERS, answer_explainer, build_snapshot, compose_brief

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["brief"])


def _resolve_user_id(con: duckdb.DuckDBPyConnection, user_id: int | None) -> int | None:
    """This app is single-user/local; default to the one synced profile's user_id."""
    if user_id is not None:
        return user_id
    profile = queries.load_profile(con)
    if profile.empty:
        return None
    return int(profile.iloc[0]["user_id"])


@router.get("/brief")
def get_daily_brief(
    user_id: int | None = Query(default=None, description="Defaults to the synced WHOOP profile's user_id"),
    con: duckdb.DuckDBPyConnection = Depends(get_writable_connection),
) -> dict[str, Any]:
    """Composed daily brief text + the rule ids that fired, logged to `insight_briefs`."""
    snapshot = build_snapshot(con)
    if snapshot is None:
        return {
            "ready": False,
            "message": "Not enough data yet. Sync WHOOP history first.",
            "date": None,
            "brief": None,
            "rule_ids": [],
        }

    brief_text, rule_ids = compose_brief(snapshot)

    resolved_user_id = _resolve_user_id(con, user_id)
    if resolved_user_id is not None:
        record_insight_brief(con, resolved_user_id, snapshot.date, brief_text, rule_ids)

    return {"ready": True, "date": snapshot.date, "brief": brief_text, "rule_ids": rule_ids}


@router.get("/brief/explain")
def get_brief_explainer(
    question: str = Query(..., description=f"One of: {', '.join(EXPLAINERS)}"),
    user_id: int | None = Query(default=None, description="Defaults to the synced WHOOP profile's user_id"),
    con: duckdb.DuckDBPyConnection = Depends(get_readonly_connection),
) -> dict[str, Any]:
    """Answer one of the four fixed preset questions from the same snapshot."""
    if question not in EXPLAINERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown question key {question!r}. Must be one of: {', '.join(EXPLAINERS)}",
        )

    snapshot = build_snapshot(con)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Not enough data yet. Sync WHOOP history first.")

    question_text, _ = EXPLAINERS[question]
    return {
        "question_key": question,
        "question": question_text,
        "answer": answer_explainer(snapshot, question),
    }
