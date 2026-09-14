"""Read-only client for the WHOOP v2 data API.

Extends `WhoopAuth` with the profile, body measurement, cycle,
recovery, sleep, and workout endpoints described at
https://developer.whoop.com/api. Collection endpoints are paginated
automatically using WHOOP's ``next_token`` cursor and capped at the
API's 25-record page size.

Built from scratch using `requests` (the `whoop` PyPI package is not
installed/used), taking inspiration from the API surface of
https://github.com/hedgertronic/whoop.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from thaalam.whoop_client.auth import WhoopAuth
from thaalam.whoop_client.rate_limit import (
    RateLimiter,
    WhoopDailyLimitReached,
    WhoopRateLimitError,  # noqa: F401  -- re-exported for callers catching either
)

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.prod.whoop.com/developer"

# WHOOP caps collection endpoints at 25 records per page.
MAX_PAGE_SIZE = 25

# WHOOP's default limits are 100 requests/minute and 10,000 requests/day; a
# 429 response reports which one via `X-RateLimit-Reset` (seconds until that
# limit resets). See https://developer.whoop.com/docs/developing/rate-limiting
#
# Rather than sprint into a 429 and wait out the reset, the client paces
# itself just under both limits (see `thaalam.whoop_client.rate_limit`). A
# full historical backfill is thousands of requests, so staying under the
# limit is what makes it finish at all.
REQUESTS_PER_MINUTE = int(os.getenv("WHOOP_REQUESTS_PER_MINUTE", "90"))
REQUESTS_PER_DAY = int(os.getenv("WHOOP_REQUESTS_PER_DAY", "9500"))

MAX_RATE_LIMIT_RETRIES = 6

# If honoring a rate-limit reset would mean sleeping longer than this, it's
# almost certainly the 10,000/day cap rather than the 100/minute one -- raise
# a clear error instead of silently blocking for a long time.
MAX_AUTO_WAIT_SECONDS = 120.0

# Called with (records, next_token) after each page of a paginated fetch.
# Returning False stops the walk early; anything else continues. A full
# historical backfill uses this to persist each page as it lands, so an
# interrupted run resumes from its last cursor instead of starting over.
PageCallback = Callable[[list[dict[str, Any]], "str | None"], "bool | None"]

# WHOOP counts requests per application, not per client object, and the API
# process builds a fresh `WhoopClient` for every sync, webhook and refresh.
# A limiter owned by the client would therefore start each of those with a
# full budget and cheerfully spend the day's quota several times over, so
# the budget is shared process-wide instead.
_SHARED_LIMITER: RateLimiter | None = None
_SHARED_LIMITER_LOCK = threading.Lock()


def shared_rate_limiter() -> RateLimiter:
    """The process-wide limiter every WHOOP request is paced by."""
    global _SHARED_LIMITER
    with _SHARED_LIMITER_LOCK:
        if _SHARED_LIMITER is None:
            _SHARED_LIMITER = RateLimiter(
                per_minute=REQUESTS_PER_MINUTE, per_day=REQUESTS_PER_DAY
            )
        return _SHARED_LIMITER


class WhoopClient(WhoopAuth):
    """Make authenticated requests to the WHOOP v2 data API."""

    def __init__(
        self, *args: Any, rate_limiter: RateLimiter | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)

        # 429 (rate limit) is handled explicitly in `_get()` using WHOOP's own
        # `X-RateLimit-Reset` header instead of generic backoff -- only
        # genuine transient server errors are retried automatically here.
        retries = Retry(
            total=5,
            backoff_factor=1.0,
            status_forcelist=[500, 502, 503, 504],
            respect_retry_after_header=True,
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retries))

        # Paces every request under WHOOP's published limits. Shared across
        # clients (see `shared_rate_limiter`); pass `rate_limiter=` to give a
        # client its own, which is mostly useful in tests.
        self.rate_limiter = rate_limiter or shared_rate_limiter()

    # ---- profile & body measurement ----------------------------------------

    def get_profile(self) -> dict[str, Any]:
        """Get the authenticated user's basic profile."""
        profile = self._get("v2/user/profile/basic")
        if profile is None:
            raise RuntimeError("WHOOP profile endpoint returned no data")
        return profile

    def get_body_measurement(self) -> dict[str, Any]:
        """Get the authenticated user's body measurements."""
        measurement = self._get("v2/user/measurement/body")
        if measurement is None:
            raise RuntimeError("WHOOP body measurement endpoint returned no data")
        return measurement

    # ---- activity ID mapping -----------------------------------------------

    def get_activity_mapping(self, activity_v1_id: int) -> dict[str, Any]:
        """Look up the v2 UUID for a legacy v1 activity ID."""
        return self._get(f"v1/activity-mapping/{activity_v1_id}")

    # ---- cycles -------------------------------------------------------------

    def get_cycle_by_id(self, cycle_id: int, *, optional: bool = False) -> dict[str, Any] | None:
        """Get a single physiological cycle by ID."""
        return self._get(f"v2/cycle/{cycle_id}", optional=optional)

    def get_cycle_collection(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        on_page: PageCallback | None = None,
        next_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all physiological cycles in the given date range (default: all)."""
        return self._get_paginated(
            "v2/cycle", start_date, end_date, on_page=on_page, next_token=next_token
        )

    def get_recovery_for_cycle(self, cycle_id: int, *, optional: bool = False) -> dict[str, Any] | None:
        """Get the recovery associated with a cycle."""
        return self._get(f"v2/cycle/{cycle_id}/recovery", optional=optional)

    def get_sleep_for_cycle(self, cycle_id: int, *, optional: bool = False) -> dict[str, Any] | None:
        """Get the sleep associated with a cycle."""
        return self._get(f"v2/cycle/{cycle_id}/sleep", optional=optional)

    # ---- recovery -------------------------------------------------------------

    def get_recovery_collection(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        on_page: PageCallback | None = None,
        next_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all recovery records in the given date range (default: all)."""
        return self._get_paginated(
            "v2/recovery", start_date, end_date, on_page=on_page, next_token=next_token
        )

    # ---- sleep -------------------------------------------------------------

    def get_sleep_by_id(self, sleep_id: str, *, optional: bool = False) -> dict[str, Any] | None:
        """Get a single sleep by ID."""
        return self._get(f"v2/activity/sleep/{sleep_id}", optional=optional)

    def get_sleep_collection(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        on_page: PageCallback | None = None,
        next_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all sleeps in the given date range (default: all)."""
        return self._get_paginated(
            "v2/activity/sleep", start_date, end_date,
            on_page=on_page, next_token=next_token,
        )

    def get_sleep_stream(
        self, sleep_id: str, types: list[str] | None = None
    ) -> dict[str, Any]:
        """Get raw signal stream data for a sleep (heart rate, temperature, etc.)."""
        params = {"types": types} if types else None
        return self._get(f"v2/activity/sleep/{sleep_id}/stream", params=params)

    # ---- workouts -------------------------------------------------------------

    def get_workout_by_id(self, workout_id: str, *, optional: bool = False) -> dict[str, Any] | None:
        """Get a single workout by ID."""
        return self._get(f"v2/activity/workout/{workout_id}", optional=optional)

    def get_workout_collection(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        *,
        on_page: PageCallback | None = None,
        next_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get all workouts in the given date range (default: all)."""
        return self._get_paginated(
            "v2/activity/workout", start_date, end_date,
            on_page=on_page, next_token=next_token,
        )

    # ---- internal helpers -------------------------------------------------------------

    def _get(
        self,
        url_slug: str,
        params: dict[str, Any] | None = None,
        *,
        optional: bool = False,
    ) -> dict[str, Any] | None:
        self.ensure_fresh_token()
        url = f"{API_BASE_URL}/{url_slug}"

        # Pace ourselves under WHOOP's limits before every send, retries
        # included -- a 429 we never provoke costs nothing to recover from.
        self.rate_limiter.acquire()
        response = self.session.get(url, params=params)
        attempt = 0

        while response.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
            # WHOOP counted requests we did not (another instance, a window
            # that does not line up); fill our own window so we back off for
            # a full minute rather than trading 429s.
            self.rate_limiter.record_external_throttle()
            wait_seconds = _rate_limit_wait_seconds(response, attempt)

            if wait_seconds > MAX_AUTO_WAIT_SECONDS:
                # A reset that far out is the daily cap, not the per-minute
                # one. Raise the same type the limiter raises when it stops
                # us itself, so callers treat a budget WHOOP enforced and one
                # we enforced identically: save progress, resume later.
                raise WhoopDailyLimitReached(
                    self.rate_limiter.requests_used_today,
                    self.rate_limiter.per_day,
                    wait_seconds,
                )

            logger.warning(
                "Rate limited by WHOOP (429) on %s; waiting %.1fs before retrying "
                "(attempt %d/%d)",
                url_slug, wait_seconds, attempt + 1, MAX_RATE_LIMIT_RETRIES,
            )
            time.sleep(wait_seconds)
            self.rate_limiter.acquire()
            response = self.session.get(url, params=params)
            attempt += 1

        if optional and response.status_code == 404:
            return None
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    def _get_paginated(
        self,
        url_slug: str,
        start_date: str | None,
        end_date: str | None,
        *,
        on_page: PageCallback | None = None,
        next_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Walk every page of a collection endpoint.

        With no `on_page`, every record is accumulated and returned -- the
        bounded-window behavior the incremental sync relies on. With an
        `on_page` callback the pages are handed over as they arrive and
        nothing is accumulated, which is what keeps a multi-year backfill
        from holding the whole history in memory; pass `next_token` to
        resume such a walk where a previous run stopped.
        """
        params: dict[str, Any] = {"limit": MAX_PAGE_SIZE}
        if start_date:
            params["start"] = _to_api_datetime(start_date)
        if end_date:
            params["end"] = _to_api_datetime(end_date)
        if next_token:
            params["nextToken"] = next_token

        records: list[dict[str, Any]] = []
        page_number = 0
        total = 0

        while True:
            page = self._get(url_slug, params=dict(params))
            page_records = page.get("records", [])
            page_number += 1
            total += len(page_records)
            token = page.get("next_token")

            logger.info(
                "%s: fetched page %d (%d records so far)", url_slug, page_number, total
            )

            if on_page is None:
                records.extend(page_records)
            elif on_page(page_records, token) is False:
                break

            if not token:
                break
            params["nextToken"] = token

        return records


def _rate_limit_wait_seconds(response: Any, attempt: int) -> float:
    """How long to wait before retrying a 429, per WHOOP's rate-limit headers.

    WHOOP reports the reset time via `X-RateLimit-Reset` (seconds), not the
    standard `Retry-After` header -- check both, then fall back to a capped
    exponential backoff if neither is present.
    """
    for header in ("X-RateLimit-Reset", "Retry-After"):
        value = response.headers.get(header)
        if value is not None:
            try:
                return max(float(value), 0.5)
            except ValueError:
                continue

    return min(2.0**attempt, 30.0)


def _to_api_datetime(value: str) -> str:
    """Normalize a `YYYY-MM-DD` or ISO datetime string to WHOOP's UTC `Z`-suffixed format."""
    raw = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(raw)
    parsed = (
        parsed.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None
        else parsed.astimezone(timezone.utc)
    )
    return parsed.isoformat().replace("+00:00", "Z")
