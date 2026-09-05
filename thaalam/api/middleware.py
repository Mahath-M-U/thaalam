"""Request-scoped logging context.

Gives every request a correlation id, logs one access line per request, and
returns the id in ``X-Request-ID`` so a user-visible error can be traced back
to a log entry without exposing internals.
"""

from __future__ import annotations

import logging
import re
import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

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
