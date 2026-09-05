"""Nightly baseline recompute and 7-day WHOOP reconciliation.

Runnable as `run_nightly_job()` or `python -m thaalam.services.nightly_job`.
Re-fetches the last 7 days (WHOOP records stay editable) then recomputes
stored baselines. Band/regression slots stay empty until later PRs.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from thaalam import db
from thaalam.services.derived_metrics import recompute
from thaalam.sync import RECONCILE_DAYS, reconcile_recent

logger = logging.getLogger(__name__)


def run_nightly_job(
    db_path: str | Path | None = None,
    client: Any | None = None,
    *,
    reconcile_days: int = RECONCILE_DAYS,
    con: Any | None = None,
) -> dict[str, Any]:
    """Reconcile recent WHOOP rows, then recompute derived baselines.

    Pass `con` when running inside the API process: DuckDB allows a single
    writer, so a second connect() to the same file would fail against the
    process-wide connection the API already holds.
    """
    close_client = False
    if client is None:
        from thaalam.api.deps import build_whoop_client, is_whoop_connected

        if not is_whoop_connected():
            logger.warning("WHOOP is not connected; skipping nightly job")
            return {"skipped": True, "reason": "not_connected"}
        client = build_whoop_client()
        close_client = True

    try:
        if hasattr(client, "is_authenticated") and not client.is_authenticated():
            logger.warning("WHOOP client has no token; skipping nightly job")
            return {"skipped": True, "reason": "not_connected"}

        recon = reconcile_recent(client, db_path, days=reconcile_days, con=con)
        if con is not None:
            baselines = recompute(con, trigger="nightly")
        else:
            own = db.get_connection(db_path) if db_path is not None else db.get_connection()
            try:
                baselines = recompute(own, trigger="nightly")
            finally:
                own.close()
        return {"skipped": False, "reconciliation": recon, "baselines": baselines}
    finally:
        if close_client and hasattr(client, "close"):
            client.close()


if __name__ == "__main__":
    import thaalam.config  # noqa: F401  -- importing loads .env
    from thaalam.logging_config import setup_logging

    setup_logging()
    result = run_nightly_job()
    if result.get("skipped"):
        logger.warning("Nightly job skipped (%s)", result.get("reason"))
    else:
        logger.info("Nightly job finished: %s", result.get("reconciliation"))
