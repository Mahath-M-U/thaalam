"""The access-control matrix: who may reach which endpoint.

The point of testing this route by route is that a gap here is silent. An
endpoint that forgets its guard still returns 200, and nothing else in the
suite would notice.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from thaalam import config
from thaalam.api.main import app
from thaalam.auth import passwords
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import CSRF_COOKIE, CSRF_HEADER

PASSWORD = "correct-horse-battery-staple"
ADMIN_EMAIL = "admin@example.com"
VIEWER_EMAIL = "viewer@example.com"

#: Read endpoints any signed-in account may use.
READ_ENDPOINTS = [
    "/api/profile",
    "/api/summary",
    "/api/recovery",
    "/api/cycles",
    "/api/daily",
    "/api/sleep",
    "/api/workouts",
    "/api/sleep/stages/average",
    "/api/workouts/by-sport",
    "/api/insights",
    "/api/brief/explain?question=recovery",
    "/api/derived/baselines",
    "/api/derived/vitality",
    "/api/derived/reads",
    "/api/derived/reads/hyperarousal",
    "/api/derived/runway",
    "/api/chat/status",
    "/api/chat/suggestions?page=sleep",
]

#: Endpoints only an administrator may reach.
ADMIN_ENDPOINTS = [
    ("post", "/api/sync"),
    ("get", "/api/oauth/whoop/status"),
    ("get", "/api/oauth/whoop/connect"),
]


@pytest.fixture
def auth_db_path(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(path))
    config.reset_settings_cache()
    yield path
    config.reset_settings_cache()


@pytest.fixture
def auth_db(auth_db_path):
    with auth_store.connect(auth_db_path) as con:
        auth_store.create_user(
            con,
            email=ADMIN_EMAIL,
            password_hash=passwords.hash_password(PASSWORD),
            role="admin",
        )
        auth_store.create_user(
            con,
            email=VIEWER_EMAIL,
            password_hash=passwords.hash_password(PASSWORD),
            role="viewer",
        )
        yield con


@pytest.fixture
def client(auth_db):
    with TestClient(app) as test_client:
        yield test_client


def _login(client, email):
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response


def _csrf(client) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies.get(CSRF_COOKIE)}


# ---------------------------------------------------------------------------
# Unauthenticated access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_read_endpoints_reject_anonymous_callers(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_endpoints_reject_anonymous_callers(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_brief_rejects_anonymous_callers(client):
    assert client.post("/api/brief").status_code == 401


def test_chat_rejects_anonymous_callers(client):
    """The assistant spends a rationed upstream allowance, so an
    unauthenticated caller must never reach it."""
    response = client.post("/api/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 401


def test_no_data_leaks_in_an_unauthenticated_error(client):
    """A 401 must not describe what it is guarding."""
    body = client.get("/api/summary").text.lower()
    assert "hrv" not in body and "recovery_score" not in body


# ---------------------------------------------------------------------------
# Public endpoints stay public
# ---------------------------------------------------------------------------


def test_health_stays_public(client):
    """Container health checks have no session to present."""
    assert client.get("/health").status_code == 200


def test_oauth_callback_stays_reachable_without_a_session(client):
    """WHOOP redirects the browser here; it carries no app cookie.

    It must fail on the state check rather than on authentication.
    """
    response = client.get(
        "/api/oauth/whoop/callback?code=abc&state=deadbeef", follow_redirects=False
    )
    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


def test_webhook_stays_exempt_from_session_auth(client):
    """The webhook authenticates by HMAC signature, not by session."""
    response = client.post("/api/webhooks/whoop", json={"type": "sleep.updated"})
    # Rejected for a missing/bad signature (401), never for a missing session.
    assert response.status_code == 401
    assert "signature" in response.text.lower()


# ---------------------------------------------------------------------------
# Role enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_viewer_is_refused_admin_endpoints(client, method, path):
    _login(client, VIEWER_EMAIL)
    headers = _csrf(client) if method == "post" else {}
    response = getattr(client, method)(path, headers=headers)
    assert response.status_code == 403
    assert "administrator" in response.json()["detail"].lower()


def test_viewer_may_read_dashboard_data(client):
    """Viewers are the sharing model: read everything, change nothing."""
    _login(client, VIEWER_EMAIL)
    # 404 is the no-database-yet answer; either way it is not a 401/403.
    assert client.get("/api/derived/baselines").status_code in (200, 404)


def test_admin_reaches_an_admin_endpoint(client):
    _login(client, ADMIN_EMAIL)
    response = client.get("/api/oauth/whoop/status")
    assert response.status_code == 200
    assert "connected" in response.json()


# ---------------------------------------------------------------------------
# CSRF coverage of state-changing routes
# ---------------------------------------------------------------------------


def test_sync_requires_a_csrf_token(client):
    _login(client, ADMIN_EMAIL)
    # Authenticated as admin but with no CSRF header: refused before doing work.
    assert client.post("/api/sync").status_code == 403


def test_brief_requires_a_csrf_token(client):
    """It writes a row, which is why it is a POST rather than a GET."""
    _login(client, ADMIN_EMAIL)
    assert client.post("/api/brief").status_code == 403


def test_brief_is_no_longer_a_get(client):
    _login(client, ADMIN_EMAIL)
    # 405 from the router, or 404 once the SPA catch-all owns unmatched GETs.
    assert client.get("/api/brief").status_code in (404, 405)


# ---------------------------------------------------------------------------
# Auditing
# ---------------------------------------------------------------------------


def test_sync_attempt_is_audited(client, auth_db):
    _login(client, ADMIN_EMAIL)
    client.post("/api/sync", headers=_csrf(client))
    events = [row["event"] for row in auth_store.list_audit(auth_db)]
    assert "whoop.sync_triggered" in events


def test_connect_is_audited(client, auth_db):
    _login(client, ADMIN_EMAIL)
    client.get("/api/oauth/whoop/connect", follow_redirects=False)
    events = [row["event"] for row in auth_store.list_audit(auth_db)]
    assert "whoop.connect_started" in events
