"""
Request ID middleware — pure ASGI, no BaseHTTPMiddleware.

Automatically generates and sets a unique request ID for every incoming HTTP request.
"""
from starlette.types import ASGIApp, Scope, Receive, Send

from shared.utils.request_context import generate_request_id, set_request_id, clear_request_id


class RequestIDMiddleware:
    """
    Middleware that generates a unique request ID for every HTTP request.

    The request ID is:
    - Generated using UUID4 for guaranteed uniqueness
    - Stored in context variables (accessible via get_request_id())
    - Added to response headers as X-Request-ID
    - Automatically included in all log messages

    Usage:
        from fastapi import FastAPI
        from shared.middleware.request_id import RequestIDMiddleware

        app = FastAPI()
        app.add_middleware(RequestIDMiddleware)
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = generate_request_id()
        set_request_id(request_id)

        async def send_wrapper(message: Send) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            clear_request_id()
