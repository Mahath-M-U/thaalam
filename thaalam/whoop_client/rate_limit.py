"""Client-side pacing for WHOOP's published API rate limits.

WHOOP's default quota is 100 requests/minute and 10,000 requests/day
(https://developer.whoop.com/docs/developing/rate-limiting). A full
historical backfill is thousands of requests, so the client paces itself
*below* those limits rather than sprinting into a 429 and then waiting
out `X-RateLimit-Reset`: a request that is never sent costs nothing, a
429 costs the request plus the reset wait.

The minute budget is a sliding window (not a fixed one) because WHOOP's
own window does not line up with ours -- 90 requests at :59 followed by
90 at :01 is 180 requests in two seconds against any real limiter.

The day budget is process-local and resets on a UTC day boundary. It is
a floor, not a guarantee: WHOOP counts requests this process never made
(another instance, an earlier container). When it runs out we stop and
raise rather than burn the rest of the day's quota on 429s -- callers
persist their progress and resume on the next run.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

# WHOOP's own limits, for reference. Defaults below sit under them on purpose.
WHOOP_LIMIT_PER_MINUTE = 100
WHOOP_LIMIT_PER_DAY = 10_000


class WhoopRateLimitError(RuntimeError):
    """WHOOP refused a request because a rate limit was exhausted."""


class WhoopDailyLimitReached(WhoopRateLimitError):
    """The daily request budget is spent; resume after the UTC day rolls over.

    Raised *instead of* sending a request, so the caller can persist its
    progress and pick up where it left off on a later run.
    """

    def __init__(self, used: int, budget: int, seconds_until_reset: float) -> None:
        self.used = used
        self.budget = budget
        self.seconds_until_reset = seconds_until_reset
        super().__init__(
            f"WHOOP daily request budget spent ({used}/{budget}); it resets in "
            f"{seconds_until_reset / 3600:.1f}h. Progress so far is saved -- "
            "re-run the sync after the reset to continue."
        )


class RateLimiter:
    """Thread-safe sliding-window limiter for per-minute and per-day budgets."""

    def __init__(
        self,
        *,
        per_minute: int,
        per_day: int,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.per_minute = max(int(per_minute), 1)
        self.per_day = max(int(per_day), 1)
        self._sleep = sleep
        self._monotonic = monotonic
        self._utc_now = utc_now
        self._lock = threading.Lock()
        self._recent: deque[float] = deque()
        self._day = self._utc_now().date()
        self._day_used = 0

    # ---- budget ------------------------------------------------------------

    @property
    def requests_used_today(self) -> int:
        with self._lock:
            self._roll_day_locked()
            return self._day_used

    @property
    def requests_left_today(self) -> int:
        with self._lock:
            self._roll_day_locked()
            return max(self.per_day - self._day_used, 0)

    def _roll_day_locked(self) -> None:
        today = self._utc_now().date()
        if today != self._day:
            self._day = today
            self._day_used = 0

    def _seconds_until_utc_midnight(self) -> float:
        now = self._utc_now()
        tomorrow = datetime.combine(
            now.date(), datetime.min.time(), tzinfo=timezone.utc
        )
        return max((tomorrow.timestamp() + 86_400) - now.timestamp(), 0.0)

    # ---- acquisition -------------------------------------------------------

    def acquire(self) -> None:
        """Block until one request may be sent, then charge it to both budgets.

        Raises `WhoopDailyLimitReached` when the day budget is spent -- that
        wait is hours long, so it is the caller's decision, not a sleep.
        """
        while True:
            with self._lock:
                self._roll_day_locked()

                if self._day_used >= self.per_day:
                    raise WhoopDailyLimitReached(
                        self._day_used, self.per_day, self._seconds_until_utc_midnight()
                    )

                now = self._monotonic()
                while self._recent and now - self._recent[0] >= 60.0:
                    self._recent.popleft()

                if len(self._recent) < self.per_minute:
                    self._recent.append(now)
                    self._day_used += 1
                    return

                # Wait for the oldest request in the window to age out.
                wait_seconds = 60.0 - (now - self._recent[0]) + 0.01

            logger.debug(
                "Pacing WHOOP requests: %d/min budget reached, waiting %.2fs",
                self.per_minute, wait_seconds,
            )
            self._sleep(wait_seconds)

    def record_external_throttle(self) -> None:
        """Note that WHOOP 429'd us anyway, so the next minute is paced harder.

        A 429 means WHOOP's count is ahead of ours (another process, or a
        window that does not line up). Filling our own window makes the
        limiter wait out a full 60s before trying again instead of
        immediately spending the rest of the budget on more 429s.
        """
        with self._lock:
            self._roll_day_locked()
            now = self._monotonic()
            self._recent.clear()
            self._recent.extend([now] * self.per_minute)
