"""
Request ID middleware for FastAPI.

Automatically generates and sets a unique request ID for every incoming HTTP request.
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from shared.utils.request_context import generate_request_id, set_request_id, clear_request_id


class RequestIDMiddleware(BaseHTTPMiddleware):
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

    async def dispatch(self, request: Request, call_next):
        """Process request and inject request ID."""
        # Generate and set request ID for this request
        request_id = generate_request_id()
        set_request_id(request_id)

        try:
            # Process request
            response = await call_next(request)

            # Add request ID to response headers for client tracking
            response.headers["X-Request-ID"] = request_id

            return response

        finally:
            # Clean up context
            clear_request_id()
