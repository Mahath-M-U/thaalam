"""The background 90-day backfill after WHOOP OAuth connect records its own
outcome to the audit log -- success or failure -- rather than only logging,
so "connected, then nothing" is diagnosable from Administration -> Audit
instead of requiring the container's own logs.
"""

from __future__ import annotations

import pytest

from thaalam import config
from thaalam.api.routes import oauth
from thaalam.auth import store as auth_store


@pytest.fixture
def auth_db_path(tmp_path, monkeypatch):
    path = tmp_path / "auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(path))
    config.reset_settings_cache()
    yield path
    config.reset_settings_cache()


class _FakeClient:
    def close(self) -> None:
        pass


class _FakeConnection:
    def close(self) -> None:
        pass


def _patch_client_and_connection(monkeypatch):
    monkeypatch.setattr(oauth, "build_whoop_client", lambda: _FakeClient())
    monkeypatch.setattr(oauth, "acquire_writable_connection", lambda: _FakeConnection())


def test_backfill_success_is_audited(auth_db_path, monkeypatch):
    _patch_client_and_connection(monkeypatch)
    monkeypatch.setattr(
        oauth, "backfill_window", lambda client, days, con: {"records": 42, "mode": "backfill"}
    )
    monkeypatch.setattr(oauth, "recompute", lambda con, trigger: None)

    oauth._run_oauth_backfill(user_id=7)

    with auth_store.connect(auth_db_path) as con:
        rows = auth_store.list_audit(con, event="whoop.backfill_completed")
    assert len(rows) == 1
    assert rows[0]["user_id"] == 7
    assert "42" in rows[0]["detail"]


def test_backfill_failure_is_audited_with_the_real_error(auth_db_path, monkeypatch):
    _patch_client_and_connection(monkeypatch)

    def _raise(client, days, con):
        raise RuntimeError("WHOOP API returned 503")

    monkeypatch.setattr(oauth, "backfill_window", _raise)

    oauth._run_oauth_backfill(user_id=3)

    with auth_store.connect(auth_db_path) as con:
        rows = auth_store.list_audit(con, event="whoop.backfill_failed")
    assert len(rows) == 1
    assert rows[0]["user_id"] == 3
    assert "WHOOP API returned 503" in rows[0]["detail"]


def test_backfill_failure_does_not_also_record_success(auth_db_path, monkeypatch):
    """A failed backfill must not leave a misleading 'completed' row behind."""
    _patch_client_and_connection(monkeypatch)
    monkeypatch.setattr(
        oauth, "backfill_window", lambda client, days, con: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    oauth._run_oauth_backfill(user_id=1)

    with auth_store.connect(auth_db_path) as con:
        assert auth_store.list_audit(con, event="whoop.backfill_completed") == []
