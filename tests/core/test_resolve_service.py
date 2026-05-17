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
    cache.set_async = AsyncMock(return_value=None)  # set_async now returns None, not bool
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
async def test_cache_warm_exception_does_not_break_resolve(service, mock_cache, mock_repository, url_data):
    """Cache warm raising must not prevent the redirect from succeeding (fail-open)."""
    mock_cache.get_async = AsyncMock(return_value=None)
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)
    mock_cache.set_async = AsyncMock(side_effect=Exception("Redis down"))

    # redirect must still succeed even if cache warm throws
    result = await service.resolve("abc12345")

    assert isinstance(result, RedirectResponse)
    assert result.status == "found"


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


# ---------------------------------------------------------------------------
# Cache get_async raises an exception — treat as miss, fall through to DB
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cache_get_exception_falls_through_to_db(service, mock_cache, mock_repository, url_data):
    """Redis GET error must be treated as a cache miss — redirect must still succeed via DB."""
    mock_cache.get_async = AsyncMock(side_effect=Exception("Redis connection lost"))
    mock_repository.get_by_short_code = AsyncMock(return_value=url_data)

    # must NOT raise — degrades to DB path
    result = await service.resolve("abc12345")

    assert isinstance(result, RedirectResponse)
    assert result.status == "found"
    mock_repository.get_by_short_code.assert_called_once_with("abc12345")


@pytest.mark.asyncio
async def test_cache_get_exception_db_miss_raises_not_found(service, mock_cache, mock_repository):
    """Redis GET error + DB miss = 404, not 500."""
    mock_cache.get_async = AsyncMock(side_effect=Exception("Redis connection lost"))
    mock_repository.get_by_short_code = AsyncMock(return_value=None)

    with pytest.raises(ShortCodeNotFoundException):
        await service.resolve("abc12345")
