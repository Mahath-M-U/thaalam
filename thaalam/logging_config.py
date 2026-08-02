"""Logging setup for the WHOOP sync pipeline.

Configures the `thaalam` logger namespace with two handlers:

- A console handler, so progress is visible while a sync is running.
- A rotating file handler (`data/thaalam.log`), so past runs -- including
  rate-limit waits and failures -- can be reviewed later.

Every other module gets its logger via ``logging.getLogger(__name__)``,
which makes it a child of ``thaalam`` and inherits these handlers.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "thaalam.log"

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(log_path: str | Path | None = None, level: str | None = None) -> logging.Logger:
    """Configure logging once and return the `thaalam` logger.

    Safe to call more than once; only the first call attaches handlers, so
    re-importing modules during a single run won't duplicate log lines.
    """
    global _configured

    logger = logging.getLogger("thaalam")

    if _configured:
        return logger

    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    resolved_level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(resolved_level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

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
