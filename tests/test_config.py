"""Settings resolution, environment unification, and production fail-fast."""

from __future__ import annotations

import pytest

from thaalam.config import (
    DEV_CORS_ORIGINS,
    DEV_FRONTEND_URL,
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
        "FRONTEND_URL",
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


# ---------------------------------------------------------------------------
# Where a finished OAuth round-trip sends the browser
# ---------------------------------------------------------------------------


def test_frontend_url_falls_back_to_the_dev_server_in_development():
    """Dev genuinely runs the frontend on a second origin."""
    assert Settings().resolved_frontend_url == DEV_FRONTEND_URL


def test_frontend_url_is_empty_in_production_when_unset(monkeypatch):
    """Never http://localhost:3001 -- that port exists only on a laptop.

    Empty means "use the origin the request arrived on", which is right
    because production serves the built frontend from that same origin.
    """
    monkeypatch.setenv("APP_ENV", "production")
    assert Settings().resolved_frontend_url == ""


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_configured_frontend_url_wins_and_loses_its_trailing_slash(
    monkeypatch, app_env
):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("FRONTEND_URL", "https://thaalam.example/")
    assert Settings().resolved_frontend_url == "https://thaalam.example"


# ---------------------------------------------------------------------------
# The assistant's API key
# ---------------------------------------------------------------------------


def test_the_assistant_is_off_when_no_key_is_set():
    """Absent is not an error: the dashboard simply hides the chat dock."""
    settings = Settings()
    assert settings.openrouter_api_key == ""
    assert settings.chat_configured is False


def test_the_canonical_key_name_is_read(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-canonical")
    settings = Settings()
    assert settings.openrouter_api_key == "sk-or-canonical"
    assert settings.chat_configured is True


def test_the_misspelled_key_name_still_works(monkeypatch):
    """`OPROUTER_API_KEY` is what shipped in .env.example and
    docker-compose.yml, so it is what existing deployments have set."""
    monkeypatch.setenv("OPROUTER_API_KEY", "sk-or-legacy")
    assert Settings().openrouter_api_key == "sk-or-legacy"


def test_the_canonical_key_wins_over_the_misspelled_one(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-canonical")
    monkeypatch.setenv("OPROUTER_API_KEY", "sk-or-legacy")
    assert Settings().openrouter_api_key == "sk-or-canonical"


def test_a_key_pasted_with_quotes_is_cleaned(monkeypatch):
    """Quotes typed into the Dokploy Environment UI become part of the value,
    which would make OpenRouter reject the key."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "'sk-or-quoted'")
    assert Settings().openrouter_api_key == "sk-or-quoted"


def test_a_blank_key_leaves_the_assistant_off(monkeypatch):
    """"Present but empty" must not read as configured."""
    monkeypatch.setenv("OPENROUTER_API_KEY", '" "')
    assert Settings().chat_configured is False


def test_the_assistant_can_be_disabled_with_the_key_left_in_place(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-canonical")
    monkeypatch.setenv("CHAT_ENABLED", "false")
    settings = Settings()
    assert settings.openrouter_api_key == "sk-or-canonical"
    assert settings.chat_configured is False


def test_no_model_is_pinned_by_default():
    """Blank is deliberate: the client discovers what is free at the time,
    because OpenRouter's free roster is rotated by its providers."""
    assert Settings().openrouter_model == ""
