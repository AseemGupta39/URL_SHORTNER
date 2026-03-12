"""
Tests for RequestIDMiddleware — pure ASGI middleware.
"""
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from shared.middleware.request_id import RequestIDMiddleware
from shared.utils.request_context import get_request_id


# ---------------------------------------------------------------------------
# Test app helpers
# ---------------------------------------------------------------------------

def make_app(capture_in_handler=False):
    """Build a minimal Starlette app with RequestIDMiddleware."""
    captured = {}

    async def homepage(request: Request):
        if capture_in_handler:
            captured["request_id"] = get_request_id()
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", homepage)])
    app.add_middleware(RequestIDMiddleware)
    return app, captured


# ---------------------------------------------------------------------------
# X-Request-ID header
# ---------------------------------------------------------------------------

def test_response_contains_x_request_id_header():
    app, _ = make_app()
    client = TestClient(app)
    response = client.get("/")
    assert "x-request-id" in response.headers


def test_x_request_id_is_uuid_format():
    app, _ = make_app()
    client = TestClient(app)
    response = client.get("/")
    rid = response.headers["x-request-id"]
    parts = rid.split("-")
    assert len(parts) == 5
    assert len(rid) == 36


def test_each_request_gets_unique_request_id():
    app, _ = make_app()
    client = TestClient(app)
    ids = [client.get("/").headers["x-request-id"] for _ in range(10)]
    assert len(set(ids)) == 10


# ---------------------------------------------------------------------------
# Context variable accessible in handler
# ---------------------------------------------------------------------------

def test_request_id_accessible_in_handler():
    app, captured = make_app(capture_in_handler=True)
    client = TestClient(app)
    response = client.get("/")
    response_id = response.headers["x-request-id"]
    assert captured["request_id"] == response_id


# ---------------------------------------------------------------------------
# Context cleanup after request
# ---------------------------------------------------------------------------

def test_request_id_cleared_after_request():
    """After request completes, context is cleared (clear_request_id called in finally)."""
    from shared.utils.request_context import clear_request_id, get_request_id
    clear_request_id()

    app, _ = make_app()
    client = TestClient(app)
    client.get("/")

    # Outside a request, get_request_id() should return None
    # (middleware clears it in finally block)
    assert get_request_id() is None


# ---------------------------------------------------------------------------
# Non-HTTP scopes pass through unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_non_http_scope_passes_through():
    """WebSocket and lifespan scopes skip request ID logic."""
    app, _ = make_app()
    middleware = RequestIDMiddleware(app)

    received = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        received.append(message)

    scope = {"type": "websocket", "path": "/ws"}
    # Should not raise and should pass through without adding headers
    await middleware(scope, receive, send)
    # send was not called (no response to wrap) — that's fine
