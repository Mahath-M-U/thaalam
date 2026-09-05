"""Auth core: password hashing, sessions, login policy, and the auth routes."""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from thaalam import config
from thaalam.api.main import app
from thaalam.auth import passwords
from thaalam.auth import sessions as session_store
from thaalam.auth import store as auth_store
from thaalam.auth.sessions import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE

PASSWORD = "correct-horse-battery-staple"
ADMIN_EMAIL = "admin@example.com"
VIEWER_EMAIL = "viewer@example.com"


@pytest.fixture
def auth_db_path(tmp_path, monkeypatch):
    """Point the app's auth database at a throwaway file.

    Redirecting the real path rather than overriding the dependency keeps the
    production connection handling -- a connection per request, which is what
    lets request threads work concurrently -- in the code under test.
    """
    path = tmp_path / "auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(path))
    config.reset_settings_cache()
    yield path
    config.reset_settings_cache()


@pytest.fixture
def auth_db(auth_db_path):
    """A direct connection for seeding and assertions."""
    with auth_store.connect(auth_db_path) as con:
        yield con


@pytest.fixture
def client(auth_db_path):
    with TestClient(app) as test_client:
        yield test_client


def _make_user(con, email=ADMIN_EMAIL, role="admin", password=PASSWORD, **kwargs) -> int:
    return auth_store.create_user(
        con,
        email=email,
        password_hash=passwords.hash_password(password),
        role=role,
        **kwargs,
    )


