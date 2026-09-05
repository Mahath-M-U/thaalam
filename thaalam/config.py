"""Central application configuration.

One module decides what "production" means. Before this existed the answer
lived in ``whoop_client.auth._is_non_dev`` (reading ``THAALAM_ENV``/``ENV``)
while the rest of the app called ``os.getenv`` ad hoc, so a deployment could
set one variable, believe it was in production, and still get development-grade
handling of secrets elsewhere.

Domain tuning knobs -- insight thresholds, sync windows, ``STEPS_SOURCE`` --
deliberately stay as module-level constants in their own modules. They are not
security config; they are documented in ``.env.example``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Importing this module is what loads `.env` for the whole application, so
# modules that still read os.getenv directly keep working unchanged.
load_dotenv()

#: Where data lands when DATA_DIR is unset: alongside the repo checkout.
#:
#: This default is derived from the package location, which is right for a
#: source checkout and wrong for an installed package -- in a container
#: `pip install .` puts the package under site-packages, so an unset DATA_DIR
#: would write the database, token and logs there instead of the mounted
#: volume, and every redeploy would take the data with it. Deployments must
#: set DATA_DIR explicitly.
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Checked in order; the first non-empty one wins. `APP_ENV` is canonical,
#: the other two are the names the app shipped with.
ENV_VAR_ALIASES = ("APP_ENV", "THAALAM_ENV", "ENV")

#: Environment names that get production-grade secret handling.
NON_DEV_ENV_NAMES = frozenset({"prod", "production", "staging"})

_TRUTHY = frozenset({"1", "true", "yes", "on"})

DEV_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def resolve_app_env() -> str:
    """The active environment name, read live from the process environment.

    Read live rather than off the cached `Settings` because secret handling in
    `whoop_client.auth` is decided lazily, long after settings are first built.
    """
    for name in ENV_VAR_ALIASES:
        value = (os.getenv(name) or "").strip().lower()
        if value:
            return value
    return "development"


def is_non_dev() -> bool:
    """Whether to enforce production-grade secret handling."""
    if resolve_app_env() in NON_DEV_ENV_NAMES:
        return True
    return _truthy(os.getenv("WHOOP_REQUIRE_TOKEN_KEY"))


class Settings(BaseSettings):
    """Security- and runtime-relevant configuration."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    app_env: str = Field(
        default="development",
        validation_alias=AliasChoices(*ENV_VAR_ALIASES),
    )

    # WHOOP OAuth application credentials.
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""
    authorization_url: str = ""
    token_url: str = ""
    revoke_url: str = ""

    # WHOOP token encryption (see whoop_client.auth).
    whoop_token_key: str = ""
    whoop_token_key_file: str = ""
    whoop_require_token_key: bool = False

    # Web surface.
    frontend_url: str = "http://localhost:5173"
    allowed_origins: str = ""
    log_level: str = "INFO"

    # Session / login policy.
    cookie_secure: bool | None = None
    session_ttl_minutes: int = 720
    login_max_attempts: int = 5
    auth_db_path: str = ""

    #: Everything that must survive a redeploy: the DuckDB file, the encrypted
    #: WHOOP token, the auth database, and the logs.
    data_dir: str = ""

    # Request limits. The rate limiter counts in-process, which is correct
    # only because the app runs a single worker (DuckDB allows one writer).
    rate_limit_requests: int = 240
    rate_limit_window_seconds: int = 60
    max_request_bytes: int = 1_048_576
    allowed_hosts: str = ""

    # Nightly recompute. Runs in-process; disable it if you drive the job
    # from cron instead.
    nightly_job_enabled: bool = True
    nightly_job_hour: int = 4

    @property
    def trusted_hosts(self) -> list[str]:
        """Host allow-list, or empty to accept any Host header."""
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() in NON_DEV_ENV_NAMES

    @property
    def cors_origins(self) -> list[str]:
        """Explicit origins, else the Vite dev origins, else nothing.

        Empty in production is correct rather than broken: the packaged app
        serves the frontend from the same origin as the API, so no
        cross-origin allowance is needed.
        """
        configured = [o.strip() for o in self.allowed_origins.split(",") if o.strip()]
        if configured:
            return configured
        return [] if self.is_production else list(DEV_CORS_ORIGINS)

    @property
    def secure_cookies(self) -> bool:
        """Default to secure cookies in production, plain HTTP in dev."""
        if self.cookie_secure is None:
            return self.is_production
        return self.cookie_secure

    @property
    def resolved_data_dir(self) -> Path:
        if self.data_dir.strip():
            return Path(self.data_dir).expanduser()
        return DEFAULT_DATA_DIR

    @property
    def resolved_db_path(self) -> Path:
        return self.resolved_data_dir / "whoop.duckdb"

    @property
    def resolved_log_path(self) -> Path:
        return self.resolved_data_dir / "thaalam.log"

    @property
    def resolved_token_path(self) -> Path:
        return self.resolved_data_dir / "whoop_token.json"

    @property
    def resolved_auth_db_path(self) -> Path:
        """Auth database path -- deliberately a separate file from the DuckDB.

        DuckDB allows a single writer, so sharing that file would let a
        90-day WHOOP backfill block logins.
        """
        if self.auth_db_path.strip():
            return Path(self.auth_db_path).expanduser()
        return self.resolved_data_dir / "thaalam_auth.db"

    def validate_runtime(self) -> None:
        """Refuse to start with development-grade settings in production.

        Reports every problem at once so a deployment isn't fixed one restart
        at a time.
        """
        if not self.is_production:
            return

        problems: list[str] = []
        if "*" in self.cors_origins:
            problems.append("ALLOWED_ORIGINS must not contain '*'")
        if self.cookie_secure is False:
            problems.append(
                "COOKIE_SECURE must not be false -- session cookies would be "
                "sent over plain HTTP"
            )
        if not self.whoop_token_key.strip():
            problems.append(
                "WHOOP_TOKEN_KEY must be set -- refusing to mint a key file "
                "alongside the encrypted token"
            )
        # An installed package puts the default data directory inside
        # site-packages, which no sane deployment mounts as a volume: the
        # database, token and accounts would be silently discarded on the next
        # redeploy. Better to refuse to start than to lose the data later.
        if "site-packages" in self.resolved_data_dir.parts:
            problems.append(
                f"DATA_DIR must be set to a persistent path -- it currently "
                f"resolves inside the installed package "
                f"({self.resolved_data_dir}), which a redeploy would discard"
            )
        if problems:
            raise RuntimeError(
                f"Refusing to start with APP_ENV={self.app_env!r}:\n  - "
                + "\n  - ".join(problems)
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    """Drop the cached settings so a test can change the environment."""
    get_settings.cache_clear()
