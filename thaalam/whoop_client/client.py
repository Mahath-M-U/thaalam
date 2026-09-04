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
import time
from datetime import datetime, timezone
from typing import Any

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from thaalam.whoop_client.auth import WhoopAuth

logger = logging.getLogger(__name__)

API_BASE_URL = "https://api.prod.whoop.com/developer"

# WHOOP caps collection endpoints at 25 records per page.
MAX_PAGE_SIZE = 25

# Small pause between pages of a paginated request, to stay well under
# WHOOP's rate limit during a bulk historical sync.
PAGE_DELAY_SECONDS = 0.1

# WHOOP's default limits are 100 requests/minute and 10,000 requests/day; a
# 429 response reports which one via `X-RateLimit-Reset` (seconds until that
# limit resets). See https://developer.whoop.com/docs/developing/rate-limiting
MAX_RATE_LIMIT_RETRIES = 6

# If honoring a rate-limit reset would mean sleeping longer than this, it's
# almost certainly the 10,000/day cap rather than the 100/minute one -- raise
# a clear error instead of silently blocking for a long time.
MAX_AUTO_WAIT_SECONDS = 120.0


class WhoopClient(WhoopAuth):
    """Make authenticated requests to the WHOOP v2 data API."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
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
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all physiological cycles in the given date range (default: all)."""
        return self._get_paginated("v2/cycle", start_date, end_date)

    def get_recovery_for_cycle(self, cycle_id: int, *, optional: bool = False) -> dict[str, Any] | None:
        """Get the recovery associated with a cycle."""
        return self._get(f"v2/cycle/{cycle_id}/recovery", optional=optional)

    def get_sleep_for_cycle(self, cycle_id: int, *, optional: bool = False) -> dict[str, Any] | None:
        """Get the sleep associated with a cycle."""
        return self._get(f"v2/cycle/{cycle_id}/sleep", optional=optional)

    # ---- recovery -------------------------------------------------------------

    def get_recovery_collection(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all recovery records in the given date range (default: all)."""
        return self._get_paginated("v2/recovery", start_date, end_date)

    # ---- sleep -------------------------------------------------------------

    def get_sleep_by_id(self, sleep_id: str, *, optional: bool = False) -> dict[str, Any] | None:
        """Get a single sleep by ID."""
        return self._get(f"v2/activity/sleep/{sleep_id}", optional=optional)

    def get_sleep_collection(
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all sleeps in the given date range (default: all)."""
        return self._get_paginated("v2/activity/sleep", start_date, end_date)

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
        self, start_date: str | None = None, end_date: str | None = None
    ) -> list[dict[str, Any]]:
        """Get all workouts in the given date range (default: all)."""
        return self._get_paginated("v2/activity/workout", start_date, end_date)

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

        response = self.session.get(url, params=params)
        attempt = 0

        while response.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
            wait_seconds = _rate_limit_wait_seconds(response, attempt)

            if wait_seconds > MAX_AUTO_WAIT_SECONDS:
                raise RuntimeError(
                    "WHOOP rate limit exceeded and the reset is "
                    f"{wait_seconds / 60:.1f} minute(s) away -- likely the "
                    "10,000/day cap. Re-run the sync later; already-fetched "
                    "endpoints from this run are lost, but stored data is untouched."
                )

            logger.warning(
                "Rate limited by WHOOP (429) on %s; waiting %.1fs before retrying "
                "(attempt %d/%d)",
                url_slug, wait_seconds, attempt + 1, MAX_RATE_LIMIT_RETRIES,
            )
            time.sleep(wait_seconds)
            response = self.session.get(url, params=params)
            attempt += 1

        if optional and response.status_code == 404:
            return None
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        return data

    def _get_paginated(
        self, url_slug: str, start_date: str | None, end_date: str | None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": MAX_PAGE_SIZE}
        if start_date:
            params["start"] = _to_api_datetime(start_date)
        if end_date:
            params["end"] = _to_api_datetime(end_date)

        records: list[dict[str, Any]] = []
        page_number = 0

        while True:
            page = self._get(url_slug, params=dict(params))
            page_number += 1
            records.extend(page.get("records", []))
            logger.info(
                "%s: fetched page %d (%d records so far)",
                url_slug, page_number, len(records),
            )

            next_token = page.get("next_token")
            if not next_token:
                break

            params["nextToken"] = next_token
            time.sleep(PAGE_DELAY_SECONDS)

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
