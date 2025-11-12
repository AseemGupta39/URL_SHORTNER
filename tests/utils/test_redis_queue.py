"""
Test suite for Redis queue functionality.
Tests queue operations with mock Redis client.
"""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
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
    mock_client.lpush = AsyncMock(return_value=1)
    mock_client.rpop = AsyncMock(return_value=None)
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

    result = await queue.enqueue(test_data)

    assert result is True
    mock_redis_client.lpush.assert_called_once()

    call_args = mock_redis_client.lpush.call_args
    assert call_args[0][0] == "url_batch_queue"

    enqueued_data = json.loads(call_args[0][1])
    assert enqueued_data == test_data


@pytest.mark.asyncio
async def test_redis_queue_dequeue_single(redis_url, mock_redis_client):
    """Test dequeuing single item from Redis queue."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client

    test_data = {"short_code": "abc123", "original_url": "https://example.com"}
    mock_redis_client.rpop = AsyncMock(return_value=json.dumps(test_data))

    result = await queue.dequeue(count=1)

    assert len(result) == 1
    assert result[0] == test_data
    mock_redis_client.rpop.assert_called_once_with("url_batch_queue")


@pytest.mark.asyncio
async def test_redis_queue_dequeue_multiple(redis_url, mock_redis_client):
    """Test dequeuing multiple items from Redis queue."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client

    test_data = [
        {"short_code": "abc123", "original_url": "https://example.com"},
        {"short_code": "def456", "original_url": "https://google.com"}
    ]
    mock_redis_client.rpop = AsyncMock(
        return_value=[json.dumps(item) for item in test_data]
    )

    result = await queue.dequeue(count=2)

    assert len(result) == 2
    assert result == test_data
    mock_redis_client.rpop.assert_called_once_with("url_batch_queue", 2)


@pytest.mark.asyncio
async def test_redis_queue_dequeue_empty(redis_url, mock_redis_client):
    """Test dequeuing from empty queue."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client
    mock_redis_client.rpop = AsyncMock(return_value=None)

    result = await queue.dequeue(count=1)

    assert result == []


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

    result = await queue.clear()

    assert result is True
    mock_redis_client.delete.assert_called_once_with("url_batch_queue")


@pytest.mark.asyncio
async def test_redis_queue_enqueue_without_connection(redis_url):
    """Test enqueuing without connection returns False."""
    queue = RedisQueue(redis_url)

    result = await queue.enqueue({"test": "data"})

    assert result is False


@pytest.mark.asyncio
async def test_redis_queue_dequeue_without_connection(redis_url):
    """Test dequeuing without connection returns empty list."""
    queue = RedisQueue(redis_url)

    result = await queue.dequeue()

    assert result == []


@pytest.mark.asyncio
async def test_redis_queue_close(redis_url, mock_redis_client):
    """Test closing Redis connection."""
    queue = RedisQueue(redis_url)
    queue._client = mock_redis_client
    mock_redis_client.close = AsyncMock()

    await queue.close()

    mock_redis_client.close.assert_called_once()
    assert queue._client is None
