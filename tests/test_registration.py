"""Registration: the first-run window, and invitation-only thereafter.

A viewer on this deployment reads the owner's health data, so "who may create
an account" is the same question as "who may read your recovery history".
These tests exist to keep that answer from drifting to "anyone".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from thaalam import config
from thaalam.api.main import app
from thaalam.auth import passwords
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE

PASSWORD = "correct-horse-battery-staple"
ADMIN_EMAIL = "admin@example.com"


@pytest.fixture
def auth_db_path(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(path))
    config.reset_settings_cache()
    yield path
    config.reset_settings_cache()


@pytest.fixture
def empty_db(auth_db_path):
    """No accounts at all -- the first-run state."""
    with auth_store.connect(auth_db_path) as con:
        yield con


@pytest.fixture
def seeded_db(auth_db_path):
    """One admin already exists, so the first-run window has closed."""
    with auth_store.connect(auth_db_path) as con:
        auth_store.create_user(
            con,
            email=ADMIN_EMAIL,
            password_hash=passwords.hash_password(PASSWORD),
            role="admin",
        )
        yield con


@pytest.fixture
def client(auth_db_path):
    with TestClient(app) as test_client:
        yield test_client


def _register(client, email, password=PASSWORD, token=None):
    body = {"email": email, "password": password}
    if token is not None:
        body["invite_token"] = token
    return client.post("/api/auth/register", json=body)


def _login_admin(client):
    response = client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": PASSWORD}
    )
    assert response.status_code == 200
    return response


def _csrf(client) -> dict[str, str]:
    return {CSRF_HEADER: client.cookies.get(CSRF_COOKIE)}


def _mint_invite(client, role="viewer", email=None) -> str:
    body: dict = {"role": role}
    if email:
        body["email"] = email
    response = client.post("/api/admin/invites", json=body, headers=_csrf(client))
    assert response.status_code == 201
    return response.json()["token"]


# ---------------------------------------------------------------------------
# First run
# ---------------------------------------------------------------------------


def test_first_visitor_claims_the_owner_account(client, empty_db):
    response = _register(client, "owner@example.com")
    assert response.status_code == 201
    body = response.json()
    assert body["role"] == "admin"
    # They chose the password themselves, so there is nothing to rotate.
    assert body["must_change_password"] is False
    assert SESSION_COOKIE in response.cookies


def test_first_run_signs_the_owner_straight_in(client, empty_db):
    _register(client, "owner@example.com")
    assert client.get("/api/auth/me").status_code == 200


def test_the_first_run_window_closes_after_one_account(client, empty_db):
    """The most important boundary here: it must not stay open."""
    assert _register(client, "owner@example.com").status_code == 201

    second = _register(client, "opportunist@example.com")
    assert second.status_code == 403
    assert "invitation" in second.json()["detail"].lower()


def test_registration_status_reports_the_first_run_window(client, empty_db):
    body = client.get("/api/auth/registration").json()
    assert body["first_run"] is True
    assert body["invite_required"] is False

    _register(client, "owner@example.com")
    after = client.get("/api/auth/registration").json()
    assert after["first_run"] is False
    assert after["invite_required"] is True


# ---------------------------------------------------------------------------
# Invitation-only
# ---------------------------------------------------------------------------


def test_registration_without_an_invite_is_refused(client, seeded_db):
    assert _register(client, "stranger@example.com").status_code == 403


def test_registration_with_a_junk_token_is_refused(client, seeded_db):
    assert _register(client, "stranger@example.com", token="not-a-real-token").status_code == 403


def test_an_invited_visitor_can_register(client, seeded_db):
    _login_admin(client)
    token = _mint_invite(client)
    client.post("/api/auth/logout")

    response = _register(client, "family@example.com", token=token)
    assert response.status_code == 201
    assert response.json()["role"] == "viewer"


def test_an_invite_is_single_use(client, seeded_db):
    _login_admin(client)
    token = _mint_invite(client)
    client.post("/api/auth/logout")

    assert _register(client, "first@example.com", token=token).status_code == 201
    assert _register(client, "second@example.com", token=token).status_code == 403


def test_an_invite_carries_its_role(client, seeded_db):
    _login_admin(client)
    token = _mint_invite(client, role="admin")
    client.post("/api/auth/logout")

    assert _register(client, "second-admin@example.com", token=token).json()["role"] == "admin"


def test_an_expired_invite_is_refused(client, seeded_db, auth_db_path):
    _login_admin(client)
    token = _mint_invite(client)
    client.post("/api/auth/logout")

    with auth_store.connect(auth_db_path) as con:
        con.execute(
            "UPDATE invites SET expires_at = ?",
            (auth_store.to_iso(auth_store.utcnow()),),
        )
        con.commit()

    assert _register(client, "late@example.com", token=token).status_code == 403


def test_a_revoked_invite_is_refused(client, seeded_db):
    _login_admin(client)
    response = client.post("/api/admin/invites", json={"role": "viewer"}, headers=_csrf(client))
    token = response.json()["token"]
    invite_id = response.json()["id"]

    assert client.delete(f"/api/admin/invites/{invite_id}", headers=_csrf(client)).status_code == 204
    client.post("/api/auth/logout")

    assert _register(client, "revoked@example.com", token=token).status_code == 403


def test_an_email_bound_invite_only_works_for_that_address(client, seeded_db):
    _login_admin(client)
    token = _mint_invite(client, email="expected@example.com")
    client.post("/api/auth/logout")

    wrong = _register(client, "someone-else@example.com", token=token)
    assert wrong.status_code == 403
    assert "different email" in wrong.json()["detail"].lower()

    assert _register(client, "expected@example.com", token=token).status_code == 201


def test_invite_tokens_are_not_stored_in_the_clear(client, seeded_db, auth_db_path):
    _login_admin(client)
    token = _mint_invite(client)
    with auth_store.connect(auth_db_path) as con:
        stored = con.execute("SELECT token_hash FROM invites").fetchone()["token_hash"]
    assert token not in stored
    assert stored == auth_store.hash_invite_token(token)


def test_listing_invites_never_returns_tokens(client, seeded_db):
    _login_admin(client)
    token = _mint_invite(client)
    body = client.get("/api/admin/invites").text
    assert token not in body
    assert "token_hash" not in body


def test_only_admins_may_mint_invites(client, seeded_db):
    """Otherwise a viewer could invite themselves an admin account."""
    _login_admin(client)
    token = _mint_invite(client)
    client.post("/api/auth/logout")
    _register(client, "viewer@example.com", token=token)

    response = client.post("/api/admin/invites", json={"role": "admin"}, headers=_csrf(client))
    assert response.status_code == 403


def test_anonymous_callers_may_not_mint_invites(client, seeded_db):
    assert client.post("/api/admin/invites", json={"role": "admin"}).status_code == 401


# ---------------------------------------------------------------------------
# Shared rules
# ---------------------------------------------------------------------------


def test_registration_enforces_the_password_policy(client, empty_db):
    assert _register(client, "owner@example.com", password="short").status_code == 400


def test_registration_refuses_a_duplicate_email(client, seeded_db):
    _login_admin(client)
    token = _mint_invite(client)
    client.post("/api/auth/logout")
    assert _register(client, ADMIN_EMAIL, token=token).status_code == 409


def test_registration_is_audited(client, empty_db):
    _register(client, "owner@example.com")
    _register(client, "rejected@example.com")
    with auth_store.connect() as con:
        events = [row["event"] for row in auth_store.list_audit(con)]
    assert "register.succeeded" in events
    assert "register.rejected" in events


def test_registration_never_echoes_the_password(client, empty_db):
    assert PASSWORD not in _register(client, "owner@example.com").text
