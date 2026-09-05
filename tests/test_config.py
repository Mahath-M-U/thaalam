"""Settings resolution, environment unification, and production fail-fast."""

from __future__ import annotations

import pytest

from thaalam.config import (
    DEV_CORS_ORIGINS,
    Settings,
    is_non_dev,
    reset_settings_cache,
    resolve_app_env,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """Start every test from a known-empty environment."""
    for name in (
        "APP_ENV",
        "THAALAM_ENV",
        "ENV",
        "WHOOP_REQUIRE_TOKEN_KEY",
        "WHOOP_TOKEN_KEY",
        "ALLOWED_ORIGINS",
        "COOKIE_SECURE",
        "AUTH_DB_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_app_env_defaults_to_development():
    assert resolve_app_env() == "development"
    assert Settings().is_production is False


@pytest.mark.parametrize("var", ["APP_ENV", "THAALAM_ENV", "ENV"])
def test_every_env_alias_flips_production(monkeypatch, var):
    """The alias the app shipped with must keep working, not just APP_ENV."""
    monkeypatch.setenv(var, "production")
    assert resolve_app_env() == "production"
    assert is_non_dev() is True
    assert Settings().is_production is True


def test_app_env_wins_over_legacy_aliases(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("THAALAM_ENV", "production")
    assert resolve_app_env() == "development"
    assert Settings().is_production is False


def test_settings_and_token_handling_agree_on_production(monkeypatch):
    """The bug this module exists to prevent: two disagreeing prod switches."""
    monkeypatch.setenv("APP_ENV", "production")
    assert Settings().is_production == is_non_dev()


def test_require_token_key_flag_forces_non_dev(monkeypatch):
    monkeypatch.setenv("WHOOP_REQUIRE_TOKEN_KEY", "1")
    assert is_non_dev() is True
    # ...but it does not by itself make the app "production".
    assert Settings().is_production is False


def test_dev_defaults_to_vite_origins_and_insecure_cookies():
    settings = Settings()
    assert settings.cors_origins == list(DEV_CORS_ORIGINS)
    assert settings.secure_cookies is False


def test_production_defaults_to_no_cors_and_secure_cookies(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    settings = Settings()
    # Same-origin deployment needs no cross-origin allowance.
    assert settings.cors_origins == []
    assert settings.secure_cookies is True


def test_allowed_origins_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example , https://b.example")
    assert Settings().cors_origins == ["https://a.example", "https://b.example"]


def test_production_boot_rejects_wildcard_origin(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WHOOP_TOKEN_KEY", "x" * 44)
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match=r"ALLOWED_ORIGINS"):
        Settings().validate_runtime()


def test_production_boot_rejects_insecure_cookies(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("WHOOP_TOKEN_KEY", "x" * 44)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError, match=r"COOKIE_SECURE"):
        Settings().validate_runtime()


def test_production_boot_requires_token_key(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError, match=r"WHOOP_TOKEN_KEY"):
        Settings().validate_runtime()


def test_production_boot_reports_every_problem_at_once(monkeypatch):
    """One restart per misconfiguration is a bad deployment experience."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError) as excinfo:
        Settings().validate_runtime()
    message = str(excinfo.value)
    assert "ALLOWED_ORIGINS" in message
    assert "COOKIE_SECURE" in message
    assert "WHOOP_TOKEN_KEY" in message


def test_development_boot_never_fails():
    Settings().validate_runtime()


def test_auth_db_is_separate_from_the_duckdb_file():
    path = Settings().resolved_auth_db_path
    assert path.name == "thaalam_auth.db"
    assert path.suffix != ".duckdb"


def test_auth_db_path_override(monkeypatch, tmp_path):
    target = tmp_path / "custom_auth.db"
    monkeypatch.setenv("AUTH_DB_PATH", str(target))
    assert Settings().resolved_auth_db_path == target
