"""Admin surface: role enforcement, account management, and lockout rails."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from thaalam import config
from thaalam.api.main import app
from thaalam.auth import passwords
from thaalam.auth import sessions as session_store
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import CSRF_COOKIE, CSRF_HEADER

PASSWORD = "correct-horse-battery-staple"
ADMIN_EMAIL = "admin@example.com"
VIEWER_EMAIL = "viewer@example.com"

ADMIN_ENDPOINTS = [
    ("get", "/api/admin/users"),
    ("get", "/api/admin/sessions"),
    ("get", "/api/admin/audit"),
    ("get", "/api/admin/system"),
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


def _login(client, email=ADMIN_EMAIL):
    response = client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response


def _csrf(client) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies.get(CSRF_COOKIE)}


def _user_id(con, email) -> int:
    return auth_store.get_user_by_email(con, email)["id"]


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_routes_reject_anonymous_callers(client, method, path):
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
def test_admin_routes_reject_viewers(client, method, path):
    _login(client, VIEWER_EMAIL)
    assert getattr(client, method)(path).status_code == 403


def test_viewer_cannot_create_an_account(client):
    """The obvious privilege-escalation path."""
    _login(client, VIEWER_EMAIL)
    response = client.post(
        "/api/admin/users",
        json={"email": "sneaky@example.com", "role": "admin"},
        headers=_csrf(client),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


def test_admin_lists_accounts(client):
    _login(client)
    emails = {row["email"] for row in client.get("/api/admin/users").json()}
    assert emails == {ADMIN_EMAIL, VIEWER_EMAIL}


def test_listing_accounts_never_exposes_hashes(client):
    _login(client)
    assert "password_hash" not in client.get("/api/admin/users").text


def test_creating_an_account_returns_a_one_time_password(client, auth_db):
    _login(client)
    response = client.post(
        "/api/admin/users",
        json={"email": "newcomer@example.com", "role": "viewer"},
        headers=_csrf(client),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user"]["role"] == "viewer"
    # The invitee must replace it before the account is good for anything.
    assert body["user"]["must_change_password"] is True

    row = auth_store.get_user_by_email(auth_db, "newcomer@example.com")
    assert passwords.verify_password(row["password_hash"], body["temporary_password"])


def test_creating_a_duplicate_account_is_refused(client):
    _login(client)
    response = client.post(
        "/api/admin/users",
        json={"email": ADMIN_EMAIL, "role": "viewer"},
        headers=_csrf(client),
    )
    assert response.status_code == 409


def test_admin_can_promote_a_viewer(client, auth_db):
    _login(client)
    viewer_id = _user_id(auth_db, VIEWER_EMAIL)
    response = client.patch(
        f"/api/admin/users/{viewer_id}", json={"role": "admin"}, headers=_csrf(client)
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


def test_disabling_an_account_revokes_its_sessions(client, auth_db):
    viewer_id = _user_id(auth_db, VIEWER_EMAIL)
    token, _ = session_store.create_session(auth_db, user_id=viewer_id, ttl_minutes=60)

    _login(client)
    response = client.patch(
        f"/api/admin/users/{viewer_id}", json={"is_active": False}, headers=_csrf(client)
    )
    assert response.status_code == 200
    assert session_store.lookup_session(auth_db, token, ttl_minutes=60) is None


def test_resetting_a_password_revokes_sessions_and_forces_a_change(client, auth_db):
    viewer_id = _user_id(auth_db, VIEWER_EMAIL)
    token, _ = session_store.create_session(auth_db, user_id=viewer_id, ttl_minutes=60)

    _login(client)
    response = client.post(
        f"/api/admin/users/{viewer_id}/reset-password", headers=_csrf(client)
    )
    assert response.status_code == 200
    assert response.json()["user"]["must_change_password"] is True
    assert session_store.lookup_session(auth_db, token, ttl_minutes=60) is None


def test_updating_a_missing_account_is_a_404(client):
    _login(client)
    assert (
        client.patch("/api/admin/users/9999", json={"role": "viewer"}, headers=_csrf(client)).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Lockout rails
# ---------------------------------------------------------------------------


def test_the_last_admin_cannot_be_demoted(client, auth_db):
    """Otherwise the deployment locks itself out and needs shell access."""
    _login(client)
    admin_id = _user_id(auth_db, ADMIN_EMAIL)
    response = client.patch(
        f"/api/admin/users/{admin_id}", json={"role": "viewer"}, headers=_csrf(client)
    )
    assert response.status_code == 409
    assert "last active administrator" in response.json()["detail"]


def test_the_last_admin_cannot_be_disabled(client, auth_db):
    _login(client)
    admin_id = _user_id(auth_db, ADMIN_EMAIL)
    response = client.patch(
        f"/api/admin/users/{admin_id}", json={"is_active": False}, headers=_csrf(client)
    )
    assert response.status_code == 409


def test_an_admin_can_be_demoted_once_another_exists(client, auth_db):
    _login(client)
    viewer_id = _user_id(auth_db, VIEWER_EMAIL)
    client.patch(
        f"/api/admin/users/{viewer_id}", json={"role": "admin"}, headers=_csrf(client)
    )
    admin_id = _user_id(auth_db, ADMIN_EMAIL)
    response = client.patch(
        f"/api/admin/users/{admin_id}", json={"role": "viewer"}, headers=_csrf(client)
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Sessions and audit
# ---------------------------------------------------------------------------


def test_admin_sees_and_can_revoke_a_session(client, auth_db):
    viewer_id = _user_id(auth_db, VIEWER_EMAIL)
    token, _ = session_store.create_session(auth_db, user_id=viewer_id, ttl_minutes=60)

    _login(client)
    sessions = client.get("/api/admin/sessions").json()
    target = next(s for s in sessions if s["email"] == VIEWER_EMAIL)

    assert (
        client.delete(f"/api/admin/sessions/{target['id']}", headers=_csrf(client)).status_code
        == 204
    )
    assert session_store.lookup_session(auth_db, token, ttl_minutes=60) is None


def test_session_listing_never_exposes_tokens(client, auth_db):
    session_store.create_session(
        auth_db, user_id=_user_id(auth_db, VIEWER_EMAIL), ttl_minutes=60
    )
    _login(client)
    body = client.get("/api/admin/sessions").text
    assert "token_hash" not in body
    assert "csrf_token" not in body


def test_audit_trail_is_paginated_and_filterable(client):
    _login(client)
    response = client.get("/api/admin/audit?limit=5").json()
    assert response["total"] >= 1
    assert len(response["entries"]) <= 5

    filtered = client.get("/api/admin/audit?event=login.succeeded").json()
    assert all(e["event"] == "login.succeeded" for e in filtered["entries"])


def test_admin_actions_are_audited(client):
    _login(client)
    client.post(
        "/api/admin/users",
        json={"email": "audited@example.com", "role": "viewer"},
        headers=_csrf(client),
    )
    events = [e["event"] for e in client.get("/api/admin/audit").json()["entries"]]
    assert "user.created" in events


# ---------------------------------------------------------------------------
# System health
# ---------------------------------------------------------------------------


def test_system_health_reports_the_deployment_shape(client):
    _login(client)
    body = client.get("/api/admin/system").json()
    assert body["environment"] == "development"
    assert body["accounts"]["total"] == 2
    assert body["accounts"]["active_admins"] == 1
    assert "whoop_connected" in body
    assert "size_bytes" in body["auth_database"]


def test_system_health_leaks_no_secrets(client):
    _login(client)
    body = client.get("/api/admin/system").text.lower()
    for leak in ("client_secret", "token_key", "password", "refresh_token"):
        assert leak not in body
