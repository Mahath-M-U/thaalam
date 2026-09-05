"""Structured logging: redaction, JSON shape, and request correlation."""

from __future__ import annotations

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thaalam.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from thaalam.logging_config import (
    REDACTED,
    JsonFormatter,
    RedactingFormatter,
    build_formatter,
    redact,
    request_id_var,
)


def _record(message: str, *args, **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="thaalam.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


# --------------------------------------------------------------------------
# Redaction
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "Authorization: Bearer abc123.def456-ghi",
        "client_secret=super-secret-value",
        "password: hunter2trustno1",
        'refresh_token="rt_0123456789abcdef"',
        "access_token=at_0123456789abcdef",
        "Cookie: thaalam_session=opaque-session-token",
        "token_key=aGVsbG8gd29ybGQgdGhpcyBpcyBrZXk=",
        "csrf_token=9f8e7d6c5b4a",
    ],
)
def test_known_secret_shapes_never_survive(line):
    out = redact(line)
    assert REDACTED in out
    for leak in (
        "abc123.def456-ghi",
        "super-secret-value",
        "hunter2trustno1",
        "rt_0123456789abcdef",
        "at_0123456789abcdef",
        "opaque-session-token",
        "aGVsbG8gd29ybGQgdGhpcyBpcyBrZXk=",
        "9f8e7d6c5b4a",
    ):
        assert leak not in out


def test_literal_configured_secret_is_redacted_anywhere(monkeypatch):
    """A secret must be caught even with no label next to it."""
    from thaalam import config, logging_config

    monkeypatch.setenv("CLIENT_SECRET", "s3cr3t-whoop-client-value")
    config.reset_settings_cache()
    logging_config._literal_secrets.cache_clear()
    try:
        out = redact("upstream rejected the value s3cr3t-whoop-client-value oddly")
        assert "s3cr3t-whoop-client-value" not in out
        assert REDACTED in out
        # A labelled occurrence of the same secret redacts exactly once,
        # rather than the literal pass eating into the placeholder.
        labelled = redact("client_secret=s3cr3t-whoop-client-value")
        assert labelled == f"client_secret={REDACTED}"
    finally:
        logging_config._literal_secrets.cache_clear()
        config.reset_settings_cache()


def test_ordinary_text_is_left_alone():
    line = "Synced 42 cycles in 1.2s"
    assert redact(line) == line


def test_redaction_survives_lazy_formatting_args():
    formatted = RedactingFormatter("%(message)s").format(
        _record("token=%s", "abcdef123456")
    )
    assert "abcdef123456" not in formatted
    assert REDACTED in formatted


def test_exception_tracebacks_are_redacted():
    try:
        raise ValueError("failed with client_secret=leaky-secret-here")
    except ValueError:
        import sys

        record = logging.LogRecord(
            name="thaalam.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="boom",
            args=(),
            exc_info=sys.exc_info(),
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "leaky-secret-here" not in payload["exception"]


# --------------------------------------------------------------------------
# JSON shape
# --------------------------------------------------------------------------


def test_json_formatter_emits_one_parsable_object():
    payload = json.loads(JsonFormatter().format(_record("hello")))
    assert payload["message"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "thaalam.test"
    assert payload["ts"].endswith("+00:00")


def test_json_formatter_includes_structured_extras():
    record = _record(
        "req",
        request_id="abc123",
        method="GET",
        path="/api/summary",
        status=200,
        duration_ms=12.5,
        user="admin@example.com",
    )
    payload = json.loads(JsonFormatter().format(record))
    assert payload["request_id"] == "abc123"
    assert payload["method"] == "GET"
    assert payload["path"] == "/api/summary"
    assert payload["status"] == 200
    assert payload["duration_ms"] == 12.5
    assert payload["user"] == "admin@example.com"


def test_json_formatter_picks_up_ambient_request_id():
    token = request_id_var.set("ambient-id")
    try:
        payload = json.loads(JsonFormatter().format(_record("hello")))
    finally:
        request_id_var.reset(token)
    assert payload["request_id"] == "ambient-id"


def test_formatter_is_human_readable_in_dev_and_json_elsewhere():
    assert isinstance(build_formatter("development"), RedactingFormatter)
    assert isinstance(build_formatter("production"), JsonFormatter)


# --------------------------------------------------------------------------
# Request correlation
# --------------------------------------------------------------------------


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ok")
    def ok():
        return {"request_id": request_id_var.get()}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kaboom")

    return app


def test_response_carries_a_request_id():
    with TestClient(_app()) as client:
        response = client.get("/ok")
    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER]
    # The handler saw the same id that came back on the response.
    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_client_supplied_request_id_is_reused():
    with TestClient(_app()) as client:
        response = client.get("/ok", headers={REQUEST_ID_HEADER: "trace-42"})
    assert response.headers[REQUEST_ID_HEADER] == "trace-42"


def test_hostile_request_id_is_replaced_not_echoed():
    """An inbound id lands in the log file, so it must not forge structure."""
    hostile = 'evil", "level": "CRITICAL\n\rinjected'
    with TestClient(_app()) as client:
        response = client.get("/ok", headers={REQUEST_ID_HEADER: hostile})
    returned = response.headers[REQUEST_ID_HEADER]
    assert returned != hostile
    assert "\n" not in returned and '"' not in returned


def test_request_id_is_not_shared_between_requests():
    with TestClient(_app()) as client:
        first = client.get("/ok").headers[REQUEST_ID_HEADER]
        second = client.get("/ok").headers[REQUEST_ID_HEADER]
    assert first != second


def test_context_is_cleared_after_a_request():
    with TestClient(_app()) as client:
        client.get("/ok")
    assert request_id_var.get() == ""


def test_failing_request_is_logged_with_its_id(caplog):
    caplog.set_level(logging.ERROR, logger="thaalam.api.middleware")
    with TestClient(_app(), raise_server_exceptions=False) as client:
        client.get("/boom")
    failures = [r for r in caplog.records if r.message == "Request failed"]
    assert failures, "the exception path must log"
    assert getattr(failures[0], "path") == "/boom"
    assert getattr(failures[0], "request_id")
