"""
Test suite for caching functionality.

Tests the LRU cache implementation with TTL support.
"""
import pytest
import asyncio
from datetime import datetime

from app.utils.cache import LRUCache, Cache
from app.core.schemas import URLData


def test_cache_interface():
    """Test that LRUCache implements Cache interface."""
    cache = LRUCache()
    assert isinstance(cache, Cache)


def test_basic_set_and_get():
    """Test basic cache set and get operations."""
    cache = LRUCache(max_size=10, ttl_seconds=60)

    # Create test data
    url_data = URLData(
        short_code="abc123",
        original_url="https://example.com",
        created_at=datetime.utcnow()
    )

    # Set and get
    cache.set("abc123", url_data)
    result = cache.get("abc123")

    assert result is not None
    assert result == url_data
    assert result.short_code == "abc123"
    assert result.original_url == "https://example.com"


def test_cache_miss():
    """Test cache miss returns None."""
    cache = LRUCache()

    result = cache.get("nonexistent")
    assert result is None


def test_cache_delete():
    """Test deleting entries from cache."""
    cache = LRUCache()

    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"

    # Delete existing key
    deleted = cache.delete("key1")
    assert deleted is True
    assert cache.get("key1") is None

    # Delete non-existent key
    deleted = cache.delete("nonexistent")
    assert deleted is False


def test_cache_size():
    """Test cache size tracking."""
    cache = LRUCache(max_size=5)

    assert cache.size() == 0

    cache.set("key1", "value1")
    assert cache.size() == 1

    cache.set("key2", "value2")
    cache.set("key3", "value3")
    assert cache.size() == 3


def test_lru_eviction():
    """Test LRU eviction when cache is full."""
    cache = LRUCache(max_size=3, ttl_seconds=60)

    # Fill cache
    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    assert cache.size() == 3

    # Add 4th item - should evict oldest (key1)
    cache.set("key4", "value4")

    assert cache.size() == 3
    assert cache.get("key1") is None  # Evicted
    assert cache.get("key2") == "value2"  # Still there
    assert cache.get("key3") == "value3"  # Still there
    assert cache.get("key4") == "value4"  # New item


def test_lru_access_updates_order():
    """Test that accessing an item moves it to the end (recently used)."""
    cache = LRUCache(max_size=3, ttl_seconds=60)

    cache.set("key1", "value1")
    cache.set("key2", "value2")
    cache.set("key3", "value3")

    # Access key1 (makes it recently used)
    cache.get("key1")

    # Add key4 - should evict key2 (least recently used), not key1
    cache.set("key4", "value4")

    assert cache.get("key1") == "value1"  # Still there (was accessed)
    assert cache.get("key2") is None  # Evicted (least recently used)
    assert cache.get("key3") == "value3"  # Still there
    assert cache.get("key4") == "value4"  # New item


@pytest.mark.asyncio
async def test_ttl_expiration():
    """Test that entries expire after TTL."""
    cache = LRUCache(max_size=10, ttl_seconds=1)  # 1 second TTL

    cache.set("key1", "value1")

    # Should exist immediately
    assert cache.get("key1") == "value1"

    # Wait for expiration
    await asyncio.sleep(1.5)

    # Should be expired
    assert cache.get("key1") is None


def test_cache_clear():
    """Test clearing all cache entries."""
    cache = LRUCache()

    cache.set("key1", "value1")
    cache.set("key2", "value2")

    assert cache.size() == 2

    cache.clear()

    assert cache.size() == 0
    assert cache.get("key1") is None
    assert cache.get("key2") is None


def test_cache_stats():
    """Test cache statistics tracking."""
    cache = LRUCache(max_size=3, ttl_seconds=60)

    # Initial stats
    stats = cache.get_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["size"] == 0
    assert stats["hit_rate"] == 0

    # Add items
    cache.set("key1", "value1")
    cache.set("key2", "value2")

    # Cache hits
    cache.get("key1")  # Hit
    cache.get("key1")  # Hit

    # Cache misses
    cache.get("key3")  # Miss

    stats = cache.get_stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["size"] == 2
    assert stats["hit_rate"] == 66.67  # 2 hits out of 3 total requests


def test_cache_update_existing_key():
    """Test updating an existing key in cache."""
    cache = LRUCache()

    cache.set("key1", "value1")
    assert cache.get("key1") == "value1"

    # Update same key
    cache.set("key1", "value2")
    assert cache.get("key1") == "value2"

    # Size should not increase
    assert cache.size() == 1


def test_cleanup_expired():
    """Test manual cleanup of expired entries."""
    cache = LRUCache(max_size=10, ttl_seconds=-1)  # Negative TTL = immediately expired

    cache.set("key1", "value1")
    cache.set("key2", "value2")

    # Entries are expired but still in cache
    assert cache.size() == 2

    # Manual cleanup
    removed = cache.cleanup_expired()

    assert removed == 2
    assert cache.size() == 0
