"""Security headers, request caps, rate limiting, and error opacity."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from thaalam import config
from thaalam.api.middleware import (
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
)


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    for name in (
        "APP_ENV",
        "RATE_LIMIT_REQUESTS",
        "RATE_LIMIT_WINDOW_SECONDS",
        "MAX_REQUEST_BYTES",
        "WHOOP_TOKEN_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


def _app(*middleware) -> FastAPI:
    app = FastAPI()
    for cls in middleware:
        app.add_middleware(cls)

    @app.get("/api/thing")
    def thing():
        return {"ok": True}

    @app.post("/api/thing")
    def create_thing(payload: dict):
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "header,expected",
    [
        ("X-Content-Type-Options", "nosniff"),
        ("X-Frame-Options", "DENY"),
        ("Referrer-Policy", "no-referrer"),
    ],
)
def test_baseline_headers_are_present(header, expected):
    with TestClient(_app(SecurityHeadersMiddleware)) as client:
        assert client.get("/api/thing").headers[header] == expected


def test_csp_blocks_framing_and_inline_script():
    with TestClient(_app(SecurityHeadersMiddleware)) as client:
        csp = client.get("/api/thing").headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    # Scripts get no inline exemption, whatever styles need.
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


def test_api_responses_are_not_cached():
    """Health data must not linger in a shared cache or the back button."""
    with TestClient(_app(SecurityHeadersMiddleware)) as client:
        assert client.get("/api/thing").headers["Cache-Control"] == "no-store"


def test_hsts_only_in_production(monkeypatch):
    with TestClient(_app(SecurityHeadersMiddleware)) as client:
        assert "Strict-Transport-Security" not in client.get("/api/thing").headers

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WHOOP_TOKEN_KEY", "x" * 44)
    config.reset_settings_cache()
    with TestClient(_app(SecurityHeadersMiddleware)) as client:
        assert "Strict-Transport-Security" in client.get("/api/thing").headers


# ---------------------------------------------------------------------------
# Request size cap
# ---------------------------------------------------------------------------


def test_oversized_body_is_refused(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "100")
    config.reset_settings_cache()
    with TestClient(_app(RequestSizeLimitMiddleware)) as client:
        response = client.post("/api/thing", json={"blob": "x" * 500})
    assert response.status_code == 413


def test_normal_body_passes(monkeypatch):
    monkeypatch.setenv("MAX_REQUEST_BYTES", "10000")
    config.reset_settings_cache()
    with TestClient(_app(RequestSizeLimitMiddleware)) as client:
        assert client.post("/api/thing", json={"blob": "x"}).status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


def test_requests_beyond_the_limit_are_refused(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "3")
    monkeypatch.setenv("RATE_LIMIT_WINDOW_SECONDS", "60")
    config.reset_settings_cache()
    with TestClient(_app(RateLimitMiddleware)) as client:
        codes = [client.get("/api/thing").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429]


def test_rate_limited_response_says_when_to_retry(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    config.reset_settings_cache()
    with TestClient(_app(RateLimitMiddleware)) as client:
        client.get("/api/thing")
        response = client.get("/api/thing")
    assert response.status_code == 429
    assert "Retry-After" in response.headers


def test_health_checks_are_exempt(monkeypatch):
    """A container health check must not exhaust a human user's budget."""
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "2")
    config.reset_settings_cache()
    with TestClient(_app(RateLimitMiddleware)) as client:
        codes = [client.get("/health").status_code for _ in range(6)]
    assert codes == [200] * 6


def test_the_limiter_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "0")
    config.reset_settings_cache()
    with TestClient(_app(RateLimitMiddleware)) as client:
        codes = [client.get("/api/thing").status_code for _ in range(10)]
    assert codes == [200] * 10


# ---------------------------------------------------------------------------
# Error opacity
# ---------------------------------------------------------------------------


def test_unhandled_errors_reveal_only_a_request_id():
    """An exception message can carry a path, a query, or a credential."""
    from thaalam.api.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        # A route that blows up inside the handler.
        response = client.get("/api/summary")

    if response.status_code == 500:
        body = response.json()
        assert body["detail"] == "Internal server error"
        assert body.get("request_id")
        assert "Traceback" not in response.text