def _login(client, email=ADMIN_EMAIL, password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def test_password_round_trip():
    hashed = passwords.hash_password(PASSWORD)
    assert hashed != PASSWORD
    assert passwords.verify_password(hashed, PASSWORD)
    assert not passwords.verify_password(hashed, "wrong-password-entirely")


def test_hashes_are_salted_per_password():
    assert passwords.hash_password(PASSWORD) != passwords.hash_password(PASSWORD)


def test_short_passwords_are_rejected():
    with pytest.raises(passwords.WeakPasswordError):
        passwords.hash_password("short")


def test_absurdly_long_passwords_are_rejected():
    with pytest.raises(passwords.WeakPasswordError):
        passwords.hash_password("a" * (passwords.MAX_PASSWORD_LENGTH + 1))


def test_garbage_hash_never_verifies():
    assert not passwords.verify_password("not-a-hash", PASSWORD)
    assert passwords.needs_rehash("not-a-hash")


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def test_a_connection_can_be_used_and_closed_from_another_thread(auth_db_path):
    """FastAPI schedules sync dependencies across its threadpool.

    Setup, the route handler and teardown can each land on a different
    thread, so a connection opened during setup gets used and closed
    elsewhere. sqlite3 refuses that by default, which surfaced only under
    real parallel load: every request 500'd on teardown.
    """
    failures: list[Exception] = []
    manager = auth_store.connect(auth_db_path)
    con = manager.__enter__()

    def use_then_close() -> None:
        try:
            auth_store.count_users(con)
            manager.__exit__(None, None, None)
        except Exception as exc:  # noqa: BLE001 - reported through the list
            failures.append(exc)

    worker = threading.Thread(target=use_then_close)
    worker.start()
    worker.join()

    assert not failures, f"cross-thread use failed: {failures[0]}"


def test_parallel_requests_do_not_trip_over_each_other(client, auth_db):
    """The shape of the original report: several requests actually in flight."""
    _make_user(auth_db)
    _login(client)

    results: list[int] = []
    lock = threading.Lock()

    def hit() -> None:
        status = client.get("/api/auth/me").status_code
        with lock:
            results.append(status)

    threads = [threading.Thread(target=hit) for _ in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == [200] * 12


def test_session_token_is_never_stored_in_the_clear(auth_db):
    user_id = _make_user(auth_db)
    token, _ = session_store.create_session(auth_db, user_id=user_id, ttl_minutes=60)
    stored = auth_db.execute("SELECT token_hash FROM sessions").fetchone()["token_hash"]
    assert token not in stored
    assert stored == session_store.hash_token(token)


def test_session_lookup_returns_the_user(auth_db):
    user_id = _make_user(auth_db)
    token, csrf = session_store.create_session(auth_db, user_id=user_id, ttl_minutes=60)
    user = session_store.lookup_session(auth_db, token, ttl_minutes=60)
    assert user is not None
    assert user.email == ADMIN_EMAIL
    assert user.is_admin
    assert user.csrf_token == csrf


def test_unknown_and_empty_tokens_resolve_to_nothing(auth_db):
    assert session_store.lookup_session(auth_db, "nope", ttl_minutes=60) is None
    assert session_store.lookup_session(auth_db, "", ttl_minutes=60) is None


def test_revoked_session_stops_resolving(auth_db):
    user_id = _make_user(auth_db)
    token, _ = session_store.create_session(auth_db, user_id=user_id, ttl_minutes=60)
    session_store.revoke_session(auth_db, token)
    assert session_store.lookup_session(auth_db, token, ttl_minutes=60) is None


def test_expired_session_stops_resolving(auth_db):
    user_id = _make_user(auth_db)
    token, _ = session_store.create_session(auth_db, user_id=user_id, ttl_minutes=60)
    auth_db.execute(
        "UPDATE sessions SET expires_at = ?",
        (auth_store.to_iso(auth_store.utcnow() - timedelta(minutes=1)),),
    )
    auth_db.commit()
    assert session_store.lookup_session(auth_db, token, ttl_minutes=60) is None


def test_disabling_an_account_kills_its_live_sessions(auth_db):
    """Disabling must take effect now, not whenever the session lapses."""
    user_id = _make_user(auth_db)
    token, _ = session_store.create_session(auth_db, user_id=user_id, ttl_minutes=60)
    auth_store.update_user(auth_db, user_id, is_active=0)
    assert session_store.lookup_session(auth_db, token, ttl_minutes=60) is None


def test_revoke_user_sessions_can_spare_the_current_one(auth_db):
    user_id = _make_user(auth_db)
    keep, _ = session_store.create_session(auth_db, user_id=user_id, ttl_minutes=60)
    drop, _ = session_store.create_session(auth_db, user_id=user_id, ttl_minutes=60)
    kept = session_store.lookup_session(auth_db, keep, ttl_minutes=60)
    session_store.revoke_user_sessions(auth_db, user_id, except_session_id=kept.session_id)
    assert session_store.lookup_session(auth_db, keep, ttl_minutes=60) is not None
    assert session_store.lookup_session(auth_db, drop, ttl_minutes=60) is None


# ---------------------------------------------------------------------------
# Login route
# ---------------------------------------------------------------------------


def test_login_sets_an_httponly_session_cookie(client, auth_db):
    _make_user(auth_db)
    response = _login(client)
    assert response.status_code == 200
    assert response.json()["email"] == ADMIN_EMAIL
    assert response.json()["role"] == "admin"

    cookie_header = "; ".join(
        v for k, v in response.headers.items() if k.lower() == "set-cookie"
    )
    assert "httponly" in cookie_header.lower()
    assert SESSION_COOKIE in response.cookies
    # The CSRF cookie must stay readable so the client can echo it back.
    assert CSRF_COOKIE in response.cookies


def test_login_rejects_a_bad_password(client, auth_db):
    _make_user(auth_db)
    response = _login(client, password="not-the-right-password")
    assert response.status_code == 401
    assert SESSION_COOKIE not in response.cookies


def test_unknown_account_is_indistinguishable_from_a_bad_password(client, auth_db):
    """The login form must not become an account-enumeration oracle."""
    _make_user(auth_db)
    unknown = _login(client, email="nobody@example.com")
    wrong = _login(client, password="not-the-right-password")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


def test_disabled_account_cannot_log_in(client, auth_db):
    user_id = _make_user(auth_db)
    auth_store.update_user(auth_db, user_id, is_active=0)
    response = _login(client)
    assert response.status_code == 401
    # ...and says nothing about the account being disabled.
    assert response.json()["detail"] == "Incorrect email or password"


def test_repeated_failures_lock_the_account_out(client, auth_db):
    _make_user(auth_db)
    for _ in range(5):
        assert _login(client, password="wrong-password-here").status_code == 401
    throttled = _login(client, password="wrong-password-here")
    assert throttled.status_code == 429
    assert "Retry-After" in throttled.headers
    # Even the correct password is refused while locked out.
    assert _login(client).status_code == 429


def test_lockout_state_survives_a_restart(client, auth_db):
    """Throttling lives in the database, so bouncing the process can't clear it."""
    _make_user(auth_db)
    for _ in range(5):
        _login(client, password="wrong-password-here")
    with TestClient(app) as fresh_client:
        assert _login(fresh_client).status_code == 429


def test_a_success_clears_the_failure_count(client, auth_db):
    _make_user(auth_db)
    for _ in range(3):
        _login(client, password="wrong-password-here")
    assert _login(client).status_code == 200
    for _ in range(3):
        _login(client, password="wrong-password-here")
    # Still under the limit because counting restarts after the success.
    assert _login(client).status_code == 200


def test_login_is_audited(client, auth_db):
    _make_user(auth_db)
    _login(client, password="wrong-password-here")
    _login(client)
    events = [row["event"] for row in auth_store.list_audit(auth_db)]
    assert "login.succeeded" in events
    assert "login.failed.bad_password" in events


def test_password_is_never_echoed_back(client, auth_db):
    _make_user(auth_db)
    response = _login(client)
    assert PASSWORD not in response.text


# ---------------------------------------------------------------------------
# Identity, logout, CSRF
# ---------------------------------------------------------------------------


def test_me_requires_a_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_the_logged_in_user(client, auth_db):
    _make_user(auth_db)
    _login(client)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["email"] == ADMIN_EMAIL


def test_logout_revokes_the_session(client, auth_db):
    _make_user(auth_db)
    _login(client)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_logout_succeeds_without_a_session(client):
    """A client must always be able to reach a known signed-out state."""
    assert client.post("/api/auth/logout").status_code == 204


def test_unsafe_request_without_csrf_header_is_refused(client, auth_db):
    _make_user(auth_db)
    login = _login(client)
    client.cookies.delete(CSRF_COOKIE)
    response = client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    assert response.status_code == 403
    assert "CSRF" in response.json()["detail"]
    assert login.json()["csrf_token"]


def test_unsafe_request_with_a_wrong_csrf_token_is_refused(client, auth_db):
    _make_user(auth_db)
    _login(client)
    response = client.post(
        "/api/auth/password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
        headers={CSRF_HEADER: "forged-token"},
    )
    assert response.status_code == 403


def test_safe_requests_need_no_csrf_token(client, auth_db):
    _make_user(auth_db)
    _login(client)
    assert client.get("/api/auth/me").status_code == 200


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------


def _change_password(client, current, new):
    return client.post(
        "/api/auth/password",
        json={"current_password": current, "new_password": new},
        headers={CSRF_HEADER: client.cookies.get(CSRF_COOKIE)},
    )


def test_password_change_updates_the_credential(client, auth_db):
    _make_user(auth_db)
    _login(client)
    new_password = "an-entirely-new-password"
    assert _change_password(client, PASSWORD, new_password).status_code == 200

    client.post("/api/auth/logout")
    assert _login(client).status_code == 401
    assert _login(client, password=new_password).status_code == 200


def test_password_change_needs_the_current_password(client, auth_db):
    _make_user(auth_db)
    _login(client)
    response = _change_password(client, "wrong-current-password", "a-new-password-x")
    assert response.status_code == 401


def test_password_change_enforces_policy(client, auth_db):
    _make_user(auth_db)
    _login(client)
    response = _change_password(client, PASSWORD, "short")
    assert response.status_code == 400


def test_password_change_rejects_reuse(client, auth_db):
    _make_user(auth_db)
    _login(client)
    assert _change_password(client, PASSWORD, PASSWORD).status_code == 400


def test_password_change_revokes_other_sessions(client, auth_db):
    """Changing a password is how someone reacts to a suspected compromise."""
    user_id = _make_user(auth_db)
    other_token, _ = session_store.create_session(
        auth_db, user_id=user_id, ttl_minutes=60
    )
    _login(client)
    _change_password(client, PASSWORD, "an-entirely-new-password")

    assert session_store.lookup_session(auth_db, other_token, ttl_minutes=60) is None
    # The session that made the change stays usable.
    assert client.get("/api/auth/me").status_code == 200


def test_a_user_mid_forced_change_can_still_reach_the_auth_routes(client, auth_db):
    _make_user(auth_db, must_change_password=True)
    _login(client)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["must_change_password"] is True


def test_changing_the_password_clears_the_forced_flag(client, auth_db):
    _make_user(auth_db, must_change_password=True)
    _login(client)
    response = _change_password(client, PASSWORD, "an-entirely-new-password")
    assert response.status_code == 200
    assert response.json()["must_change_password"] is False


# ---------------------------------------------------------------------------
# Role and forced-change guards
# ---------------------------------------------------------------------------


def _user(role="admin", must_change_password=False):
    return session_store.AuthenticatedUser(
        id=1,
        email=ADMIN_EMAIL,
        role=role,
        must_change_password=must_change_password,
        session_id=1,
        csrf_token="csrf",
    )


def test_require_user_blocks_a_pending_password_change():
    """A bootstrap credential must not be usable for normal work."""
    from thaalam.api.deps import require_user

    with pytest.raises(HTTPException) as excinfo:
        require_user(_user(must_change_password=True))
    assert excinfo.value.status_code == 403

    assert require_user(_user()).email == ADMIN_EMAIL


def test_require_admin_rejects_a_viewer():
    from thaalam.api.deps import require_admin

    with pytest.raises(HTTPException) as excinfo:
        require_admin(_user(role="viewer"))
    assert excinfo.value.status_code == 403

    assert require_admin(_user(role="admin")).is_admin


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------


def test_bootstrap_creates_one_admin(auth_db_path, auth_db):
    from thaalam.auth import bootstrap

    email, generated = bootstrap.create_account("owner@example.com", None)
    assert generated, "a generated password must be reported back"

    row = auth_store.get_user_by_email(auth_db, email)
    assert row["role"] == "admin"
    # Generated credentials must be rotated before the account is usable.
    assert row["must_change_password"] == 1
    assert passwords.verify_password(row["password_hash"], generated)


def test_bootstrap_refuses_a_duplicate_account(auth_db_path):
    from thaalam.auth import bootstrap

    bootstrap.create_account(ADMIN_EMAIL, PASSWORD)
    with pytest.raises(SystemExit):
        bootstrap.create_account(ADMIN_EMAIL, PASSWORD)


def test_no_account_exists_until_bootstrap_runs(auth_db):
    """There are no default credentials shipped anywhere."""
    assert auth_store.count_users(auth_db) == 0
