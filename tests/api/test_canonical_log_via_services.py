"""
Service-level canonical-log tests — through the real shorten and redirect
FastAPI apps with CanonicalLogMiddleware actually wired in.

These tests prove the middleware works correctly when stitched into the
production service stack (service_name configured, RequestIDMiddleware
above it, skip paths matching production routes, etc.).

We mock the service-layer dependency so we don't need a real DB / Redis,
but we go through the full app + middleware chain.
"""

import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from shared.core.schemas import RedirectResponse, ShortenResponse


# Make `services.*` importable regardless of how pytest is launched
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_records(caplog) -> list:
    return [r for r in caplog.records if r.message == "canonical"]


def get_canonical_record(caplog) -> logging.LogRecord:
    recs = canonical_records(caplog)
    assert len(recs) == 1, f"expected exactly 1 canonical log, got {len(recs)}"
    return recs[0]


# ---------------------------------------------------------------------------
# Fixtures — shorten service
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_shorten_service():
    return AsyncMock()


@pytest.fixture
def shorten_client(mock_shorten_service):
    from services.shorten.main import app
    from shared.config.dependencies import get_shorten_service

    app.dependency_overrides[get_shorten_service] = lambda: mock_shorten_service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Fixtures — redirect service
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_resolve_service():
    return AsyncMock()


@pytest.fixture
def redirect_client(mock_resolve_service):
    from services.redirect.main import app
    from shared.config.dependencies import get_resolve_service

    app.dependency_overrides[get_resolve_service] = lambda: mock_resolve_service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Shorten service canonical log
# ---------------------------------------------------------------------------


def test_shorten_emits_canonical_with_service_name(
    caplog, shorten_client, mock_shorten_service
):
    """POST /v1/shorten emits one canonical record tagged service='shorten'."""
    caplog.set_level(logging.INFO)
    mock_shorten_service.shorten.return_value = ShortenResponse(
        short_code="abc12345",
        short_url="https://short.ly/abc12345",
        created_at=__import__("datetime").datetime.now(),
    )

    response = shorten_client.post(
        "/v1/shorten", json={"original_url": "https://example.com"}
    )

    assert response.status_code in (200, 201)
    rec = get_canonical_record(caplog)
    assert rec.service == "shorten"
    assert rec.method == "POST"
    assert rec.path == "/v1/shorten"
    assert rec.status_code == response.status_code


def test_shorten_health_does_not_emit_canonical(caplog, shorten_client):
    """/health on shorten service must not emit canonical."""
    caplog.set_level(logging.INFO)
    shorten_client.get("/health")
    assert canonical_records(caplog) == []


def test_shorten_invalid_url_still_emits_canonical(caplog, shorten_client):
    """Validation error (422) still gets a canonical line — finally runs."""
    caplog.set_level(logging.INFO)
    response = shorten_client.post("/v1/shorten", json={"original_url": "not-a-url"})
    assert response.status_code == 422

    rec = get_canonical_record(caplog)
    assert rec.service == "shorten"
    assert rec.status_code == 422


# ---------------------------------------------------------------------------
# Redirect service canonical log
# ---------------------------------------------------------------------------


def test_redirect_emits_canonical_with_service_name(
    caplog, redirect_client, mock_resolve_service
):
    """GET /:short_code emits one canonical record tagged service='redirect'."""
    caplog.set_level(logging.INFO)
    mock_resolve_service.resolve.return_value = RedirectResponse(
        original_url=HttpUrl("https://example.com"),
        status="found",
    )

    response = redirect_client.get("/abc12345", follow_redirects=False)

    assert response.status_code == 302
    rec = get_canonical_record(caplog)
    assert rec.service == "redirect"
    assert rec.method == "GET"
    assert rec.path == "/abc12345"
    assert rec.status_code == 302


def test_redirect_health_does_not_emit_canonical(caplog, redirect_client):
    caplog.set_level(logging.INFO)
    redirect_client.get("/health")
    assert canonical_records(caplog) == []


def test_redirect_not_found_still_emits_canonical(
    caplog, redirect_client, mock_resolve_service
):
    """A not-found short code still emits canonical with the failing status."""
    caplog.set_level(logging.INFO)
    from shared.core.exceptions import ShortCodeNotFoundException

    mock_resolve_service.resolve.side_effect = ShortCodeNotFoundException("nope")

    response = redirect_client.get("/notfound", follow_redirects=False)
    # status depends on how exception handler maps it — but a canonical line
    # must always be present
    rec = get_canonical_record(caplog)
    assert rec.service == "redirect"
    assert rec.status_code == response.status_code


# ---------------------------------------------------------------------------
# Cross-service: factory-injected request_id is present (NOT in extras)
# ---------------------------------------------------------------------------


def test_canonical_record_has_request_id_via_factory_shorten(
    caplog, shorten_client, mock_shorten_service
):
    """
    Locks in the rule: middleware does NOT pass request_id in extra={}.
    The factory in logging_config.py stamps it on every record from contextvar.
    """
    caplog.set_level(logging.INFO)
    mock_shorten_service.shorten.return_value = ShortenResponse(
        short_code="x" * 8,
        short_url="https://short.ly/xxxxxxxx",
        created_at=__import__("datetime").datetime.now(),
    )
    shorten_client.post(
        "/v1/shorten", json={"original_url": "https://example.com"}
    )

    rec = get_canonical_record(caplog)
    assert hasattr(rec, "request_id")
    assert isinstance(rec.request_id, str)
    assert rec.request_id != "-"  # RequestIDMiddleware sets it for HTTP paths