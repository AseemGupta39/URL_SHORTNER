"""
Confirms /health/full returns 200, not a ResponseValidationError.

Pre-fix this fails because the endpoint is annotated `-> dict` while
check_all_dependencies returns a ServiceHealth model. Pydantic v2 refuses
to coerce the model into a dict, so FastAPI raises ResponseValidationError
and the endpoint returns 500.

The endpoint internally try/excepts dependency loading, so this test does
NOT need Postgres or Redis to be up. The bug is purely in the response
type annotation.
"""
from fastapi.testclient import TestClient


def test_shorten_health_full_returns_200():
    from services.shorten.main import app
    client = TestClient(app)

    response = client.get("/health/full")

    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}. Body: {response.text}"
    )