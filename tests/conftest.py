"""Ensure the repo root is on sys.path so `import thaalam` works.

This project isn't packaged/installed (no [build-system] in pyproject.toml),
same reason `scripts/tests_dbdata.py` needs an explicit sys.path shim.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from thaalam import db


@pytest.fixture
def tmp_db(tmp_path):
    con = db.get_connection(tmp_path / "whoop.duckdb")
    try:
        yield con
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Clear the shared app's rate-limit counters between tests.

    `thaalam.api.main.app` is a module-level singleton, and its
    `RateLimitMiddleware` keeps its hit counters in the instance. Every
    `TestClient(app)` in the suite therefore draws down one budget of
    RATE_LIMIT_REQUESTS per 60-second window, and since a full run takes well
    under a minute the counter only ever climbs. Left alone, the suite has a
    hard ceiling on its own total request count: adding tests anywhere starts
    returning 429 to unrelated tests elsewhere, and which ones fail depends on
    collection order.

    Resetting here makes each test independent of how many requests ran before
    it. Tests that exercise the limiter deliberately build their own app, so
    they are unaffected.
    """
    from thaalam.api.main import app
    from thaalam.api.middleware import RateLimitMiddleware

    # The instance lives inside the built middleware stack, reachable by
    # walking the `.app` chain. Nothing is asserted about finding it: before
    # the first request the stack may not be built yet, and a run with no HTTP
    # tests needs no reset.
    node = getattr(app, "middleware_stack", None)
    for _ in range(30):
        if node is None:
            break
        if isinstance(node, RateLimitMiddleware):
            with node._lock:
                node._hits.clear()
            break
        node = getattr(node, "app", None)
    yield
