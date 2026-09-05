"""Request-scoped logging context.

Gives every request a correlation id, logs one access line per request, and
returns the id in ``X-Request-ID`` so a user-visible error can be traced back
to a log entry without exposing internals.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict, deque
from threading import Lock
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from thaalam.config import get_settings
from thaalam.logging_config import current_user_var, request_id_var

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"

#: An inbound id is echoed into logs, so it must not be able to forge log
#: structure or smuggle terminal escapes.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

#: Polled by container health checks; logging it at INFO would drown the file.
_QUIET_PATHS = frozenset({"/health"})


def _resolve_request_id(raw: str | None) -> str:
    if raw and _SAFE_REQUEST_ID.match(raw):
        return raw
    return uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        request_token = request_id_var.set(request_id)
        user_token = current_user_var.set("")
        started = time.perf_counter()

        # The path only, never the query string: the WHOOP OAuth callback
        # carries the authorization code there.
        path = request.url.path
        client_ip = request.client.host if request.client else None
        level = logging.DEBUG if path in _QUIET_PATHS else logging.INFO

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Request failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "client_ip": client_ip,
                    "user": current_user_var.get(),
                },
            )
            raise
        else:
            logger.log(
                level,
                "%s %s -> %s",
                request.method,
                path,
                response.status_code,
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "client_ip": client_ip,
                    "user": current_user_var.get(),
                },
            )
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            request_id_var.reset(request_token)
            current_user_var.reset(user_token)


#: `style-src` allows inline styles because Recharts sets them on the elements
#: it renders. Scripts get no such exemption.
_CSP = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "img-src 'self' data:",
        "font-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",
        "script-src 'self'",
        "connect-src 'self'",
    )
)

_SECURITY_HEADERS = {
    "Content-Security-Policy": _CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), interest-cohort=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Baseline hardening headers, plus no-store on API responses."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)

        settings = get_settings()
        if settings.is_production:
            # Only meaningful over TLS, which production terminates upstream.
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )

        # Health data must not sit in a shared cache or come back via the
        # back button after sign-out.
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized bodies before they are read into memory."""

    async def dispatch(self, request: Request, call_next) -> Response:
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                length = int(declared)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
            if length > get_settings().max_request_bytes:
                return JSONResponse({"detail": "Request body too large"}, status_code=413)
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window request cap per client address.

    Counters live in this process, which is correct only because the app runs
    a single worker -- DuckDB allows one writer, so it cannot be scaled out
    without the database change this deployment deliberately avoids.
    """

    #: Polled constantly by health checks and by WHOOP; neither should be able
    #: to exhaust a human user's budget, and both are cheap.
    EXEMPT_PATHS = frozenset({"/health"})

    def __init__(self, app) -> None:
        super().__init__(app)
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _over_limit(self, key: str, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return True
            hits.append(now)
            if not hits:
                self._hits.pop(key, None)
        return False

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in self.EXEMPT_PATHS:
            return await call_next(request)

        settings = get_settings()
        limit = settings.rate_limit_requests
        if limit <= 0:
            return await call_next(request)

        key = request.client.host if request.client else "unknown"
        window = float(settings.rate_limit_window_seconds)
        if self._over_limit(key, limit, window):
            logger.warning(
                "Rate limit exceeded",
                extra={"client_ip": key, "path": request.url.path},
            )
            return JSONResponse(
                {"detail": "Too many requests"},
                status_code=429,
                headers={"Retry-After": str(settings.rate_limit_window_seconds)},
            )
        return await call_next(request)
