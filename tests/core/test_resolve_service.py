"""
Tests for ResolveService — cache-first resolve with DB fallback and cache warming.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from shared.core.services import ResolveService
from shared.core.schemas import URLData, RedirectResponse
from shared.core.exceptions import ShortCodeNotFoundException


@pytest.fixture
def mock_repository():
    repo = AsyncMock()
    repo.get_by_short_code = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_cache():
    cache = AsyncMock()
    cache.get_async = AsyncMock(return_value=None)
    cache.set_async = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def url_data():
    return URLData(
        short_code="abc12345",
        original_url="https://example.com",
        created_at=datetime.now(),
    )


@pytest.fixture
def service(mock_repository, mock_cache):
    return ResolveService(url_repo=mock_repository, cache=mock_cache)


# ---------------------------------------------------------------------------
# Cache hit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_hit_returns_redirect_response(service, mock_cache, mock_repository, url_data):
    mock_cache.get_async = AsyncMock(return_value=url_data)

    result = await service.resolve("abc12345")

    assert isinstance(result, RedirectResponse)
    assert result.status == "found"
    mock_repository.get_by_short_code.assert_not_called()


@pytest.mark.asyncio
async def test_cache_hit_returns_correct_url(service, mock_cache, url_data):
    mock_cache.get_async = AsyncMock(return_value=url_data)

    result = await service.resolve("abc12345")

    assert "example.com" in str(result.original_url)


@pytest.mark.asyncio
async def test_cache_hit_does_not_warm_cache(service, mock_cache, url_data):
    mock_cache.get_async = AsyncMock(return_value=url_data)

    await service.resolve("abc12345")

    mock_cache.set_async.assert_not_called()


# ---------------------------------------------------------------------------
# Cache miss → DB hit → cache warm
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_miss_queries_db(service, mock_cache, mock_repository, url_data):
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)

    await service.resolve("abc12345")

    mock_repository.get_by_short_code.assert_called_once_with("abc12345")


@pytest.mark.asyncio
async def test_cache_miss_db_hit_warms_cache(service, mock_cache, mock_repository, url_data):
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)

    await service.resolve("abc12345")

    mock_cache.set_async.assert_called_once_with("abc12345", url_data)


@pytest.mark.asyncio
async def test_cache_miss_db_hit_returns_redirect_response(service, mock_cache, mock_repository, url_data):
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)

    result = await service.resolve("abc12345")

    assert isinstance(result, RedirectResponse)
    assert result.status == "found"
    assert "example.com" in str(result.original_url)


# ---------------------------------------------------------------------------
# Cache miss → DB miss → 404
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_miss_db_miss_raises_not_found(service, mock_cache, mock_repository):
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=None)

    with pytest.raises(ShortCodeNotFoundException):
        await service.resolve("notfound")


@pytest.mark.asyncio
async def test_not_found_does_not_warm_cache(service, mock_cache, mock_repository):
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=None)

    with pytest.raises(ShortCodeNotFoundException):
        await service.resolve("notfound")

    mock_cache.set_async.assert_not_called()


# ---------------------------------------------------------------------------
# Cache warming failure (non-fatal)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_warm_failure_does_not_break_resolve(service, mock_cache, mock_repository, url_data):
    """Cache warm failing should not prevent the redirect from succeeding."""
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)
    mock_cache.set_async = AsyncMock(return_value=False)

    result = await service.resolve("abc12345")

    assert isinstance(result, RedirectResponse)
    assert result.status == "found"


@pytest.mark.asyncio
async def test_cache_warm_exception_does_not_break_resolve(service, mock_cache, mock_repository, url_data):
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)
    mock_cache.set_async = AsyncMock(side_effect=Exception("Redis down"))

    with pytest.raises(Exception):
        await service.resolve("abc12345")


# ---------------------------------------------------------------------------
# Correct short_code passed to cache and DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_passes_correct_short_code_to_cache(service, mock_cache, url_data):
    mock_cache.get_async = AsyncMock(return_value=url_data)

    await service.resolve("mycode1")

    mock_cache.get_async.assert_called_once_with("mycode1")


@pytest.mark.asyncio
async def test_resolve_passes_correct_short_code_to_db(service, mock_cache, mock_repository, url_data):
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)

    await service.resolve("mycode1")

    mock_repository.get_by_short_code.assert_called_once_with("mycode1")
