"""
Tests for CanonicalLogMiddleware — emits one canonical log line per HTTP request.

Every request through this middleware must emit exactly one INFO-level
"canonical" log record at the END of the request, carrying:
    method, path, status_code, duration_ms, request_id (via factory),
    + any fields set via set_canonical_field() during the request,
    + service (when configured).

Skipped: /health* and /metrics — no canonical line.
Skipped: non-http scopes (lifespan, websocket).
"""

import logging

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from shared.middleware.canonical_log import CanonicalLogMiddleware
from shared.utils.request_context import set_canonical_field


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_canonical_record(caplog) -> logging.LogRecord:
    """Return the single canonical record from caplog (asserts exactly one)."""
    records = [r for r in caplog.records if r.message == "canonical"]
    assert len(records) == 1, f"expected exactly 1 canonical log, got {len(records)}"
    return records[0]


def canonical_records(caplog) -> list:
    return [r for r in caplog.records if r.message == "canonical"]


def make_app(
    service_name: str = "",
    handler=None,
    path: str = "/",
    extra_routes: list = None,
):
    """Build a minimal Starlette app wrapped with CanonicalLogMiddleware."""

    async def default_handler(request: Request):
        return JSONResponse({"ok": True})

    routes = [Route(path, handler or default_handler)]
    if extra_routes:
        routes.extend(extra_routes)

    app = Starlette(routes=routes)
    app.add_middleware(CanonicalLogMiddleware, service_name=service_name)
    return app


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_canonical_log_emitted_on_200_get(caplog):
    caplog.set_level(logging.INFO)
    app = make_app(service_name="test_svc")

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    rec = get_canonical_record(caplog)
    assert rec.method == "GET"
    assert rec.path == "/"
    assert rec.status_code == 200
    assert isinstance(rec.duration_ms, float)
    assert rec.duration_ms >= 0.0
    # NOTE: `service` is stamped by the LogRecord factory in
    # logging_config.py (set by setup_logging). This unit test doesn't call
    # setup_logging, so the factory isn't installed and the field may be
    # absent. Service-level tests cover the production path.


def test_canonical_log_includes_method_path_status(caplog):
    caplog.set_level(logging.INFO)

    async def post_handler(request: Request):
        return JSONResponse({"created": True}, status_code=201)

    app = Starlette(routes=[Route("/", post_handler, methods=["POST"])])
    app.add_middleware(CanonicalLogMiddleware)

    with TestClient(app) as client:
        client.post("/")

    rec = get_canonical_record(caplog)
    assert rec.method == "POST"
    assert rec.path == "/"
    assert rec.status_code == 201


def test_canonical_log_does_not_pass_service_in_extras(caplog):
    """
    The middleware must NOT add `service` to the extras dict — the factory
    in logging_config.py handles it. This test would have failed with
    KeyError before the fix; it now passes because the middleware no longer
    sets `service` and the factory's value (whatever it is in the current
    test process) is allowed through cleanly.
    """
    caplog.set_level(logging.INFO)
    app = make_app(service_name="ignored_now")

    with TestClient(app) as client:
        client.get("/")

    # Must produce exactly one canonical record without raising KeyError.
    get_canonical_record(caplog)


# ---------------------------------------------------------------------------
# Status codes — error responses still emit canonical
# ---------------------------------------------------------------------------


def test_canonical_log_on_404_response(caplog):
    caplog.set_level(logging.INFO)

    async def not_found(request: Request):
        return JSONResponse({"error": "missing"}, status_code=404)

    app = make_app(handler=not_found)

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 404
    rec = get_canonical_record(caplog)
    assert rec.status_code == 404


def test_canonical_log_on_500_response(caplog):
    caplog.set_level(logging.INFO)

    async def server_error(request: Request):
        return PlainTextResponse("oops", status_code=500)

    app = make_app(handler=server_error)

    with TestClient(app) as client:
        client.get("/")

    rec = get_canonical_record(caplog)
    assert rec.status_code == 500


# ---------------------------------------------------------------------------
# Handler raises — canonical still emitted from finally
# ---------------------------------------------------------------------------


