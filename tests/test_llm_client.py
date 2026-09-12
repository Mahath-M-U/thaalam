"""Model selection and failure handling for the OpenRouter client.

The behaviour worth pinning down is what happens when the free tier misbehaves,
because that is the normal case rather than the exception: slugs are retired
upstream without notice, and 429s arrive whenever the shared allowance runs
short. None of these tests touch the network.
"""

from __future__ import annotations

import json

import pytest
import requests

from thaalam import config
from thaalam.services import llm_client
from thaalam.services.llm_client import ChatUnavailable


@pytest.fixture(autouse=True)
def _configured(monkeypatch):
    """A key present, no pinned model, and a clean model cache per test."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("CHAT_ENABLED", "true")
    config.reset_settings_cache()
    llm_client.reset_model_cache()
    yield
    config.reset_settings_cache()
    llm_client.reset_model_cache()


class _Response:
    """The slice of `requests.Response` this client actually uses."""

    def __init__(self, status_code: int, payload: object, headers: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def _answer(text: str = "Because your HRV is 12% below baseline.") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"total_tokens": 120},
    }


class _Session:
    """Scripted session. `posts` replays one response per call, in order."""

    def __init__(self, models: object = None, posts: list[_Response] | None = None) -> None:
        self._models = models
        self._posts = list(posts or [])
        self.post_bodies: list[dict] = []
        self.model_calls = 0
        self.closed = False

    def get(self, url, headers=None, timeout=None):
        self.model_calls += 1
        if isinstance(self._models, Exception):
            raise self._models
        return _Response(200, self._models)

    def post(self, url, json=None, headers=None, timeout=None):
        self.post_bodies.append(json or {})
        if not self._posts:
            raise AssertionError("more POSTs than the test scripted")
        result = self._posts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def _catalogue(*entries: tuple[str, str, str, int]) -> dict:
    """`data` payload for GET /models from (id, prompt, completion, ctx) tuples."""
    return {
        "data": [
            {
                "id": slug,
                "context_length": ctx,
                "pricing": {"prompt": prompt, "completion": completion},
            }
            for slug, prompt, completion, ctx in entries
        ]
    }


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_only_genuinely_free_models_are_offered():
    """A priced model must never be selected, however it spells its price.

    The prices arrive as decimal strings, so a truthiness check would call
    every priced model free -- exactly the bug that would silently start
    charging a user's account.
    """
    session = _Session(
        models=_catalogue(
            ("free/model:free", "0", "0", 32_000),
            ("cheap/model", "0.0000001", "0", 32_000),
            ("priced/model", "0", "0.0000002", 32_000),
            ("zero-decimal/model:free", "0.0", "0.0", 32_000),
        )
    )
    slugs = llm_client.available_models(session)
    assert "cheap/model" not in slugs
    assert "priced/model" not in slugs
    assert set(slugs) == {"free/model:free", "zero-decimal/model:free"}


def test_preference_order_beats_context_length():
    """Taste first, then the roomiest model inside that family."""
    session = _Session(
        models=_catalogue(
            ("unknown/whatever:free", "0", "0", 200_000),
            ("google/gemma-2-9b:free", "0", "0", 16_000),
            ("deepseek/deepseek-chat:free", "0", "0", 64_000),
            ("deepseek/deepseek-small:free", "0", "0", 32_000),
        )
    )
    slugs = llm_client.available_models(session)
    # deepseek leads MODEL_PREFERENCE; the larger context wins within it; and
    # an unlisted family ranks last rather than being dropped.
    assert slugs[0] == "deepseek/deepseek-chat:free"
    assert slugs[1] == "deepseek/deepseek-small:free"
    assert slugs[-1] == "unknown/whatever:free"


def test_models_too_small_to_hold_a_page_are_skipped():
    session = _Session(
        models=_catalogue(
            ("tiny/model:free", "0", "0", 4_096),
            ("roomy/model:free", "0", "0", 32_000),
        )
    )
    assert llm_client.available_models(session) == ("roomy/model:free",)


def test_an_unreachable_catalogue_falls_back_instead_of_failing():
    """A models endpoint that is down must not take the assistant down."""
    session = _Session(models=requests.ConnectionError("no route"))
    assert llm_client.available_models(session) == llm_client.FALLBACK_MODELS


def test_an_empty_free_roster_falls_back():
    session = _Session(models=_catalogue(("priced/only", "0.001", "0.001", 32_000)))
    assert llm_client.available_models(session) == llm_client.FALLBACK_MODELS


def test_a_pinned_model_is_used_verbatim_and_costs_no_lookup(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "someone/specific:free")
    config.reset_settings_cache()
    session = _Session(models=_catalogue(("other/model:free", "0", "0", 32_000)))
    assert llm_client.available_models(session) == ("someone/specific:free",)
    assert session.model_calls == 0


def test_the_catalogue_is_fetched_once_and_then_cached():
    session = _Session(models=_catalogue(("free/model:free", "0", "0", 32_000)))
    llm_client.available_models(session)
    llm_client.available_models(session)
    assert session.model_calls == 1


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


def test_a_retired_model_is_skipped_for_the_next_candidate():
    """The rotation this client exists to absorb: a 404 on the leading slug.

    It must cost one wasted request, not the answer.
    """
    session = _Session(
        models=_catalogue(
            ("deepseek/gone:free", "0", "0", 32_000),
            ("qwen/qwen3-alive:free", "0", "0", 32_000),
        ),
        posts=[
            _Response(404, {"error": {"message": "No endpoints found for this model"}}),
            _Response(200, _answer()),
        ],
    )
    result = llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert result.model == "qwen/qwen3-alive:free"
    assert result.attempted == ["deepseek/gone:free"]
    assert "HRV" in result.reply


def test_a_rate_limited_model_is_skipped_then_the_answer_still_lands():
    session = _Session(
        models=_catalogue(
            ("deepseek/busy:free", "0", "0", 32_000),
            ("qwen/qwen3-free:free", "0", "0", 32_000),
        ),
        posts=[
            _Response(429, {"error": {"message": "rate limited"}}, {"Retry-After": "30"}),
            _Response(200, _answer()),
        ],
    )
    result = llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert result.model == "qwen/qwen3-free:free"


def test_every_candidate_rate_limited_reports_429_not_a_server_error():
    """The distinction the UI depends on: "wait" rather than "broken"."""
    session = _Session(
        models=_catalogue(
            ("deepseek/a:free", "0", "0", 32_000),
            ("qwen/qwen3-b:free", "0", "0", 32_000),
            ("google/gemma-3-c:free", "0", "0", 32_000),
        ),
        posts=[
            _Response(429, {"error": {"message": "limit"}}, {"Retry-After": "45"}),
            _Response(429, {"error": {"message": "limit"}}),
            _Response(429, {"error": {"message": "limit"}}),
        ],
    )
    with pytest.raises(ChatUnavailable) as exc:
        llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert exc.value.status == 429
    assert exc.value.retry_after == 45


def test_a_rejected_key_fails_immediately_rather_than_trying_every_model():
    """Another model cannot fix a bad key, and trying wastes the allowance."""
    session = _Session(
        models=_catalogue(
            ("deepseek/a:free", "0", "0", 32_000),
            ("qwen/qwen3-b:free", "0", "0", 32_000),
        ),
        posts=[_Response(401, {"error": {"message": "invalid key"}})],
    )
    with pytest.raises(ChatUnavailable) as exc:
        llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert exc.value.status == 503
    assert "OPENROUTER_API_KEY" in str(exc.value)
    assert len(session.post_bodies) == 1


def test_a_dead_network_reports_once_without_retrying_every_model():
    session = _Session(
        models=_catalogue(
            ("deepseek/a:free", "0", "0", 32_000),
            ("qwen/qwen3-b:free", "0", "0", 32_000),
        ),
        posts=[requests.ConnectionError("down")],
    )
    with pytest.raises(ChatUnavailable) as exc:
        llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert exc.value.status == 503
    assert len(session.post_bodies) == 1


def test_retries_are_capped_so_a_bad_roster_cannot_drain_the_daily_budget():
    session = _Session(
        models=_catalogue(
            *[(f"deepseek/m{i}:free", "0", "0", 32_000) for i in range(10)]
        ),
        posts=[_Response(404, {"error": {"message": "gone"}}) for _ in range(10)],
    )
    with pytest.raises(ChatUnavailable):
        llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert len(session.post_bodies) == 3


def test_an_unconfigured_key_refuses_before_any_request():
    """No key means no outbound call at all, not a failed one."""
    import os

    os.environ.pop("OPENROUTER_API_KEY", None)
    config.reset_settings_cache()
    session = _Session()
    with pytest.raises(ChatUnavailable) as exc:
        llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert exc.value.status == 503
    assert session.post_bodies == []


def test_the_request_carries_the_key_and_app_attribution_headers():
    session = _Session(
        models=_catalogue(("deepseek/a:free", "0", "0", 32_000)),
        posts=[_Response(200, _answer())],
    )
    llm_client.complete(
        [{"role": "user", "content": "why?"}], max_tokens=256, session=session
    )
    body = session.post_bodies[0]
    assert body["model"] == "deepseek/a:free"
    assert body["max_tokens"] == 256
    assert body["messages"][0]["content"] == "why?"

    settings = config.get_settings()
    headers = llm_client._headers(settings)
    assert headers["Authorization"] == "Bearer test-key"
    assert headers["X-Title"] == "Thaalam"


def test_a_multipart_content_answer_is_flattened():
    """Some providers answer with the content array rather than a string."""
    session = _Session(
        models=_catalogue(("deepseek/a:free", "0", "0", 32_000)),
        posts=[
            _Response(
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "HRV is "},
                                    {"type": "text", "text": "48 ms."},
                                ]
                            }
                        }
                    ]
                },
            )
        ],
    )
    result = llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert result.reply == "HRV is 48 ms."


def test_an_empty_answer_moves_on_to_the_next_model():
    session = _Session(
        models=_catalogue(
            ("deepseek/a:free", "0", "0", 32_000),
            ("qwen/qwen3-b:free", "0", "0", 32_000),
        ),
        posts=[
            _Response(200, {"choices": [{"message": {"content": "   "}}]}),
            _Response(200, _answer()),
        ],
    )
    result = llm_client.complete([{"role": "user", "content": "why?"}], session=session)
    assert result.model == "qwen/qwen3-b:free"
