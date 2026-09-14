"""Full-history import: does it reach back to activation, and stay under the limits?

The bug these cover: connecting an account used to import a fixed 90-day
window, so every record from before that window -- most of the history of
a strap someone has worn for years -- was simply never fetched.
"""

from __future__ import annotations

import pytest

from thaalam import db, sync
from thaalam.sync import (
    backfill_full_history,
    reconcile_recent,
    resume_history_if_pending,
    sync_all_historical_data,
)
from thaalam.whoop_client.rate_limit import RateLimiter, WhoopDailyLimitReached

USER_ID = 42

_ENTITY_ID_BASE = {"cycles": 1000, "recovery": 2000, "sleep": 3000, "workouts": 4000}


class FakePagedClient:
    """A WHOOP account with `pages_per_entity` pages of history per endpoint.

    Mirrors the real client's contract: `on_page(records, next_token)` per
    page, a `next_token` of None on the last page, and `next_token=` to
    resume a walk. `fail_after_pages` stops it the way the daily request
    budget does.
    """

    def __init__(self, pages_per_entity: int = 3, fail_after_pages: int | None = None):
        self.pages_per_entity = pages_per_entity
        self.fail_after_pages = fail_after_pages
        self.pages_served = 0
        self.calls: list[tuple[str, str | None, str | None, str | None]] = []

    def get_profile(self):
        return {"user_id": USER_ID, "email": "a@b.c", "first_name": "A", "last_name": "B"}

    def get_body_measurement(self):
        return {"height_meter": 1.7, "weight_kilogram": 65, "max_heart_rate": 190}

    def _collection(self, entity):
        def _fetch(start_date=None, end_date=None, *, on_page=None, next_token=None):
            self.calls.append((entity, start_date, end_date, next_token))
            if on_page is None:
                return []

            first = 0 if next_token is None else int(next_token.split("-")[-1])
            for index in range(first, self.pages_per_entity):
                if (
                    self.fail_after_pages is not None
                    and self.pages_served >= self.fail_after_pages
                ):
                    raise WhoopDailyLimitReached(9500, 9500, 3600.0)
                self.pages_served += 1
                last = index == self.pages_per_entity - 1
                # cycles/recovery are keyed by integer IDs, sleep/workouts by
                # WHOOP's v2 UUID strings -- keep both shapes honest so the
                # upserts here fail the same way the real ones would.
                numeric_id = _ENTITY_ID_BASE[entity] + index
                on_page(
                    [
                        {
                            "id": numeric_id if entity in ("cycles", "recovery")
                            else f"{entity}-{index}",
                            "cycle_id": numeric_id,
                            "sleep_id": f"sleep-uuid-{index}",
                            "user_id": USER_ID,
                            "start": f"{2018 + index}-01-01T00:00:00.000Z",
                            "end": f"{2018 + index}-01-02T00:00:00.000Z",
                            "score_state": "SCORED",
                            "score": {"strain": 10.0},
                        }
                    ],
                    None if last else f"{entity}-tok-{index + 1}",
                )
            return []

        return _fetch

    def __getattr__(self, name):
        for entity in ("cycle", "recovery", "sleep", "workout"):
            if name == f"get_{entity}_collection":
                return self._collection(
                    {"cycle": "cycles", "workout": "workouts"}.get(entity, entity)
                )
        raise AttributeError(name)


def _states(db_path):
    con = db.get_connection(db_path)
    try:
        return {e: db.get_sync_state(con, e) for _l, e in sync._COLLECTIONS}
    finally:
        con.close()


def test_connecting_imports_history_from_the_start_not_a_recent_window(tmp_path):
    """The regression: a connect must not stop at BACKFILL_DAYS ago."""
    client = FakePagedClient(pages_per_entity=3)
    result = backfill_full_history(client, tmp_path / "whoop.duckdb")

    assert result["skipped"] is False
    assert result["history_complete"] is True
    # 4 endpoints x 3 pages x 1 record.
    assert result["records"] == 12

    for entity, start, end, _token in client.calls:
        assert start == sync.HISTORY_START, f"{entity} asked for a truncated window"
        assert end is None, f"{entity} capped its history at an end date"


def test_history_is_marked_complete_so_it_is_not_walked_twice(tmp_path):
    db_path = tmp_path / "whoop.duckdb"
    client = FakePagedClient(pages_per_entity=2)
    backfill_full_history(client, db_path)

    for entity, state in _states(db_path).items():
        assert state["backfill_complete"] is True, entity
        assert state["backfill_cursor"] is None
        assert state["backfill_finished_at"] is not None

    # A second sync must fall through to bounded incremental fetches rather
    # than re-spending request budget on history it already holds.
    later = FakePagedClient(pages_per_entity=2)
    sync_all_historical_data(later, db_path, force=True)
    assert later.pages_served == 0
    assert all(token is None for _e, _s, _end, token in later.calls)


def test_an_interrupted_import_resumes_instead_of_starting_over(tmp_path):
    """Running out of daily budget must cost progress, not restart the years."""
    db_path = tmp_path / "whoop.duckdb"

    stopped = FakePagedClient(pages_per_entity=4, fail_after_pages=2)
    first = backfill_full_history(stopped, db_path)

    assert first["partial"] is True
    assert first["history_complete"] is False
    assert first["records"] == 2  # stored, not lost

    cycles = _states(db_path)["cycles"]
    assert cycles["backfill_complete"] is False
    assert cycles["backfill_cursor"] == "cycles-tok-2"
    assert cycles["backfill_records"] == 2

    # The next run picks up at the saved cursor.
    resumed = FakePagedClient(pages_per_entity=4)
    second = resume_history_if_pending(resumed, db_path)

    assert second["history_complete"] is True
    assert resumed.calls[0][3] == "cycles-tok-2", "resumed from the wrong page"
    # Two of the four cycle pages were already stored, so only two are re-read.
    assert sum(1 for e, *_rest in resumed.calls if e == "cycles") == 1
    assert _states(db_path)["cycles"]["backfill_records"] == 4


