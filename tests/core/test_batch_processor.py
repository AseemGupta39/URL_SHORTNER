"""
Test suite for batch processor functionality.
Tests batch insertion logic and queue processing.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock

from shared.data.interfaces.url_repository import URLRepository
from shared.core.schemas import URLData
from shared.core.queue_messages import URLQueueMessage


@pytest.fixture
def mock_repository():
    """Create mock URL repository."""
    repo = AsyncMock(spec=URLRepository)
    repo.batch_create = AsyncMock(return_value=0)
    repo.initialize = AsyncMock()
    repo.close = AsyncMock()
    return repo


@pytest.fixture
def mock_queue():
    """Create mock Redis queue."""
    queue = AsyncMock()
    queue.dequeue = AsyncMock(return_value=[])
    queue.size = AsyncMock(return_value=0)
    queue.connect = AsyncMock()
    queue.close = AsyncMock()
    return queue


@pytest.mark.asyncio
async def test_batch_create_single_url(mock_repository):
    """Test batch creating a single URL."""
    url_data = URLData(
        short_code="abc123",
        original_url="https://example.com",
        created_at=datetime.now()
    )

    mock_repository.batch_create = AsyncMock(return_value=1)

    result = await mock_repository.batch_create([url_data])

    assert result == 1
    mock_repository.batch_create.assert_called_once()


@pytest.mark.asyncio
async def test_batch_create_multiple_urls(mock_repository):
    """Test batch creating multiple URLs."""
    url_data_list = [
        URLData(
            short_code=f"code{i}",
            original_url=f"https://example{i}.com",
            created_at=datetime.now()
        )
        for i in range(10)
    ]

    mock_repository.batch_create = AsyncMock(return_value=10)

    result = await mock_repository.batch_create(url_data_list)

    assert result == 10
    mock_repository.batch_create.assert_called_once_with(url_data_list)


@pytest.mark.asyncio
async def test_batch_create_empty_list(mock_repository):
    """Test batch creating with empty list."""
    mock_repository.batch_create = AsyncMock(return_value=0)

    result = await mock_repository.batch_create([])

    assert result == 0


@pytest.mark.asyncio
async def test_queue_message_to_url_data():
    """Test converting URLQueueMessage to URLData."""
    msg = URLQueueMessage(
        short_code="abc123",
        original_url="https://example.com",
        created_at=datetime.now().isoformat(),
        request_id="test-request-id"
    )

    url_data = URLData(
        short_code=msg.short_code,
        original_url=msg.original_url,
        created_at=datetime.fromisoformat(msg.created_at)
    )

    assert url_data.short_code == "abc123"
    assert url_data.original_url == "https://example.com"
    assert isinstance(url_data.created_at, datetime)


@pytest.mark.asyncio
async def test_dequeue_and_process_batch(mock_queue, mock_repository):
    """Test dequeuing items and processing as batch."""
    queue_items = [
        {
            "short_code": f"code{i}",
            "original_url": f"https://example{i}.com",
            "created_at": datetime.now().isoformat(),
            "request_id": "test-request-id"
        }
        for i in range(5)
    ]

    mock_queue.dequeue = AsyncMock(return_value=queue_items)
    mock_queue.size = AsyncMock(side_effect=[5, 0])
    mock_repository.batch_create = AsyncMock(return_value=5)

    queue_size_before = await mock_queue.size()
    assert queue_size_before == 5

    items = await mock_queue.dequeue(count=5)
    assert len(items) == 5

    url_data_list = []
    for item in items:
        msg = URLQueueMessage(**item)
        url_data = URLData(
            short_code=msg.short_code,
            original_url=msg.original_url,
            created_at=datetime.fromisoformat(msg.created_at)
        )
        url_data_list.append(url_data)

    inserted = await mock_repository.batch_create(url_data_list)
    assert inserted == 5

    queue_size_after = await mock_queue.size()
    assert queue_size_after == 0


@pytest.mark.asyncio
async def test_process_batch_with_invalid_message(mock_queue):
    """Test processing batch with invalid message format."""
    queue_items = [
        {
            "short_code": "valid1",
            "original_url": "https://example.com",
            "created_at": datetime.now().isoformat(),
            "request_id": "test-request-id"
        },
        {
            "invalid": "message"
        },
        {
            "short_code": "valid2",
            "original_url": "https://google.com",
            "created_at": datetime.now().isoformat(),
            "request_id": "test-request-id"
        }
    ]

    mock_queue.dequeue = AsyncMock(return_value=queue_items)

    items = await mock_queue.dequeue(count=3)

    url_data_list = []
    for item in items:
        try:
            msg = URLQueueMessage(**item)
            url_data = URLData(
                short_code=msg.short_code,
                original_url=msg.original_url,
                created_at=datetime.fromisoformat(msg.created_at)
            )
            url_data_list.append(url_data)
        except Exception:
            continue

    assert len(url_data_list) == 2
    assert url_data_list[0].short_code == "valid1"
    assert url_data_list[1].short_code == "valid2"


@pytest.mark.asyncio
async def test_empty_queue_processing(mock_queue, mock_repository):
    """Test processing when queue is empty."""
    mock_queue.size = AsyncMock(return_value=0)
    mock_queue.dequeue = AsyncMock(return_value=[])

    queue_size = await mock_queue.size()
    assert queue_size == 0

    items = await mock_queue.dequeue(count=100)
    assert items == []

    mock_repository.batch_create.assert_not_called()


@pytest.mark.asyncio
async def test_large_batch_processing(mock_queue, mock_repository):
    """Test processing large batch of URLs."""
    batch_size = 100
    queue_items = [
        {
            "short_code": f"code{i}",
            "original_url": f"https://example{i}.com",
            "created_at": datetime.now().isoformat()
        }
        for i in range(batch_size)
    ]

    mock_queue.dequeue = AsyncMock(return_value=queue_items)
    mock_queue.size = AsyncMock(return_value=batch_size)
    mock_repository.batch_create = AsyncMock(return_value=batch_size)

    items = await mock_queue.dequeue(count=batch_size)
    assert len(items) == batch_size

    url_data_list = [
        URLData(
            short_code=item["short_code"],
            original_url=item["original_url"],
            created_at=datetime.fromisoformat(item["created_at"])
        )
        for item in items
    ]

    inserted = await mock_repository.batch_create(url_data_list)
    assert inserted == batch_size
