"""
Canonical log middleware — emits one structured log line per request.

Each layer (cache, DB, service) writes fields into the request's canonical dict
via set_canonical_field(). This middleware drains all those fields into one log
line at request end — makes cross-request querying fast (one record per request).
"""
import logging
from starlette.types import ASGIApp, Scope, Receive, Send

from shared.utils.timer import Timer
from shared.utils.request_context import (
    init_canonical_fields,
    get_canonical_fields,
    clear_canonical_fields,
)

logger = logging.getLogger(__name__)

_SKIP_PATHS = {"/health", "/health/full", "/health/db", "/health/redis", "/health/queue", "/metrics"}


class CanonicalLogMiddleware:
    """
    Pure ASGI middleware. Must be added BEFORE RequestIDMiddleware so that
    request_id is still set in context when the canonical line is emitted.
    """

    def __init__(self, app: ASGIApp, service_name: str = "") -> None:
        self.app = app
        self.service_name = service_name

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        init_canonical_fields()
        timer = Timer()
        status_code = None

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round(timer.total(), 2)
            fields = get_canonical_fields()
            # NOTE: request_id is already on every LogRecord via the factory in
            # logging_config.py. Adding it here would raise KeyError.
            fields.update({
                "method": scope.get("method", ""),
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
            })
            if self.service_name:
                fields["service"] = self.service_name
            logger.info("canonical", extra=fields)
            clear_canonical_fields()