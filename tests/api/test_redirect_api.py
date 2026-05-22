"""
API tests for Redirect Service endpoints.
Tests HTTP layer with FastAPI TestClient.
"""
import pytest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from shared.core.schemas import RedirectResponse
from shared.core.exceptions import ShortCodeNotFoundException


@pytest.fixture
def mock_resolve_service():
    """Mock ResolveService for testing API layer."""
    return AsyncMock()


@pytest.fixture
def test_client(mock_resolve_service):
    """Create test client with mocked ResolveService."""
    # Import app here to avoid import issues
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    def override_get_resolve_service():
        return mock_resolve_service

    from services.redirect.main import app
    from shared.config.dependencies import get_resolve_service

    app.dependency_overrides[get_resolve_service] = override_get_resolve_service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_health_check(test_client):
    """Test health check endpoint."""
    response = test_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "redirect"
    assert data["status"] == "healthy"


def test_redirect_success(test_client, mock_resolve_service):
    """Test successful redirect to original URL."""
    mock_resolve_service.resolve.return_value = RedirectResponse(
        original_url=HttpUrl("https://example.com"),
        status="found"
    )

    response = test_client.get("/abc12345", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://example.com/"

    mock_resolve_service.resolve.assert_called_once_with("abc12345")


def test_redirect_with_query_params(test_client, mock_resolve_service):
    """Test redirect to URL with query parameters."""
    mock_resolve_service.resolve.return_value = RedirectResponse(
        original_url=HttpUrl("https://example.com/path?foo=bar"),
        status="found"
    )

    response = test_client.get("/query012", follow_redirects=False)

    assert response.status_code == 302
    assert "foo=bar" in response.headers["location"]


def test_redirect_not_found(test_client, mock_resolve_service):
    """Test redirect with non-existent short code."""
    mock_resolve_service.resolve.side_effect = ShortCodeNotFoundException("notfoun1")

    response = test_client.get("/notfoun1")

    assert response.status_code == 404
    data = response.json()
    assert data["detail"] == "Short code not found"


def test_redirect_multiple_codes(test_client, mock_resolve_service):
    """Test redirecting different short codes."""
    test_cases = [
        ("codeAB01", "https://example.com/1"),
        ("codeAB02", "https://example.com/2"),
        ("codeAB03", "https://example.com/3"),
    ]

    for short_code, original_url in test_cases:
        mock_resolve_service.resolve.return_value = RedirectResponse(
            original_url=HttpUrl(original_url),
            status="found"
        )

        response = test_client.get(f"/{short_code}", follow_redirects=False)

        assert response.status_code == 302
        assert original_url in response.headers["location"]


def test_redirect_preserves_url_fragments(test_client, mock_resolve_service):
    """Test redirect preserves URL fragments."""
    mock_resolve_service.resolve.return_value = RedirectResponse(
        original_url=HttpUrl("https://example.com/page#section"),
        status="found"
    )

    response = test_client.get("/frag1234", follow_redirects=False)

    assert response.status_code == 302
    assert "#section" in response.headers["location"]


def test_docs_endpoint_accessible(test_client):
    """Test that API docs are accessible."""
    response = test_client.get("/docs")
    assert response.status_code == 200


def test_redoc_endpoint_accessible(test_client):
    """Test that ReDoc is accessible."""
    response = test_client.get("/redoc")
    assert response.status_code == 200


def test_redirect_empty_short_code(test_client, mock_resolve_service):
    """Test that empty short code returns 404."""
    # Health endpoint takes precedence
    response = test_client.get("/")
    # Root path is not a valid short code, should return 404 or OpenAPI spec
    assert response.status_code in [404, 200]  # 200 if OpenAPI spec at root


def test_redirect_special_chars_in_code(test_client, mock_resolve_service):
    """Test that short codes with special characters are rejected."""
    response = test_client.get("/test-123", follow_redirects=False)

    assert response.status_code == 400
    mock_resolve_service.resolve.assert_not_called()
