"""Streaming the answer out of OpenRouter, one token at a time.

The client's job here is the same as in `test_llm_client`: survive a free tier
that retires models without notice. What changes is that some of the walk
happens *after* the first token has been handed over, and at that point the
choice of model is final -- so these tests are mostly about where the line
between "try someone else" and "keep what we have" falls. None touch the
network.
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
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.setenv("CHAT_ENABLED", "true")
    config.reset_settings_cache()
    llm_client.reset_model_cache()
    yield
    config.reset_settings_cache()
    llm_client.reset_model_cache()


class _StreamResponse:
    """The slice of a streamed `requests.Response` this client uses."""

    def __init__(
        self,
        status_code: int = 200,
        lines: list[str] | None = None,
        payload: object = None,
        headers: dict | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self._lines = list(lines or [])
        self._payload = payload if payload is not None else {"error": {"message": "nope"}}
        self._raises = raises
        self.text = json.dumps(self._payload)
        self.closed = False

    def iter_lines(self):
        for line in self._lines:
            yield line.encode("utf-8")
        if self._raises is not None:
            raise self._raises

    def json(self):
        return self._payload

    def close(self):
        self.closed = True


class _Session:
    """Scripted session whose POSTs replay one response each, in order."""

    def __init__(self, models: object = None, posts: list[object] | None = None) -> None:
        self._models = models
        self._posts = list(posts or [])
        self.post_bodies: list[dict] = []
        self.closed = False

    def get(self, url, headers=None, timeout=None):
        class _Models:
            status_code = 200

            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

            def raise_for_status(self):
                return None

        if isinstance(self._models, Exception):
            raise self._models
        return _Models(self._models)

    def post(self, url, json=None, headers=None, timeout=None, stream=False):
        assert stream is True, "the streaming client must ask for a streamed body"
        self.post_bodies.append(json or {})
        if not self._posts:
            raise AssertionError("more POSTs than the test scripted")
        result = self._posts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


def _catalogue(*slugs: str) -> dict:
    return {
        "data": [
            {"id": slug, "context_length": 128_000, "pricing": {"prompt": "0", "completion": "0"}}
            for slug in slugs
        ]
    }


def _sse(*texts: str, usage: dict | None = None, done: bool = True) -> list[str]:
    """An OpenRouter stream: a keepalive, one frame per token, then [DONE]."""
    lines = [": OPENROUTER PROCESSING", ""]
    for text in texts:
        lines.append(
            "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})
        )
        lines.append("")
    if usage is not None:
        lines.append(
            "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": usage})
        )
        lines.append("")
    if done:
        lines.append("data: [DONE]")
    return lines


def _drain(events):
    """Collect a stream into (text, events)."""
    collected = list(events)
    text = "".join(e.text for e in collected if e.kind == "delta")
    return text, collected


MESSAGES = [{"role": "user", "content": "why is my HRV low?"}]


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_tokens_arrive_one_at_a_time_and_reassemble_into_the_answer():
    session = _Session(
        models=_catalogue("deepseek/one:free"),
        posts=[_StreamResponse(lines=_sse("Your ", "HRV ", "is low.", usage={"total_tokens": 42}))],
    )

    text, events = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "Your HRV is low."
    assert [e.kind for e in events] == ["start", "delta", "delta", "delta", "end"]
    assert events[0].model == "deepseek/one:free"
    assert events[-1].usage == {"total_tokens": 42}
    assert events[-1].error == ""


def test_the_request_asks_upstream_to_stream():
    session = _Session(
        models=_catalogue("deepseek/one:free"),
        posts=[_StreamResponse(lines=_sse("ok"))],
    )

    _drain(llm_client.stream(MESSAGES, session=session))

    assert session.post_bodies[0]["stream"] is True
    assert session.post_bodies[0]["messages"] == MESSAGES


def test_keepalive_comments_and_unparseable_frames_are_ignored():
    """A stream carries traffic that is not an answer; none of it may show up."""
    lines = [
        ": OPENROUTER PROCESSING",
        "",
        "data: {not json",
        "",
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"Real text."}}]}',
        "",
        "data: [DONE]",
    ]
    session = _Session(models=_catalogue("deepseek/one:free"), posts=[_StreamResponse(lines=lines)])

    text, _ = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "Real text."


def test_a_multipart_delta_is_flattened():
    lines = [
        'data: {"choices":[{"delta":{"content":[{"type":"text","text":"Split "},'
        '{"type":"text","text":"answer."}]}}]}',
        "",
        "data: [DONE]",
    ]
    session = _Session(models=_catalogue("deepseek/one:free"), posts=[_StreamResponse(lines=lines)])

    text, _ = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "Split answer."


def test_the_upstream_response_is_closed_even_when_the_caller_walks_away():
    """A dock the user closes mid-answer must not leak the upstream socket."""
    response = _StreamResponse(lines=_sse("one", "two", "three"))
    session = _Session(models=_catalogue("deepseek/one:free"), posts=[response])

    events = llm_client.stream(MESSAGES, session=session)
    next(events)  # start
    next(events)  # first delta
    events.close()

    assert response.closed is True


# ---------------------------------------------------------------------------
# Before the first token: still free to try someone else
# ---------------------------------------------------------------------------


def test_a_retired_model_is_skipped_for_the_next_candidate():
    session = _Session(
        models=_catalogue("deepseek/gone:free", "meta-llama/llama-4:free"),
        posts=[
            _StreamResponse(status_code=404, payload={"error": {"message": "No endpoints"}}),
            _StreamResponse(lines=_sse("From the second model.")),
        ],
    )

    text, events = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "From the second model."
    start = next(e for e in events if e.kind == "start")
    assert start.model == "meta-llama/llama-4:free"
    assert start.attempted == ["deepseek/gone:free"]


def test_an_error_frame_before_any_text_falls_through_to_the_next_model():
    """Upstream reports some failures inside a 200 body rather than as a status."""
    session = _Session(
        models=_catalogue("deepseek/one:free", "meta-llama/llama-4:free"),
        posts=[
            _StreamResponse(lines=['data: {"error":{"code":429,"message":"rate limited"}}', ""]),
            _StreamResponse(lines=_sse("Second model answered.")),
        ],
    )

    text, _ = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "Second model answered."


def test_a_stream_that_produces_nothing_moves_on_rather_than_returning_silence():
    session = _Session(
        models=_catalogue("deepseek/one:free", "meta-llama/llama-4:free"),
        posts=[
            _StreamResponse(lines=["data: [DONE]"]),
            _StreamResponse(lines=_sse("A real answer.")),
        ],
    )

    text, _ = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "A real answer."


def test_a_connection_that_dies_before_the_first_token_tries_the_next_model():
    session = _Session(
        models=_catalogue("deepseek/one:free", "meta-llama/llama-4:free"),
        posts=[
            _StreamResponse(lines=[], raises=requests.ConnectionError("reset")),
            _StreamResponse(lines=_sse("Recovered.")),
        ],
    )

    text, _ = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "Recovered."


def test_every_candidate_rate_limited_reports_429_rather_than_a_server_error():
    session = _Session(
        models=_catalogue("a/one:free", "b/two:free", "c/three:free"),
        posts=[
            _StreamResponse(status_code=429, headers={"Retry-After": "30"}),
            _StreamResponse(status_code=429),
            _StreamResponse(status_code=429),
        ],
    )

    with pytest.raises(ChatUnavailable) as raised:
        _drain(llm_client.stream(MESSAGES, session=session))

    assert raised.value.status == 429
    assert raised.value.retry_after == 30


def test_a_rejected_key_fails_immediately_rather_than_trying_every_model():
    session = _Session(
        models=_catalogue("a/one:free", "b/two:free"),
        posts=[_StreamResponse(status_code=401, payload={"error": {"message": "bad key"}})],
    )

    with pytest.raises(ChatUnavailable) as raised:
        _drain(llm_client.stream(MESSAGES, session=session))

    assert raised.value.status == 503
    assert "OPENROUTER_API_KEY" in str(raised.value)


def test_an_unconfigured_key_refuses_before_the_iterator_is_even_touched():
    """The route needs this as a raise, not as a first event, to answer 503."""
    import os

    old = os.environ.pop("OPENROUTER_API_KEY", None)
    config.reset_settings_cache()
    try:
        with pytest.raises(ChatUnavailable) as raised:
            llm_client.stream(MESSAGES)
        assert raised.value.status == 503
    finally:
        if old is not None:
            os.environ["OPENROUTER_API_KEY"] = old
        config.reset_settings_cache()


# ---------------------------------------------------------------------------
# After the first token: the answer stands with whatever it managed to say
# ---------------------------------------------------------------------------


def test_a_connection_dropped_mid_answer_keeps_the_partial_text():
    session = _Session(
        models=_catalogue("deepseek/one:free", "meta-llama/llama-4:free"),
        posts=[
            _StreamResponse(
                lines=['data: {"choices":[{"delta":{"content":"Half an "}}]}', ""],
                raises=requests.ConnectionError("reset"),
            )
        ],
    )

    text, events = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "Half an "
    end = events[-1]
    assert end.kind == "end"
    assert "connection" in end.error.lower()


def test_an_error_frame_after_text_ends_the_answer_instead_of_restarting_it():
    """Switching models here would replay the answer from the top on screen."""
    session = _Session(
        models=_catalogue("deepseek/one:free", "meta-llama/llama-4:free"),
        posts=[
            _StreamResponse(
                lines=[
                    'data: {"choices":[{"delta":{"content":"Started"}}]}',
                    "",
                    'data: {"error":{"code":502,"message":"provider died"}}',
                    "",
                ]
            )
        ],
    )

    text, events = _drain(llm_client.stream(MESSAGES, session=session))

    assert text == "Started"
    assert events[-1].kind == "end"
    assert events[-1].error
