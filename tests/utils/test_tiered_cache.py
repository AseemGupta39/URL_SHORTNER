import pytest
from unittest.mock import AsyncMock

from shared.utils.tiered_cache import TieredCache

@pytest.fixture
def mock_l1():
    cache = AsyncMock()
    cache.get_async = AsyncMock(return_value=None)
    cache.set_async = AsyncMock(return_value=None)  # set_async returns None now
    cache.delete_async = AsyncMock(return_value=None)  # delete_async returns None now
    return cache

@pytest.fixture
def mock_l2():
    cache = AsyncMock()
    cache.get_async = AsyncMock(return_value=None)
    cache.set_async = AsyncMock(return_value=None)
    cache.delete_async = AsyncMock(return_value=None)
    return cache

@pytest.fixture
def tiered_cache(mock_l1, mock_l2):
    return TieredCache(l1_cache=mock_l1, l2_cache=mock_l2)

@pytest.mark.asyncio
async def test_tiered_cache_l1_hit(tiered_cache, mock_l1, mock_l2):
    mock_l1.get_async.return_value = "l1_value"
    
    val = await tiered_cache.get_async("key1")
    assert val == "l1_value"
    mock_l1.get_async.assert_called_once_with("key1")
    mock_l2.get_async.assert_not_called()

@pytest.mark.asyncio
async def test_tiered_cache_l2_hit_backfills_l1(tiered_cache, mock_l1, mock_l2):
    mock_l1.get_async.return_value = None
    mock_l2.get_async.return_value = "l2_value"
    
    val = await tiered_cache.get_async("key1")
    assert val == "l2_value"
    mock_l1.get_async.assert_called_once_with("key1")
    mock_l2.get_async.assert_called_once_with("key1")
    mock_l1.set_async.assert_called_once_with("key1", "l2_value")

@pytest.mark.asyncio
async def test_tiered_cache_miss(tiered_cache, mock_l1, mock_l2):
    mock_l1.get_async.return_value = None
    mock_l2.get_async.return_value = None
    
    val = await tiered_cache.get_async("key1")
    assert val is None
    mock_l1.get_async.assert_called_once_with("key1")
    mock_l2.get_async.assert_called_once_with("key1")
    mock_l1.set_async.assert_not_called()

@pytest.mark.asyncio
async def test_tiered_cache_set(tiered_cache, mock_l1, mock_l2):
    await tiered_cache.set_async("key1", "val1")
    mock_l1.set_async.assert_called_once_with("key1", "val1")
    mock_l2.set_async.assert_called_once_with("key1", "val1")

@pytest.mark.asyncio
async def test_tiered_cache_delete(tiered_cache, mock_l1, mock_l2):
    await tiered_cache.delete_async("key1")
    mock_l1.delete_async.assert_called_once_with("key1")
    mock_l2.delete_async.assert_called_once_with("key1")
