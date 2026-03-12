"""
Tests for ShortenService failure paths:
- Queue failure → sync DB fallback
- Queue + DB both fail → cache rollback
- Cache exception handling
- ID generation failure
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from pydantic import HttpUrl

from shared.core.services import ShortenService
from shared.core.schemas import ShortenResponse


@pytest.fixture
def mock_repository():
    repo = AsyncMock()
    repo.batch_create = AsyncMock(return_value=1)
    repo.get_pool_status = MagicMock(return_value={"pool_size": 5, "checked_in": 5})
    return repo


@pytest.fixture
def mock_cache():
    cache = AsyncMock()
    cache.set_async = AsyncMock(return_value=True)
    cache.delete_async = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def mock_queue():
    queue = AsyncMock()
    queue.enqueue = AsyncMock(return_value=True)
    return queue


@pytest.fixture
def mock_id_buffer():
    buf = AsyncMock()
    buf.get = AsyncMock(return_value="abc12345")
    return buf


@pytest.fixture
def service(mock_repository, mock_cache, mock_queue, mock_id_buffer):
    return ShortenService(
        url_repo=mock_repository,
        cache=mock_cache,
        queue=mock_queue,
        id_buffer=mock_id_buffer,
        base_domain="short.ly",
        base_url_scheme="https",
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_shorten_happy_path(_, service, mock_cache, mock_queue, mock_repository):
    result = await service.shorten(HttpUrl("https://example.com"))
    assert isinstance(result, ShortenResponse)
    assert result.short_code == "abc12345"
    assert result.short_url == "https://short.ly/abc12345"
    mock_cache.set_async.assert_called_once()
    mock_queue.enqueue.assert_called_once()
    mock_repository.batch_create.assert_not_called()


# ---------------------------------------------------------------------------
# Queue failure → sync DB fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_queue_failure_triggers_db_fallback(_, service, mock_queue, mock_repository):
    mock_queue.enqueue = AsyncMock(return_value=False)

    result = await service.shorten(HttpUrl("https://example.com"))

    assert isinstance(result, ShortenResponse)
    mock_repository.batch_create.assert_called_once()


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_queue_exception_triggers_db_fallback(_, service, mock_queue, mock_repository):
    mock_queue.enqueue = AsyncMock(side_effect=Exception("Redis down"))

    result = await service.shorten(HttpUrl("https://example.com"))

    assert isinstance(result, ShortenResponse)
    mock_repository.batch_create.assert_called_once()


# ---------------------------------------------------------------------------
# Queue + DB both fail → cache rollback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_queue_and_db_fail_rolls_back_cache(_, service, mock_queue, mock_repository, mock_cache):
    mock_queue.enqueue = AsyncMock(return_value=False)
    mock_repository.batch_create = AsyncMock(side_effect=Exception("DB error"))
    mock_cache.set_async = AsyncMock(return_value=True)

    with pytest.raises(Exception, match="DB error"):
        await service.shorten(HttpUrl("https://example.com"))

    mock_cache.delete_async.assert_called_once_with("abc12345")


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_queue_and_db_fail_no_rollback_when_cache_failed(_, service, mock_queue, mock_repository, mock_cache):
    """If cache also failed, no rollback needed (nothing to roll back)."""
    mock_queue.enqueue = AsyncMock(return_value=False)
    mock_repository.batch_create = AsyncMock(side_effect=Exception("DB error"))
    mock_cache.set_async = AsyncMock(return_value=False)

    with pytest.raises(Exception, match="DB error"):
        await service.shorten(HttpUrl("https://example.com"))

    mock_cache.delete_async.assert_not_called()


# ---------------------------------------------------------------------------
# Cache exception handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_cache_exception_does_not_prevent_success(_, service, mock_cache, mock_queue):
    """Cache raising an exception is handled — queue still succeeds, response returned."""
    mock_cache.set_async = AsyncMock(side_effect=Exception("Redis down"))

    result = await service.shorten(HttpUrl("https://example.com"))

    assert isinstance(result, ShortenResponse)
    mock_queue.enqueue.assert_called_once()


# ---------------------------------------------------------------------------
# ID generation failure
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_id_buffer_failure_raises(_, service, mock_id_buffer):
    mock_id_buffer.get = AsyncMock(side_effect=RuntimeError("buffer empty"))

    with pytest.raises(RuntimeError, match="buffer empty"):
        await service.shorten(HttpUrl("https://example.com"))


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_short_url_uses_correct_scheme_and_domain(_, mock_repository, mock_cache, mock_queue, mock_id_buffer):
    svc = ShortenService(
        url_repo=mock_repository,
        cache=mock_cache,
        queue=mock_queue,
        id_buffer=mock_id_buffer,
        base_domain="my.domain",
        base_url_scheme="http",
    )
    result = await svc.shorten(HttpUrl("https://example.com"))
    assert result.short_url == "http://my.domain/abc12345"


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_response_created_at_is_datetime(_, service):
    result = await service.shorten(HttpUrl("https://example.com"))
    assert isinstance(result.created_at, datetime)


# ---------------------------------------------------------------------------
# Nested failure: cache rollback itself fails
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_cache_rollback_failure_still_raises_original_db_error(_, service, mock_queue, mock_repository, mock_cache):
    """Even if cache delete fails, the original DB error is still raised."""
    mock_queue.enqueue = AsyncMock(return_value=False)
    mock_repository.batch_create = AsyncMock(side_effect=Exception("DB error"))
    mock_cache.set_async = AsyncMock(return_value=True)
    mock_cache.delete_async = AsyncMock(return_value=False)  # rollback also fails

    with pytest.raises(Exception, match="DB error"):
        await service.shorten(HttpUrl("https://example.com"))

    mock_cache.delete_async.assert_called_once_with("abc12345")


# ---------------------------------------------------------------------------
# ID generation fails before short_code is assigned (NameError branch)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_id_buffer_exception_before_short_code_assigned_raises(_, mock_repository, mock_cache, mock_queue):
    """When id_buffer.get() raises, short_code is never set — NameError branch in except."""
    buf = AsyncMock()
    buf.get = AsyncMock(side_effect=RuntimeError("buffer drained"))

    svc = ShortenService(
        url_repo=mock_repository,
        cache=mock_cache,
        queue=mock_queue,
        id_buffer=buf,
        base_domain="short.ly",
        base_url_scheme="https",
    )

    with pytest.raises(RuntimeError, match="buffer drained"):
        await svc.shorten(HttpUrl("https://example.com"))

    # Cache and queue should never have been touched
    mock_cache.set_async.assert_not_called()
    mock_queue.enqueue.assert_not_called()
