"""
Test suite for caching functionality.
Tests the LRU cache implementation with TTL support.
"""
import pytest
import asyncio
from datetime import datetime

from shared.utils.lru_cache import LRUCache
from shared.utils.interfaces.cache import Cache
from shared.core.schemas import URLData


def test_cache_interface():
    """Test that LRUCache implements Cache interface."""
    cache = LRUCache()
    assert isinstance(cache, Cache)


@pytest.mark.asyncio
async def test_basic_set_and_get():
    """Test basic cache set and get operations."""
    cache = LRUCache(max_size=10, ttl_seconds=60)

    url_data = URLData(
        short_code="abc123",
        original_url="https://example.com",
        created_at=datetime.utcnow()
    )

    await cache.set_async("abc123", url_data)
    result = await cache.get_async("abc123")

    assert result is not None
    assert result == url_data
    assert result.short_code == "abc123"
    assert result.original_url == "https://example.com"


@pytest.mark.asyncio
async def test_cache_miss():
    """Test cache miss returns None."""
    cache = LRUCache()

    result = await cache.get_async("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_cache_delete():
    """Test deleting entries from cache."""
    cache = LRUCache()

    await cache.set_async("key1", "value1")
    assert await cache.get_async("key1") == "value1"

    deleted = await cache.delete_async("key1")
    assert deleted is True
    assert await cache.get_async("key1") is None

    deleted = await cache.delete_async("nonexistent")
    assert deleted is False


def test_cache_size():
    """Test cache size tracking."""
    cache = LRUCache(max_size=5)

    assert cache.size() == 0


@pytest.mark.asyncio
async def test_lru_eviction():
    """Test LRU eviction when cache is full."""
    cache = LRUCache(max_size=3, ttl_seconds=60)

    await cache.set_async("key1", "value1")
    await cache.set_async("key2", "value2")
    await cache.set_async("key3", "value3")

    assert cache.size() == 3

    await cache.set_async("key4", "value4")

    assert cache.size() == 3
    assert await cache.get_async("key1") is None
    assert await cache.get_async("key2") == "value2"
    assert await cache.get_async("key3") == "value3"
    assert await cache.get_async("key4") == "value4"


@pytest.mark.asyncio
async def test_lru_access_updates_order():
    """Test that accessing an item moves it to the end."""
    cache = LRUCache(max_size=3, ttl_seconds=60)

    await cache.set_async("key1", "value1")
    await cache.set_async("key2", "value2")
    await cache.set_async("key3", "value3")

    await cache.get_async("key1")

    await cache.set_async("key4", "value4")

    assert await cache.get_async("key1") == "value1"
    assert await cache.get_async("key2") is None
    assert await cache.get_async("key3") == "value3"
    assert await cache.get_async("key4") == "value4"


@pytest.mark.asyncio
async def test_ttl_expiration():
    """Test that entries expire after TTL."""
    cache = LRUCache(max_size=10, ttl_seconds=1)

    await cache.set_async("key1", "value1")

    assert await cache.get_async("key1") == "value1"

    await asyncio.sleep(1.5)

    assert await cache.get_async("key1") is None


def test_cache_clear():
    """Test clearing all cache entries."""
    cache = LRUCache()

    asyncio.run(cache.set_async("key1", "value1"))
    asyncio.run(cache.set_async("key2", "value2"))

    assert cache.size() == 2

    cache.clear()

    assert cache.size() == 0


@pytest.mark.asyncio
async def test_cache_stats():
    """Test cache statistics tracking."""
    cache = LRUCache(max_size=3, ttl_seconds=60)

    stats = cache.get_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["size"] == 0
    assert stats["hit_rate"] == 0

    await cache.set_async("key1", "value1")
    await cache.set_async("key2", "value2")

    await cache.get_async("key1")
    await cache.get_async("key1")

    await cache.get_async("key3")

    stats = cache.get_stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["size"] == 2
    assert stats["hit_rate"] == 66.67


@pytest.mark.asyncio
async def test_cache_update_existing_key():
    """Test updating an existing key in cache."""
    cache = LRUCache()

    await cache.set_async("key1", "value1")
    assert await cache.get_async("key1") == "value1"

    await cache.set_async("key1", "value2")
    assert await cache.get_async("key1") == "value2"

    assert cache.size() == 1


@pytest.mark.asyncio
async def test_cleanup_expired():
    """Test manual cleanup of expired entries."""
    cache = LRUCache(max_size=10, ttl_seconds=-1)

    await cache.set_async("key1", "value1")
    await cache.set_async("key2", "value2")

    assert cache.size() == 2

    removed = cache.cleanup_expired()

    assert removed == 2
    assert cache.size() == 0