def test_a_finished_import_leaves_the_nightly_resume_a_no_op(tmp_path):
    db_path = tmp_path / "whoop.duckdb"
    backfill_full_history(FakePagedClient(pages_per_entity=1), db_path)

    idle = FakePagedClient(pages_per_entity=1)
    result = resume_history_if_pending(idle, db_path)

    assert result == {"skipped": True, "reason": "history_complete", "records": 0}
    assert idle.calls == []


def test_unfinished_history_is_never_skipped_by_the_interval_guard(tmp_path, monkeypatch):
    """The 'synced recently' guard is about *new* data, not missing history."""
    db_path = tmp_path / "whoop.duckdb"
    monkeypatch.setattr(sync, "MIN_SYNC_INTERVAL_MINUTES", 60.0)

    backfill_full_history(FakePagedClient(pages_per_entity=4, fail_after_pages=2), db_path)

    # Not forced, and every endpoint was just synced -- but history is owed.
    resumed = FakePagedClient(pages_per_entity=4)
    result = sync_all_historical_data(resumed, db_path)

    assert result["skipped"] is False
    assert result["history_complete"] is True


def test_reconciliation_stays_a_bounded_window(tmp_path):
    """The nightly 7-day re-read must not turn into a history walk."""
    db_path = tmp_path / "whoop.duckdb"
    client = FakePagedClient(pages_per_entity=3)
    reconcile_recent(client, db_path, days=7)

    assert client.pages_served == 0
    for _entity, start, end, token in client.calls:
        assert start is not None and end is not None
        assert token is None


# ---- pacing ---------------------------------------------------------------


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds

    def monotonic(self):
        return self.now


def test_the_limiter_keeps_a_burst_under_the_per_minute_quota():
    clock = _Clock()
    limiter = RateLimiter(
        per_minute=90, per_day=10_000, sleep=clock.sleep, monotonic=clock.monotonic
    )

    sent = []
    for _ in range(300):
        limiter.acquire()
        sent.append(clock.now)

    # The property that matters is not the average: it is that no 60-second
    # window anywhere in the run holds more than the quota.
    for index, at in enumerate(sent):
        in_window = sum(1 for other in sent[index:] if other - at < 60.0)
        assert in_window <= 90, f"{in_window} requests in the minute from {at}"


def test_a_sliding_window_blocks_the_burst_a_fixed_window_would_allow():
    """90 requests at :59 plus 90 at :01 is 180 in two seconds to WHOOP."""
    clock = _Clock()
    limiter = RateLimiter(
        per_minute=3, per_day=100, sleep=clock.sleep, monotonic=clock.monotonic
    )

    for _ in range(3):
        limiter.acquire()
    clock.now += 59.0
    limiter.acquire()

    assert clock.slept, "the fourth request went out inside the same minute"


def test_the_daily_budget_stops_rather_than_sleeping_for_hours():
    clock = _Clock()
    limiter = RateLimiter(
        per_minute=90, per_day=5, sleep=clock.sleep, monotonic=clock.monotonic
    )

    for _ in range(5):
        limiter.acquire()

    with pytest.raises(WhoopDailyLimitReached) as excinfo:
        limiter.acquire()
    assert "resumes" in str(excinfo.value) or "re-run" in str(excinfo.value)
    assert clock.slept == [], "a day-long wait must be the caller's decision"


def test_a_429_backs_the_limiter_off_for_a_full_minute():
    """WHOOP counting requests we did not must not be answered with more."""
    clock = _Clock()
    limiter = RateLimiter(
        per_minute=90, per_day=10_000, sleep=clock.sleep, monotonic=clock.monotonic
    )

    limiter.acquire()
    limiter.record_external_throttle()
    limiter.acquire()

    assert clock.slept and clock.slept[0] >= 60.0


def test_every_client_shares_one_daily_budget():
    """WHOOP counts per application; a per-client budget would multiply it."""
    from thaalam.whoop_client.client import WhoopClient

    token = {"access_token": "t", "refresh_token": "r", "expires_in": 99_999}
    first = WhoopClient("id", "secret", token=dict(token))
    second = WhoopClient("id", "secret", token=dict(token))
    try:
        assert first.rate_limiter is second.rate_limiter
        first.rate_limiter.acquire()
        assert second.rate_limiter.requests_used_today == 1
    finally:
        first.close()
        second.close()


def test_a_429_whose_reset_is_hours_away_is_treated_as_the_daily_cap(monkeypatch):
    """It must pause-and-resume, not surface as an opaque failure."""
    from thaalam.whoop_client.client import WhoopClient

    class _Response:
        status_code = 429
        headers = {"X-RateLimit-Reset": "7200"}

    client = WhoopClient(
        "id",
        "secret",
        token={"access_token": "t", "refresh_token": "r", "expires_in": 99_999},
    )
    try:
        monkeypatch.setattr(client.session, "get", lambda *_a, **_k: _Response())
        with pytest.raises(WhoopDailyLimitReached):
            client._get("v2/cycle")
    finally:
        client.close()
