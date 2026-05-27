"""
Test suite for Redis queue functionality.
Tests queue operations with mock Redis client.
"""
import pytest
import json
from unittest.mock import AsyncMock, patch
from shared.utils.redis_queue import RedisQueue


@pytest.fixture
def redis_url():
    """Test Redis URL."""
    return "redis://localhost:6379/0"


@pytest.fixture
def mock_redis_client():
    """Create mock Redis client."""
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock()
    mock_client.rpush = AsyncMock(return_value=1)
    mock_client.lpop = AsyncMock(return_value=None)
    mock_client.llen = AsyncMock(return_value=0)
    mock_client.delete = AsyncMock(return_value=1)
    return mock_client


@pytest.mark.asyncio
async def test_redis_queue_initialization(redis_url):
    """Test Redis queue initialization."""
    queue = RedisQueue(redis_url, queue_name="test_queue")

    assert queue.redis_url == redis_url
    assert queue.queue_name == "test_queue"
    assert queue._client is None


@pytest.mark.asyncio
async def test_redis_queue_connect(redis_url, mock_redis_client):
    """Test Redis queue connection."""
    queue = RedisQueue(redis_url)

    async def mock_from_url(*args, **kwargs):
        return mock_redis_client

    with patch('shared.utils.redis_queue.aioredis.from_url', side_effect=mock_from_url):
        await queue.connect()

        assert queue._client is not None
        mock_redis_client.ping.assert_called_once()


@pytest.mark.asyncio
async def test_redis_queue_enqueue(redis_url, mock_redis_client):
    """Test enqueuing items to Redis queue."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client

    test_data = {
        "short_code": "abc123",
        "original_url": "https://example.com",
        "created_at": "2024-01-01T00:00:00"
    }

    await queue.enqueue(test_data)

    mock_redis_client.rpush.assert_called_once()

    call_args = mock_redis_client.rpush.call_args
    assert call_args[0][0] == "url_batch_queue"

    enqueued_data = json.loads(call_args[0][1])
    assert enqueued_data == test_data


@pytest.mark.asyncio
async def test_redis_queue_dequeue_single(redis_url, mock_redis_client):
    """Test dequeuing single item uses lpop (FIFO — removes oldest)."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client

    test_data = {"short_code": "abc123", "original_url": "https://example.com"}
    mock_redis_client.lpop = AsyncMock(return_value=json.dumps(test_data))

    result = await queue.dequeue(count=1)

    assert len(result) == 1
    assert result[0] == test_data
    mock_redis_client.lpop.assert_called_once_with("url_batch_queue")


@pytest.mark.asyncio
async def test_redis_queue_dequeue_multiple(redis_url, mock_redis_client):
    """Test dequeuing multiple items uses lpop (FIFO — removes oldest first)."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client

    test_data = [
        {"short_code": "abc123", "original_url": "https://example.com"},
        {"short_code": "def456", "original_url": "https://google.com"}
    ]
    mock_redis_client.lpop = AsyncMock(
        return_value=[json.dumps(item) for item in test_data]
    )

    result = await queue.dequeue(count=2)

    assert len(result) == 2
    assert result == test_data
    mock_redis_client.lpop.assert_called_once_with("url_batch_queue", 2)


@pytest.mark.asyncio
async def test_redis_queue_dequeue_empty(redis_url, mock_redis_client):
    """Test dequeuing from empty queue returns empty list."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client
    mock_redis_client.lpop = AsyncMock(return_value=None)

    result = await queue.dequeue(count=1)

    assert result == []


@pytest.mark.asyncio
async def test_dequeue_is_fifo(redis_url, mock_redis_client):
    """
    dequeue() must return items in FIFO order (oldest first).

    enqueue() uses rpush → items pile up on the right.
    dequeue() must use lpop → pulls from the left (oldest).
    RPUSH + RPOP would be a stack (LIFO) — that's the bug this test guards against.
    """
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client

    first_in  = {"short_code": "aaa", "original_url": "https://first.com"}
    second_in = {"short_code": "bbb", "original_url": "https://second.com"}

    # Simulate Redis list state after two rpush calls: [first_in, second_in]
    # lpop pulls from the left → first_in comes out first (FIFO)
    # rpop would pull from the right → second_in first (LIFO / bug)
    remaining = [json.dumps(first_in), json.dumps(second_in)]

    async def fake_lpop(name, count=None):
        if count is not None:
            items = remaining[:count]
            del remaining[:count]
            return items if items else None
        if remaining:
            return remaining.pop(0)
        return None

    mock_redis_client.lpop = AsyncMock(side_effect=fake_lpop)

    first_out  = await queue.dequeue(count=1)
    second_out = await queue.dequeue(count=1)

    assert first_out[0]["short_code"]  == "aaa", "oldest item must come out first"
    assert second_out[0]["short_code"] == "bbb", "newest item must come out second"


@pytest.mark.asyncio
async def test_redis_queue_size(redis_url, mock_redis_client):
    """Test getting queue size."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client
    mock_redis_client.llen = AsyncMock(return_value=5)

    size = await queue.size()

    assert size == 5
    mock_redis_client.llen.assert_called_once_with("url_batch_queue")


@pytest.mark.asyncio
async def test_redis_queue_clear(redis_url, mock_redis_client):
    """Test clearing queue."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client

    await queue.clear()

    mock_redis_client.delete.assert_called_once_with("url_batch_queue")


@pytest.mark.asyncio
async def test_redis_queue_enqueue_without_connection(redis_url):
    """Test enqueuing without connection raises RuntimeError."""
    queue = RedisQueue(redis_url)

    with pytest.raises(RuntimeError, match="not connected"):
        await queue.enqueue({"test": "data"})


@pytest.mark.asyncio
async def test_redis_queue_dequeue_without_connection(redis_url):
    """Test dequeuing without connection raises RuntimeError."""
    queue = RedisQueue(redis_url)

    with pytest.raises(RuntimeError, match="not connected"):
        await queue.dequeue()


@pytest.mark.asyncio
async def test_redis_queue_close(redis_url, mock_redis_client):
    """Test closing Redis connection."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client
    mock_redis_client.close = AsyncMock()

    await queue.close()

    mock_redis_client.close.assert_called_once()
    assert queue._client is None
