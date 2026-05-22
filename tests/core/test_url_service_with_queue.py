"""
Test suite for ShortenService and ResolveService with queue integration.
Tests cache-first + queue-based batch processing flow.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, patch
from pydantic import HttpUrl

from shared.core.services import ShortenService, ResolveService
from shared.core.schemas import URLData, ShortenResponse, RedirectResponse
from shared.core.queue_messages import URLQueueMessage
from shared.utils.lru_cache import LRUCache


@pytest.fixture
def mock_repository():
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get_by_short_code = AsyncMock(return_value=None)
    repo.batch_create = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_cache():
    cache = AsyncMock(spec=LRUCache)
    cache.get_async = AsyncMock(return_value=None)
    cache.set_async = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def mock_queue():
    queue = AsyncMock()
    queue.enqueue = AsyncMock(return_value=True)
    queue.dequeue = AsyncMock(return_value=[])
    queue.size = AsyncMock(return_value=0)
    return queue


@pytest.fixture
def mock_id_buffer():
    buffer = AsyncMock()
    buffer.get = AsyncMock(return_value="abc123")
    return buffer


@pytest.fixture
def shorten_service(mock_repository, mock_cache, mock_queue, mock_id_buffer):
    return ShortenService(
        url_repo=mock_repository,
        cache=mock_cache,
        queue=mock_queue,
        id_buffer=mock_id_buffer,
        base_domain="short.ly",
        base_url_scheme="https",
    )


@pytest.fixture
def resolve_service(mock_repository, mock_cache):
    return ResolveService(
        url_repo=mock_repository,
        cache=mock_cache,
    )


# ---------------------------------------------------------------------------
# ShortenService tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="test-request-id")
async def test_shorten_url_with_queue(mock_req_id, shorten_service, mock_cache, mock_queue):
    """Test URL shortening writes to cache and queues for batch insert."""
    original_url = HttpUrl("https://example.com")

    result = await shorten_service.shorten(original_url)

    assert isinstance(result, ShortenResponse)
    assert result.short_code == "abc123"
    assert result.short_url == "https://short.ly/abc123"
    assert isinstance(result.created_at, datetime)

    mock_cache.set_async.assert_called_once()

    cached_data = mock_cache.set_async.call_args[0][1]
    assert isinstance(cached_data, URLData)
    assert cached_data.short_code == "abc123"
    assert cached_data.original_url == str(original_url)

    mock_queue.enqueue.assert_called_once()

    queued_data = mock_queue.enqueue.call_args[0][0]
    assert queued_data["short_code"] == "abc123"
    assert queued_data["original_url"] == str(original_url)
    assert "created_at" in queued_data


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="test-request-id")
async def test_shorten_url_queue_message_format(mock_req_id, shorten_service, mock_queue):
    """Test that queue message follows URLQueueMessage format."""
    original_url = HttpUrl("https://example.com")

    await shorten_service.shorten(original_url)

    queued_data = mock_queue.enqueue.call_args[0][0]

    msg = URLQueueMessage(**queued_data)
    assert msg.short_code == "abc123"
    assert msg.original_url == str(original_url)
    assert isinstance(msg.created_at, str)

    parsed_date = datetime.fromisoformat(msg.created_at)
    assert isinstance(parsed_date, datetime)


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="test-request-id")
async def test_multiple_shortens_unique_codes(mock_req_id, shorten_service, mock_id_buffer):
    """Test multiple shortens generate unique codes."""
    mock_id_buffer.get = AsyncMock(side_effect=["abc123", "def456", "ghi789"])

    urls = [
        HttpUrl("https://example1.com"),
        HttpUrl("https://example2.com"),
        HttpUrl("https://example3.com"),
    ]

    results = [await shorten_service.shorten(url) for url in urls]

    assert results[0].short_code == "abc123"
    assert results[1].short_code == "def456"
    assert results[2].short_code == "ghi789"
    assert len(set(r.short_code for r in results)) == 3


# ---------------------------------------------------------------------------
# ResolveService tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_url_cache_hit(resolve_service, mock_cache, mock_repository):
    """Test URL resolution with cache hit."""
    cached_data = URLData(
        short_code="abc123",
        original_url="https://example.com",
        created_at=datetime.now()
    )
    mock_cache.get_async = AsyncMock(return_value=cached_data)

    result = await resolve_service.resolve("abc123")

    assert isinstance(result, RedirectResponse)
    assert str(result.original_url) == "https://example.com/"
    assert result.status == "found"

    mock_cache.get_async.assert_called_once_with("abc123")
    mock_repository.get_by_short_code.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_url_cache_miss_db_hit(resolve_service, mock_cache, mock_repository):
    """Test URL resolution with cache miss but DB hit."""
    mock_cache.get_async = AsyncMock(return_value=None)

    db_data = URLData(
        short_code="abc123",
        original_url="https://example.com",
        created_at=datetime.now()
    )
    mock_repository.get_by_short_code = AsyncMock(return_value=db_data)

    result = await resolve_service.resolve("abc123")

    assert isinstance(result, RedirectResponse)
    assert str(result.original_url) == "https://example.com/"
    assert result.status == "found"

    mock_cache.get_async.assert_called_once_with("abc123")
    mock_repository.get_by_short_code.assert_called_once_with("abc123")
    mock_cache.set_async.assert_called_once()
