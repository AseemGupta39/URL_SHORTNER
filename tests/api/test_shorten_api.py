"""
API tests for Shorten Service endpoints.
Tests HTTP layer with FastAPI TestClient.
"""
import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from shared.core.schemas import ShortenResponse


@pytest.fixture
def mock_url_service():
    """Mock URLService for testing API layer."""
    return AsyncMock()


@pytest.fixture
def test_client(mock_url_service):
    """Create test client with mocked URLService."""
    # Import app here to avoid import issues
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))

    # Mock the dependency to return our mock service directly
    def override_get_url_service():
        return mock_url_service

    from services.shorten.main import app
    from shared.config.dependencies import get_url_service

    app.dependency_overrides[get_url_service] = override_get_url_service
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


def test_health_check(test_client):
    """Test health check endpoint."""
    response = test_client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "shorten"
    assert data["status"] == "healthy"
    assert "datacenter_id" in data
    assert "worker_id" in data


def test_shorten_url_success(test_client, mock_url_service):
    """Test successful URL shortening."""
    mock_url_service.shorten.return_value = ShortenResponse(
        short_code="abc1234",
        short_url="https://short.ly/abc1234",
        created_at=datetime.now()
    )

    response = test_client.post(
        "/v1/shorten",
        json={"original_url": "https://example.com"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["short_code"] == "abc1234"
    assert data["short_url"] == "https://short.ly/abc1234"
    assert "created_at" in data

    mock_url_service.shorten.assert_called_once()


def test_shorten_url_with_query_params(test_client, mock_url_service):
    """Test shortening URL with query parameters."""
    mock_url_service.shorten.return_value = ShortenResponse(
        short_code="query01",
        short_url="https://short.ly/query01",
        created_at=datetime.now()
    )

    response = test_client.post(
        "/v1/shorten",
        json={"original_url": "https://example.com/path?foo=bar&baz=qux"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["short_code"] == "query01"


def test_shorten_url_invalid_url(test_client):
    """Test shortening with invalid URL format."""
    response = test_client.post(
        "/v1/shorten",
        json={"original_url": "not-a-valid-url"}
    )

    assert response.status_code == 422


def test_shorten_url_missing_url(test_client):
    """Test shortening without URL field."""
    response = test_client.post(
        "/v1/shorten",
        json={}
    )

    assert response.status_code == 422


def test_shorten_url_http_url(test_client, mock_url_service):
    """Test shortening HTTP (non-HTTPS) URL."""
    mock_url_service.shorten.return_value = ShortenResponse(
        short_code="http123",
        short_url="https://short.ly/http123",
        created_at=datetime.now()
    )

    response = test_client.post(
        "/v1/shorten",
        json={"original_url": "http://example.com"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["short_code"] == "http123"


def test_docs_endpoint_accessible(test_client):
    """Test that API docs are accessible."""
    response = test_client.get("/docs")
    assert response.status_code == 200


def test_redoc_endpoint_accessible(test_client):
    """Test that ReDoc is accessible."""
    response = test_client.get("/redoc")
    assert response.status_code == 200
