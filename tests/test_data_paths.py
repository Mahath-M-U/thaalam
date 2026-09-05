"""Where persistent data lands.

Every path here has to follow DATA_DIR. The default is derived from the
package location, which is right for a source checkout and wrong for an
installed one: in a container `pip install .` puts the package under
site-packages, so an unset DATA_DIR would write the database, the WHOOP token
and every account next to the installed package instead of the mounted
volume -- and the next redeploy would take them with it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thaalam import config
from thaalam.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("DATA_DIR", "AUTH_DB_PATH", "APP_ENV", "WHOOP_TOKEN_KEY"):
        monkeypatch.delenv(name, raising=False)
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


def test_data_dir_defaults_to_the_checkout(monkeypatch):
    assert Settings().resolved_data_dir == config.DEFAULT_DATA_DIR


@pytest.mark.parametrize(
    "attribute,filename",
    [
        ("resolved_db_path", "whoop.duckdb"),
        ("resolved_log_path", "thaalam.log"),
        ("resolved_token_path", "whoop_token.json"),
        ("resolved_auth_db_path", "thaalam_auth.db"),
    ],
)
def test_every_persistent_path_follows_data_dir(monkeypatch, tmp_path, attribute, filename):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    resolved: Path = getattr(Settings(), attribute)
    assert resolved == tmp_path / filename


def test_auth_db_path_still_wins_over_data_dir(monkeypatch, tmp_path):
    """A deployment may keep the security database somewhere else entirely."""
    explicit = tmp_path / "elsewhere" / "auth.db"
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AUTH_DB_PATH", str(explicit))
    assert Settings().resolved_auth_db_path == explicit


def test_production_refuses_to_write_into_the_installed_package(monkeypatch, tmp_path):
    """The container bug this module exists for: silent data loss on redeploy."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WHOOP_TOKEN_KEY", "x" * 44)
    monkeypatch.setenv(
        "DATA_DIR", str(Path("/usr/local/lib/python3.12/site-packages/data"))
    )
    with pytest.raises(RuntimeError, match="DATA_DIR"):
        Settings().validate_runtime()


def test_production_accepts_a_persistent_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WHOOP_TOKEN_KEY", "x" * 44)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    Settings().validate_runtime()


def test_the_module_defaults_agree_with_settings(monkeypatch):
    """db and logging read their defaults at import; they must not drift."""
    from thaalam import db, logging_config

    settings = Settings()
    assert Path(db.DEFAULT_DB_PATH) == settings.resolved_db_path
    assert Path(logging_config.DEFAULT_LOG_PATH) == settings.resolved_log_path
