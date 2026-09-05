"""Logging setup for the WHOOP sync pipeline and the API.

Configures the `thaalam` logger namespace with two handlers:

- A console handler, so progress is visible while a sync is running.
- A rotating file handler (`data/thaalam.log`), so past runs -- including
  rate-limit waits and failures -- can be reviewed later.

Every other module gets its logger via ``logging.getLogger(__name__)``,
which makes it a child of ``thaalam`` and inherits these handlers.

Outside development the output is JSON, one object per line, so a log shipper
can parse it. Every record passes through :func:`redact` first: this process
handles WHOOP OAuth tokens and password material, and a log file is a place
those must never reach.
"""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
from logging.handlers import RotatingFileHandler
from pathlib import Path

from thaalam.config import get_settings

DEFAULT_LOG_PATH = get_settings().resolved_log_path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

REDACTED = "[REDACTED]"

#: Per-request correlation id, attached to every record logged while handling
#: that request. Empty outside a request (CLI sync, nightly job).
request_id_var: ContextVar[str] = ContextVar("request_id", default="")

#: Who is making the request, once authentication exists.
current_user_var: ContextVar[str] = ContextVar("current_user", default="")

#: Structured fields the API middleware attaches via `extra=`.
_EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "client_ip")

# `\b` around the alternation keeps bare `token` from matching inside
# `access_token` (underscore is a word character), so each label redacts
# under its own name.
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)\b(client_secret|password|passwd|refresh_token|access_token|token_key"
    r"|authorization|cookie|set-cookie|api[_-]?key|secret|csrf[_-]?token"
    r"|session[_-]?token|token)\b\s*[=:]\s*(\"[^\"]*\"|'[^']*'|[^\s,;)}\]]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-~+/=]+")

_configured = False


@lru_cache(maxsize=1)
def _literal_secrets() -> tuple[str, ...]:
    """Exact secret values, so they're caught however they got interpolated.

    Pattern matching only catches secrets that appear next to a recognisable
    label; this catches the value on its own.
    """
    settings = get_settings()
    candidates = (settings.client_secret, settings.whoop_token_key)
    return tuple(value for value in candidates if value and len(value.strip()) >= 8)


def redact(text: str) -> str:
    """Strip secret material out of a log line."""
    if not text:
        return text
    # Labelled values first: redacting them by pattern consumes the whole
    # value, so a later literal pass can't chew a hole in the placeholder.
    text = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)
    text = _SECRET_KEY_PATTERN.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    for secret in _literal_secrets():
        text = text.replace(secret, REDACTED)
    return text


class RedactingFormatter(logging.Formatter):
    """Human-readable dev output, redacted."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class JsonFormatter(logging.Formatter):
    """One JSON object per line, redacted."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }

        request_id = getattr(record, "request_id", "") or request_id_var.get()
        if request_id:
            payload["request_id"] = request_id

        user = getattr(record, "user", "") or current_user_var.get()
        if user:
            payload["user"] = user

        for field in _EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))

        return json.dumps(payload, default=str)


def build_formatter(app_env: str | None = None) -> logging.Formatter:
    """JSON outside development, human-readable inside it."""
    env = app_env if app_env is not None else get_settings().app_env
    if env.strip().lower() == "development":
        return RedactingFormatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)
    return JsonFormatter()


def setup_logging(
    log_path: str | Path | None = None,
    level: str | None = None,
    *,
    force: bool = False,
) -> logging.Logger:
    """Configure logging once and return the `thaalam` logger.

    Safe to call more than once; only the first call attaches handlers, so
    re-importing modules during a single run won't duplicate log lines.
    """
    global _configured

    logger = logging.getLogger("thaalam")

    if _configured and not force:
        return logger

    if force:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    settings = get_settings()
    level_name = (level or settings.log_level).upper()
    resolved_level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(resolved_level)

    formatter = build_formatter(settings.app_env)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    resolved_path = Path(log_path) if log_path else DEFAULT_LOG_PATH
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        resolved_path, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Third-party HTTP libraries are noisy at DEBUG; keep them quieter than
    # whatever level `thaalam` itself is set to.
    logging.getLogger("urllib3").setLevel(max(resolved_level, logging.WARNING))

    logger.propagate = False
    _configured = True
    return logger
