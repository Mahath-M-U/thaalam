"""Where the WHOOP callback sends the browser once the round-trip finishes.

The callback used to fall back to a literal http://localhost:3001, so a
deployment that had not set FRONTEND_URL would exchange the token correctly
and then redirect the user to a port on their own machine.
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from thaalam.api.routes.oauth import _frontend_base
from thaalam.config import DEV_FRONTEND_URL, reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    for name in ("APP_ENV", "THAALAM_ENV", "ENV", "FRONTEND_URL"):
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def _request(host: str = "thaalam.example", scheme: str = "https") -> Request:
    """A request as it reaches the app behind a TLS-terminating proxy.

    `run_api.py` enables proxy headers in production, so by the time the route
    sees it the scheme and host are the public ones, not the container's.
    """
    return Request(
        {
            "type": "http",
            "scheme": scheme,
            "server": (host, 443 if scheme == "https" else 80),
            "root_path": "",
            "path": "/api/oauth/whoop/callback",
            "query_string": b"",
            "headers": [(b"host", host.encode())],
        }
    )


def test_production_redirects_to_the_origin_the_request_arrived_on(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert _frontend_base(_request()) == "https://thaalam.example"


def test_production_never_falls_back_to_localhost(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert "localhost" not in _frontend_base(_request())


def test_configured_frontend_url_still_wins(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("FRONTEND_URL", "https://elsewhere.example")
    assert _frontend_base(_request()) == "https://elsewhere.example"


def test_development_keeps_pointing_at_the_vite_server():
    """Dev serves the frontend on 3001 while the API answers on 8001."""
    assert _frontend_base(_request("127.0.0.1:8001", "http")) == DEV_FRONTEND_URL
