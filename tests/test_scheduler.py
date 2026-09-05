"""The nightly job actually runs.

Before this existed, `run_nightly_job` was reachable only from tests and its
own __main__ block, so derived baselines silently went stale forever. These
tests exist so that cannot quietly happen again.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from thaalam import config
from thaalam.api import scheduler


@pytest.fixture(autouse=True)
def _clean_settings(monkeypatch):
    for name in ("NIGHTLY_JOB_ENABLED", "NIGHTLY_JOB_HOUR", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    config.reset_settings_cache()
    yield
    config.reset_settings_cache()


def test_next_run_is_later_today_when_the_hour_has_not_passed():
    now = datetime(2026, 3, 1, 1, 0, 0)
    assert scheduler.seconds_until(4, now=now) == 3 * 3600


def test_next_run_rolls_to_tomorrow_once_the_hour_has_passed():
    now = datetime(2026, 3, 1, 5, 0, 0)
    assert scheduler.seconds_until(4, now=now) == 23 * 3600


def test_next_run_is_never_zero_or_negative():
    """Exactly on the hour must schedule tomorrow, not spin."""
    now = datetime(2026, 3, 1, 4, 0, 0)
    assert scheduler.seconds_until(4, now=now) == 24 * 3600


def test_the_app_starts_the_scheduler():
    """The regression that mattered: nothing was scheduling the job at all."""
    from fastapi.testclient import TestClient

    from thaalam.api.main import app

    with TestClient(app):
        state = scheduler.scheduler_state()
    assert state["next_run_at"] is not None, "startup must schedule a next run"


def test_the_scheduler_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("NIGHTLY_JOB_ENABLED", "false")
    config.reset_settings_cache()

    async def go():
        holder: set[asyncio.Task] = set()
        return scheduler.start(holder)

    assert asyncio.run(go()) is None


def test_a_failing_run_does_not_kill_the_loop(monkeypatch):
    """One bad night must not stop every night after it."""
    calls: list[int] = []

    def explode() -> dict:
        calls.append(1)
        raise RuntimeError("WHOOP unreachable")

    monkeypatch.setattr(scheduler, "_run_once", explode)
    monkeypatch.setattr(scheduler, "seconds_until", lambda *a, **k: 0.0)

    async def go():
        task = asyncio.create_task(scheduler._loop(4))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
    assert len(calls) > 1, "the loop must survive a failure and try again"
    assert scheduler.scheduler_state()["last_result"] == "failed"


def test_the_job_reuses_the_api_connection(monkeypatch):
    """DuckDB allows one writer; a second connect() in-process would fail."""
    seen: dict = {}

    class FakeCursor:
        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(
        "thaalam.api.deps.acquire_writable_connection", lambda: FakeCursor()
    )
    monkeypatch.setattr(
        "thaalam.services.nightly_job.run_nightly_job",
        lambda **kwargs: seen.update(kwargs) or {"skipped": True},
    )

    scheduler._run_once()
    assert isinstance(seen["con"], FakeCursor), "must hand the job a connection"
    assert seen["closed"], "and close the cursor afterwards"
