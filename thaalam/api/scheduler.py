"""Runs the nightly recompute inside the API process.

Until this existed, `run_nightly_job` was reachable only from tests and its
own __main__ block -- nothing scheduled it, so baselines, bands, regressions
and the 30-day score series never recomputed on their own. Webhooks covered
new WHOOP records; the derived layer just went stale.

`python -m thaalam.services.nightly_job` still works, for anyone who would
rather drive it from cron.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from thaalam.config import get_settings

logger = logging.getLogger(__name__)

#: Last outcome and next due time, surfaced in the admin System tab.
_state: dict[str, Any] = {"last_run_at": None, "last_result": None, "next_run_at": None}


def scheduler_state() -> dict[str, Any]:
    return dict(_state)


def seconds_until(hour: int, *, now: datetime | None = None) -> float:
    """Seconds until the next occurrence of `hour` in local time."""
    current = now or datetime.now()
    target = current.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return (target - current).total_seconds()


def _run_once() -> dict[str, Any]:
    """Blocking body, run off the event loop.

    Uses the API's process-wide DuckDB connection: DuckDB allows one writer,
    so opening a second one here would fail.
    """
    from thaalam.api.deps import acquire_writable_connection
    from thaalam.services.nightly_job import run_nightly_job

    con = acquire_writable_connection()
    try:
        return run_nightly_job(con=con)
    finally:
        con.close()


async def _loop(hour: int) -> None:
    while True:
        delay = seconds_until(hour)
        _state["next_run_at"] = (
            datetime.now(tz=timezone.utc) + timedelta(seconds=delay)
        ).isoformat()
        await asyncio.sleep(delay)

        try:
            result = await asyncio.to_thread(_run_once)
            _state["last_run_at"] = datetime.now(tz=timezone.utc).isoformat()
            _state["last_result"] = "skipped" if result.get("skipped") else "ok"
            if result.get("skipped"):
                logger.warning("Nightly job skipped (%s)", result.get("reason"))
            else:
                logger.info("Nightly job finished: %s", result.get("reconciliation"))
        except asyncio.CancelledError:
            raise
        except Exception:
            # One bad night must not take the scheduler down with it.
            _state["last_run_at"] = datetime.now(tz=timezone.utc).isoformat()
            _state["last_result"] = "failed"
            logger.exception("Nightly job failed")


def start(loop_task: set[asyncio.Task]) -> asyncio.Task | None:
    """Start the nightly loop, unless it is switched off."""
    settings = get_settings()
    if not settings.nightly_job_enabled:
        logger.info("Nightly job disabled by configuration")
        return None

    task = asyncio.create_task(_loop(settings.nightly_job_hour))
    # Held so the task is not garbage collected mid-flight.
    loop_task.add(task)
    task.add_done_callback(loop_task.discard)
    logger.info("Nightly job scheduled for %02d:00 local", settings.nightly_job_hour)
    return task
