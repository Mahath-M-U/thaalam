"""OpenRouter chat-completions client, restricted to the free model tier.

This is the only place in the application that makes an outbound AI call.
Everything above it (`services.chat_service`) hands over already-assembled
messages; everything below it is OpenRouter's OpenAI-compatible HTTP surface:

    POST {base_url}/chat/completions
    Authorization: Bearer <OPENROUTER_API_KEY>

Two things about the free tier drive the design here.

**The roster rotates.** Which slugs are free is decided by the upstream
providers, not by OpenRouter, and models are added, pulled and repriced
continuously. A slug hardcoded at development time is a 404 some weeks later.
So the client asks `GET /models` which ones are free *right now* (price 0 for
both prompt and completion), ranks them, and caches the answer. `MODEL_
PREFERENCE` only expresses taste over that live list; `FALLBACK_MODELS` is the
last resort for when the catalogue itself cannot be reached.

**The budget is small and shared.** Free models allow 20 requests/minute, and
50 requests/day until an account has bought $10 of credits at some point
(then 1,000). Every request therefore matters: the caller is throttled per
account upstream of this module, and a model that answers with 429 or "no
longer available" is retired from this process's rotation and the next
candidate is tried, so one dead slug doesn't take the feature down.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import requests

from thaalam.config import get_settings

logger = logging.getLogger(__name__)

#: Ranked substrings, best first. Matched against a live free-model slug, so
#: this survives version bumps (`llama-3.3` -> `llama-4`) without edits: the
#: family name is the durable part, and anything unlisted still ranks below
#: these rather than being excluded.
#:
#: Ordered for this application's actual job -- reading a page of health
#: analytics and answering a specific question about it in a few sentences.
#: That rewards instruction-following and long context over raw code ability,
#: so the large general instruct models lead.
MODEL_PREFERENCE: tuple[str, ...] = (
    "deepseek",
    "llama-4",
    "llama-3.3",
    "qwen3",
    "qwen-2.5",
    "gpt-oss",
    "mistral-small",
    "gemma-3",
    "gemma-2",
    "phi-4",
)

#: Used only when `GET /models` cannot be reached, so the assistant still has
#: something to try. Any of these may have been retired upstream -- the client
#: walks the list, so a 404 on the first costs one request, not the feature.
FALLBACK_MODELS: tuple[str, ...] = (
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen-2.5-72b-instruct:free",
    "google/gemma-2-9b-it:free",
)

#: How long a discovered free-model list is trusted. Long enough that a chatty
#: afternoon costs one catalogue fetch, short enough to pick up a rotation.
_MODEL_CACHE_TTL_SECONDS = 6 * 60 * 60

#: A model that answers "gone" or "rate limited" is skipped for this long
#: rather than permanently, since free-tier 429s clear on their own.
_MODEL_COOLDOWN_SECONDS = 15 * 60

#: Smallest context window worth offering. The grounding block for a page of
#: analytics plus a few turns of history does not fit in 4k.
_MIN_CONTEXT_TOKENS = 8_000

#: How many candidates one question may try before giving up. Keeps a bad
#: roster from spending the daily budget on retries.
_MAX_ATTEMPTS = 3


class ChatUnavailable(RuntimeError):
    """The assistant cannot answer, with a reason safe to show a user.

    `status` is what the API route should return: 503 when the feature is off
    or upstream is down, 429 when the free tier is exhausted.
    """

    def __init__(self, message: str, *, status: int = 503, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass
class ChatResult:
    """One model reply, plus what it took to get it."""

    reply: str
    model: str
    #: Slugs tried and rejected before the one that answered. Logged, and
    #: surfaced in dev, because "which free model actually served this" is
    #: otherwise unanswerable after the fact.
    attempted: list[str] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Model discovery
# ---------------------------------------------------------------------------


@dataclass
class _ModelCache:
    slugs: tuple[str, ...] = ()
    fetched_at: float = 0.0


_cache = _ModelCache()
_cache_lock = Lock()

#: slug -> unix time at which it may be tried again.
_cooldowns: dict[str, float] = {}
_cooldown_lock = Lock()


def _is_free(model: dict[str, Any]) -> bool:
    """Whether both directions of this model cost nothing.

    OpenRouter reports prices as decimal *strings* ("0", "0.0000001"), so this
    compares numerically -- `"0.0" == "0"` is false, and a truthiness check on
    the string would call every priced model free.
    """
    pricing = model.get("pricing") or {}
    for key in ("prompt", "completion"):
        try:
            if float(pricing.get(key, 1)) > 0:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _preference_rank(slug: str) -> int:
    lowered = slug.lower()
    for index, family in enumerate(MODEL_PREFERENCE):
        if family in lowered:
            return index
    return len(MODEL_PREFERENCE)


def _rank_models(models: list[dict[str, Any]]) -> tuple[str, ...]:
    """Free, roomy models, best first."""
    scored: list[tuple[int, int, str]] = []
    for model in models:
        slug = str(model.get("id") or "")
        if not slug or not _is_free(model):
            continue
        try:
            context = int(model.get("context_length") or 0)
        except (TypeError, ValueError):
            context = 0
        if context and context < _MIN_CONTEXT_TOKENS:
            continue
        # Preference first, then the largest context inside that family, so a
        # question about a long page is less likely to be truncated.
        scored.append((_preference_rank(slug), -context, slug))
    scored.sort()
    return tuple(slug for _, _, slug in scored)


def _fetch_free_models(session: requests.Session, settings: Any) -> tuple[str, ...]:
    """Ask OpenRouter which models are free right now.

    Unauthenticated on OpenRouter's side, but the key is sent anyway so the
    catalogue reflects anything specific to this account.
    """
    url = f"{settings.openrouter_base_url.rstrip('/')}/models"
    response = session.get(url, headers=_headers(settings), timeout=15)
    response.raise_for_status()
    payload = response.json()
    models = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(models, list):
        return ()
    return _rank_models([m for m in models if isinstance(m, dict)])


def available_models(session: requests.Session | None = None) -> tuple[str, ...]:
    """Candidate slugs, best first: the pinned model, or the live free list.

    Never raises: a catalogue that cannot be reached degrades to
    `FALLBACK_MODELS` rather than taking the assistant down with it.
    """
    settings = get_settings()

    pinned = settings.openrouter_model.strip()
    if pinned:
        return (pinned,)

    now = time.monotonic()
    with _cache_lock:
        if _cache.slugs and (now - _cache.fetched_at) < _MODEL_CACHE_TTL_SECONDS:
            return _cache.slugs

    owned_session = session is None
    session = session or requests.Session()
    try:
        slugs = _fetch_free_models(session, settings)
    except Exception as exc:  # network, HTTP, malformed JSON -- all the same here
        logger.warning(
            "Could not list OpenRouter free models (%s); using the built-in fallbacks",
            exc,
        )
        return FALLBACK_MODELS
    finally:
        if owned_session:
            session.close()

    if not slugs:
        logger.warning("OpenRouter reported no usable free models; using the built-in fallbacks")
        return FALLBACK_MODELS

    with _cache_lock:
        _cache.slugs = slugs
        _cache.fetched_at = time.monotonic()
    logger.info("Discovered %d free OpenRouter models; leading with %s", len(slugs), slugs[0])
    return slugs


def reset_model_cache() -> None:
    """Forget discovered models and cooldowns (tests, and after a config change)."""
    global _cache
    with _cache_lock:
        _cache = _ModelCache()
    with _cooldown_lock:
        _cooldowns.clear()


def _benched(slug: str, *, now: float) -> bool:
    with _cooldown_lock:
        until = _cooldowns.get(slug, 0.0)
        if until <= now:
            _cooldowns.pop(slug, None)
            return False
        return True


def _bench(slug: str, *, seconds: float = _MODEL_COOLDOWN_SECONDS) -> None:
    with _cooldown_lock:
        _cooldowns[slug] = time.monotonic() + seconds


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


def _headers(settings: Any) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key.strip()}",
        "Content-Type": "application/json",
    }
    # OpenRouter's app-attribution headers. Optional, and deliberately carry
    # no user-identifying value.
    referer = (settings.openrouter_app_url or settings.resolved_frontend_url or "").strip()
    if referer:
        headers["HTTP-Referer"] = referer
    if settings.openrouter_app_title.strip():
        headers["X-Title"] = settings.openrouter_app_title.strip()
    return headers


def _extract_reply(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    # Some providers answer with the multi-part content array instead.
    if isinstance(content, list):
        parts = [p.get("text", "") for p in content if isinstance(p, dict)]
        return "".join(parts).strip()
    return ""


def _error_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:200]
    return str(error or body)[:200]


def _retry_after(response: requests.Response) -> int | None:
    raw = response.headers.get("Retry-After", "").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def complete(
    messages: list[dict[str, str]],
    *,
    max_tokens: int | None = None,
    temperature: float = 0.3,
    session: requests.Session | None = None,
) -> ChatResult:
    """Send `messages` to the best free model that will take them.

    Walks the candidate list, retiring any model that reports itself gone or
    rate-limited, and returns the first real answer. Raises `ChatUnavailable`
    when no candidate could answer -- with 429 when the free tier is spent, so
    the route can say "try again shortly" rather than "something broke".
    """
    settings = get_settings()
    if not settings.chat_configured:
        raise ChatUnavailable(
            "The assistant is not configured. Set OPENROUTER_API_KEY to enable it.",
            status=503,
        )

    owned_session = session is None
    session = session or requests.Session()
    url = f"{settings.openrouter_base_url.rstrip('/')}/chat/completions"
    headers = _headers(settings)

    now = time.monotonic()
    candidates = [slug for slug in available_models(session) if not _benched(slug, now=now)]
    if not candidates:
        # Everything is cooling off, which on the free tier means the daily or
        # per-minute allowance is spent rather than anything being broken.
        raise ChatUnavailable(
            "The free model tier is busy right now. Try again in a few minutes.",
            status=429,
            retry_after=60,
        )

    attempted: list[str] = []
    last_detail = ""
    rate_limited = False
    retry_after: int | None = None

    try:
        for slug in candidates[:_MAX_ATTEMPTS]:
            body = {
                "model": slug,
                "messages": messages,
                "max_tokens": max_tokens or settings.chat_max_tokens,
                "temperature": temperature,
            }
            try:
                response = session.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=settings.chat_timeout_seconds,
                )
            except requests.Timeout:
                last_detail = "the model did not respond in time"
                logger.warning("OpenRouter timeout on %s", slug)
                attempted.append(slug)
                _bench(slug, seconds=60)
                continue
            except requests.RequestException as exc:
                # No candidate will do better if the network itself is down.
                raise ChatUnavailable(
                    "Could not reach the assistant service. Check the server's "
                    "network access and try again.",
                    status=503,
                ) from exc

            if response.status_code == 200:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}
                reply = _extract_reply(payload)
                if reply:
                    if attempted:
                        logger.info("OpenRouter answered with %s after skipping %s", slug, attempted)
                    usage = payload.get("usage") or {}
                    return ChatResult(
                        reply=reply,
                        model=slug,
                        attempted=attempted,
                        usage=usage if isinstance(usage, dict) else {},
                    )
                # A 200 with nothing in it (content filter, truncation at zero
                # tokens) is not worth retrying on the same model.
                last_detail = "the model returned an empty answer"
                attempted.append(slug)
                continue

            detail = _error_detail(response)
            last_detail = detail
            attempted.append(slug)

            if response.status_code in (401, 403):
                # A bad key is not fixed by another model.
                logger.error("OpenRouter rejected the API key: %s", detail)
                raise ChatUnavailable(
                    "The assistant's API key was rejected. Check OPENROUTER_API_KEY.",
                    status=503,
                )
            if response.status_code == 429:
                rate_limited = True
                retry_after = retry_after or _retry_after(response)
                _bench(slug, seconds=retry_after or _MODEL_COOLDOWN_SECONDS)
                logger.info("OpenRouter rate-limited %s: %s", slug, detail)
                continue
            if response.status_code in (400, 404):
                # Overwhelmingly "this slug is gone or no longer free", which
                # is exactly the rotation this client exists to absorb.
                _bench(slug)
                logger.info("Retiring OpenRouter model %s: %s", slug, detail)
                continue

            logger.warning("OpenRouter error %s on %s: %s", response.status_code, slug, detail)
            _bench(slug, seconds=120)
    finally:
        if owned_session:
            session.close()

    if rate_limited:
        raise ChatUnavailable(
            "The free model tier is rate-limited right now. Try again in a few minutes.",
            status=429,
            retry_after=retry_after or 60,
        )
    raise ChatUnavailable(
        f"No free model could answer right now ({last_detail or 'unknown error'}).",
        status=503,
    )
