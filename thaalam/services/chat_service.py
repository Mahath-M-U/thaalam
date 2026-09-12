"""Turn a page-scoped question into a grounded answer.

Sits between the API route and `llm_client`: builds the prompt from
`chat_context`, rations requests per account, and normalises what comes back.
The route handles HTTP; this module owns the conversation.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock

import duckdb

from thaalam.config import get_settings
from thaalam.services import chat_context
from thaalam.services.llm_client import ChatUnavailable, complete

logger = logging.getLogger(__name__)

#: Roles a caller may send. The system prompt is ours, never theirs -- a
#: client-supplied system message would be the whole ballgame for prompt
#: injection, so the field is dropped rather than rejected.
_ALLOWED_ROLES = frozenset({"user", "assistant"})


@dataclass
class Turn:
    role: str
    content: str


@dataclass
class ChatAnswer:
    reply: str
    model: str
    page: str
    grounded_on: list[str]
    #: False when there is no synced history yet, so the UI can point at
    #: syncing rather than looking broken.
    ready: bool
    usage: dict


# ---------------------------------------------------------------------------
# Per-account rationing
# ---------------------------------------------------------------------------
#
# The free tier's allowance belongs to the API key, not to the person: 20
# requests a minute and 50 a day (1,000 once $10 of credits has ever been
# bought) across everyone sharing this deployment. Without a cap here, one
# user holding the send key spends the household's day in a minute.
#
# In-process, like `RateLimitMiddleware`, and correct for the same reason:
# this app runs a single worker because DuckDB allows one writer.

_history: dict[str, deque[float]] = {}
_history_lock = Lock()


class ChatThrottled(ChatUnavailable):
    """This account has used its share of the free allowance for now."""

    def __init__(self, retry_after: int) -> None:
        super().__init__(
            "You have reached this account's hourly limit for the assistant. "
            f"Try again in about {max(1, round(retry_after / 60))} minute(s).",
            status=429,
            retry_after=retry_after,
        )


def _check_quota(account: str) -> None:
    limit = get_settings().chat_requests_per_hour
    if limit <= 0:
        return
    window = 3600.0
    now = time.monotonic()
    with _history_lock:
        bucket = _history.setdefault(account, deque())
        while bucket and now - bucket[0] > window:
            bucket.popleft()
        if len(bucket) >= limit:
            raise ChatThrottled(retry_after=int(window - (now - bucket[0])) + 1)
        bucket.append(now)


def reset_quotas() -> None:
    """Forget per-account usage (tests)."""
    with _history_lock:
        _history.clear()


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------


def sanitise_turns(raw: list[Turn] | list[dict], *, max_chars: int) -> list[Turn]:
    """Keep the usable user/assistant turns, trimmed and bounded.

    Over-long turns are truncated rather than refused: a user who pastes a
    paragraph should get an answer about the start of it, not an error.
    """
    turns: list[Turn] = []
    for item in raw:
        role = (item.role if isinstance(item, Turn) else str(item.get("role", ""))).strip().lower()
        content = (item.content if isinstance(item, Turn) else str(item.get("content", ""))).strip()
        if role not in _ALLOWED_ROLES or not content:
            continue
        turns.append(Turn(role=role, content=content[:max_chars]))
    return turns


def build_messages(context: chat_context.ChatContext, turns: list[Turn]) -> list[dict[str, str]]:
    """The exact message array sent upstream.

    The grounding block travels as its own system message directly before the
    conversation, so the data stays adjacent to the question it answers rather
    than scrolling out of attention behind several turns of history.
    """
    return [
        {"role": "system", "content": chat_context.SYSTEM_PROMPT},
        {"role": "system", "content": f"DATA (this user's own, current):\n\n{context.text}"},
        *({"role": t.role, "content": t.content} for t in turns),
    ]


def answer(
    con: duckdb.DuckDBPyConnection | None,
    *,
    turns: list[Turn] | list[dict],
    account: str,
    page: str | None = None,
    read_id: str | None = None,
    range_days: int | None = None,
) -> ChatAnswer:
    """Answer the last turn in `turns`, grounded in what `page` is showing.

    Raises `ChatUnavailable` (which carries the HTTP status to use) when the
    assistant is unconfigured, throttled, or upstream cannot answer.
    """
    settings = get_settings()
    if not settings.chat_configured:
        raise ChatUnavailable(
            "The assistant is not configured on this server.",
            status=503,
        )

    cleaned = sanitise_turns(turns, max_chars=settings.chat_max_question_chars)
    if not cleaned or cleaned[-1].role != "user":
        raise ChatUnavailable("Ask a question to get an answer.", status=400)

    # Oldest turns fall off first; the newest question always survives.
    if len(cleaned) > settings.chat_history_messages:
        cleaned = cleaned[-settings.chat_history_messages :]

    _check_quota(account)

    context = chat_context.build_context(con, page=page, read_id=read_id, range_days=range_days)
    result = complete(build_messages(context, cleaned))

    logger.info(
        "Chat answered on page=%s model=%s grounded_on=%s",
        context.page,
        result.model,
        ",".join(context.grounded_on) or "none",
    )
    return ChatAnswer(
        reply=result.reply,
        model=result.model,
        page=context.page,
        grounded_on=context.grounded_on,
        ready=context.ready,
        usage=result.usage,
    )
