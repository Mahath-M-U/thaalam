"""Page-aware assistant endpoints, backed by a free OpenRouter model.

The dashboard's chat dock opens on every screen, so these routes take a page
key and answer from that page's analytics first. The grounding data is read
server-side from DuckDB -- the client sends only *where* it is asking from,
never figures -- so an answer cannot be steered onto a false premise by a
crafted request.

`/api/chat/status` exists so the frontend can hide the dock entirely when no
API key is configured, rather than offering a button that fails.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import duckdb
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from thaalam.api.deps import get_optional_readonly_connection, require_user
from thaalam.auth.sessions import AuthenticatedUser
from thaalam.config import get_settings
from thaalam.services import chat_context, chat_service
from thaalam.services.llm_client import ChatUnavailable

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"], dependencies=[Depends(require_user)])

#: Hard ceiling on turns accepted in one request, above the configured history
#: window, so an oversized body is refused before any of it is processed.
_MAX_TURNS = 40


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class ChatRequest(BaseModel):
    """A question, and which screen it was asked from.

    `page` is validated loosely on purpose: an unrecognised key degrades to
    the overview context, so adding a screen to the frontend cannot break
    chat on it before the backend catches up.
    """

    messages: list[ChatTurn] = Field(min_length=1, max_length=_MAX_TURNS)
    page: str | None = None
    #: Which derived read is open, when `page` is "read".
    read_id: str | None = Field(default=None, max_length=64)
    #: The range the charts on screen are showing, for wording only.
    range_days: int | None = Field(default=None, ge=1, le=3_650)


@router.get("/status")
def get_chat_status(
    _user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Whether the assistant can answer, and how it is configured.

    Deliberately says nothing about the key itself -- only whether one is
    present -- since any signed-in viewer may call this.
    """
    settings = get_settings()
    return {
        "enabled": settings.chat_configured,
        # "auto" is the normal answer: the model is chosen per request from
        # whatever is free at the time, so there is no single name to give.
        "model": settings.openrouter_model.strip() or "auto",
        "pages": list(chat_context.PAGES),
        "requests_per_hour": settings.chat_requests_per_hour,
    }


@router.get("/suggestions")
def get_chat_suggestions(
    page: str | None = Query(default=None, description="Page key the dock is open on"),
    _user: AuthenticatedUser = Depends(require_user),
) -> dict[str, Any]:
    """Starter questions for one page. Static, so it costs no model call."""
    key = chat_context.normalise_page(page)
    return {"page": key, "suggestions": chat_context.suggestions_for(key)}


@router.post("")
def post_chat(
    payload: ChatRequest,
    response: Response,
    user: AuthenticatedUser = Depends(require_user),
    con: duckdb.DuckDBPyConnection | None = Depends(get_optional_readonly_connection),
) -> dict[str, Any]:
    """Answer the latest question, grounded in the active page's analytics.

    A POST because it calls out to a paid-tier-limited service and consumes
    the account's allowance; that also puts it behind CSRF protection.
    """
    try:
        answer = chat_service.answer(
            con,
            turns=[chat_service.Turn(role=t.role, content=t.content) for t in payload.messages],
            account=user.email,
            page=payload.page,
            read_id=payload.read_id,
            range_days=payload.range_days,
        )
    except ChatUnavailable as exc:
        # The message is written for a user to read; the status says whether
        # waiting will help. Retry-After lets the dock say how long.
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status, detail=str(exc), headers=headers) from exc

    if not answer.ready:
        # Answered, but from an empty baseline -- the dock shows this as a
        # nudge to sync rather than as a failure.
        response.headers["X-Chat-Grounded"] = "false"

    return {
        "reply": answer.reply,
        "model": answer.model,
        "page": answer.page,
        "grounded_on": answer.grounded_on,
        "ready": answer.ready,
        "usage": answer.usage,
    }
