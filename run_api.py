"""Start the Thaalam API server.

    uv run run_api.py

Development defaults to 127.0.0.1 with reload. Set APP_ENV=production (or
HOST/PORT) to bind for a container, where a reverse proxy terminates TLS.

Always a single worker. DuckDB allows one writer and the API holds one
process-wide writable connection, so a second worker would fight it for the
file; the in-process rate limiter counts per process for the same reason.
Scaling out means moving off DuckDB first.
"""

from __future__ import annotations

import os

import uvicorn

from thaalam.config import get_settings


def main() -> None:
    settings = get_settings()
    production = settings.is_production

    uvicorn.run(
        "thaalam.api.main:app",
        host=os.getenv("HOST") or ("0.0.0.0" if production else "127.0.0.1"),
        port=int(os.getenv("PORT") or 8000),
        reload=not production,
        workers=1,
        # Behind a proxy every request otherwise appears to come from the
        # proxy itself, which would break per-address login throttling and
        # make the access log useless.
        proxy_headers=production,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS") or ("*" if production else None),
    )


if __name__ == "__main__":
    main()