def test_canonical_log_when_handler_raises(caplog):
    caplog.set_level(logging.INFO)

    async def boom(request: Request):
        raise RuntimeError("kaboom")

    app = make_app(handler=boom)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/")

    assert response.status_code == 500
    rec = get_canonical_record(caplog)
    assert rec.method == "GET"
    assert rec.path == "/"
    # status_code is 500 (Starlette wrote it before re-raising) OR None
    assert rec.status_code in (500, None)


# ---------------------------------------------------------------------------
# Skip paths — NO canonical for health / metrics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skip_path",
    ["/health", "/health/full", "/health/db", "/health/redis", "/health/queue", "/metrics"],
)
def test_canonical_log_skipped_for_health_and_metrics(caplog, skip_path):
    caplog.set_level(logging.INFO)

    async def ok(request: Request):
        return JSONResponse({"ok": True})

    app = make_app(handler=ok, path=skip_path)

    with TestClient(app) as client:
        client.get(skip_path)

    assert canonical_records(caplog) == []


def test_canonical_log_emitted_for_non_skip_path(caplog):
    """Sanity check — non-skip path DOES emit canonical."""
    caplog.set_level(logging.INFO)
    app = make_app(path="/api/something")

    with TestClient(app) as client:
        client.get("/api/something")

    assert len(canonical_records(caplog)) == 1


# ---------------------------------------------------------------------------
# set_canonical_field() — business layers attach extra fields
# ---------------------------------------------------------------------------


def test_canonical_log_includes_fields_set_by_handler(caplog):
    caplog.set_level(logging.INFO)

    async def handler(request: Request):
        set_canonical_field("short_code", "abc123")
        set_canonical_field("cache", "hit")
        return JSONResponse({"ok": True})

    app = make_app(handler=handler)

    with TestClient(app) as client:
        client.get("/")

    rec = get_canonical_record(caplog)
    assert rec.short_code == "abc123"
    assert rec.cache == "hit"


def test_canonical_fields_isolated_per_request(caplog):
    """init_canonical_fields() must reset the dict per request."""
    caplog.set_level(logging.INFO)
    counter = {"n": 0}

    async def handler(request: Request):
        counter["n"] += 1
        if counter["n"] == 1:
            set_canonical_field("only_first", "x")
        else:
            set_canonical_field("only_second", "y")
        return JSONResponse({"ok": True})

    app = make_app(handler=handler)

    with TestClient(app) as client:
        client.get("/")
        client.get("/")

    recs = canonical_records(caplog)
    assert len(recs) == 2

    assert getattr(recs[0], "only_first", None) == "x"
    assert not hasattr(recs[0], "only_second")

    assert getattr(recs[1], "only_second", None) == "y"
    assert not hasattr(recs[1], "only_first")


# ---------------------------------------------------------------------------
# Multiple requests
# ---------------------------------------------------------------------------


def test_one_canonical_record_per_request(caplog):
    caplog.set_level(logging.INFO)
    app = make_app()

    with TestClient(app) as client:
        for _ in range(5):
            client.get("/")

    assert len(canonical_records(caplog)) == 5


# ---------------------------------------------------------------------------
# Non-HTTP scopes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_canonical_log_skipped_for_lifespan_scope(caplog):
    caplog.set_level(logging.INFO)
    called = {"app_called": False}

    async def downstream(scope, receive, send):
        called["app_called"] = True

    mw = CanonicalLogMiddleware(downstream, service_name="t")
    scope = {"type": "lifespan"}

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(msg):
        pass

    await mw(scope, receive, send)

    assert called["app_called"] is True
    assert canonical_records(caplog) == []


# ---------------------------------------------------------------------------
# request_id — comes from factory (contextvar), not extras
# ---------------------------------------------------------------------------


def test_canonical_record_has_request_id_attribute(caplog):
    """
    request_id MUST be present on the canonical record.

    In production, the LogRecord factory (logging_config.py) injects it from
    a contextvar. In this isolated unit test the factory isn't installed, so
    request_id comes from whatever path the middleware takes — either set on
    the record via extras (current buggy code) or via the factory (after fix).
    Either way, the attribute must exist.
    """
    caplog.set_level(logging.INFO)
    app = make_app()

    with TestClient(app) as client:
        client.get("/")

    rec = get_canonical_record(caplog)
    assert hasattr(rec, "request_id")
