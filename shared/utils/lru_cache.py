"""
Caching abstraction with in-memory LRU implementation.

Provides concrete LRU cache implementation
for fast URL lookups with automatic expiration.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from collections import OrderedDict
import threading
import logging

from shared.utils.interfaces.cache import Cache, CacheEntry

logger = logging.getLogger(__name__)


class LRUCache(Cache):
    """
    In-memory LRU cache with TTL support.

    **Why we need this:**
    - URL shorteners get the SAME short codes accessed repeatedly
    - Querying database every time is slow (10-50ms per query)
    - Cache stores results in memory (0.1ms lookup = 100x faster!)
    - Example: If short.ly/abc123 gets 1000 hits, we only query DB once

    **How it works:**
    1. When you look up a URL, we check cache first (super fast)
    2. If not in cache, we query database (slower) and cache the result
    3. If cache gets full, we remove the LEAST recently used item (LRU)
    4. Old entries automatically expire after TTL (Time To Live)

    **Thread-safe:** Multiple requests can use cache at the same time safely.

    Usage:
        cache = LRUCache(max_size=1000, ttl_seconds=3600)

        # Store a URL in cache
        cache.set("abc123", "https://example.com")

        # Retrieve from cache (returns None if not found)
        url = cache.get("abc123")
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        """
        Initialize the LRU cache.

        Args:
            max_size: Maximum number of URLs to store (default: 1000)
            ttl_seconds: How long to keep entries before expiring (default: 1 hour)
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

        # OrderedDict remembers insertion order, perfect for LRU
        # (Least Recently Used = oldest item is at the beginning)
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()

        # Lock ensures only one thread modifies cache at a time
        # RLock = Reentrant Lock (same thread can acquire multiple times)
        self._lock = threading.RLock()

        # Statistics for monitoring cache performance
        self._hits = 0      # How many times we found item in cache
        self._misses = 0    # How many times item wasn't in cache
        self._evictions = 0 # How many times we removed old items

        # Log initialization
        logger.info("LRUCache initialized", extra={"max_size": max_size, "ttl_seconds": ttl_seconds})

    async def get_async(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache.

        Args:
            key: The short code (e.g., "abc123")

        Returns:
            The cached value (e.g., original URL) if found and not expired
            None if not in cache or expired
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._misses += 1
                logger.debug(f"LRU cache miss: {key} (not found)")
                return None

            if entry.is_expired():
                self._cache.pop(key)
                self._misses += 1
                logger.debug(f"LRU cache miss: {key} (expired)")
                return None

            self._cache.move_to_end(key)
            self._hits += 1
            logger.debug(f"LRU cache hit: {key}")
            return entry.value

    async def set_async(self, key: str, value: Any) -> bool:
        """
        Store a value in the cache.

        Args:
            key: The short code (e.g., "abc123")
            value: The data to cache (e.g., original URL)

        Returns:
            True if successful
        """
        with self._lock:
            expires_at = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
            entry = CacheEntry(value=value, expires_at=expires_at)

            if key in self._cache:
                self._cache[key] = entry
                self._cache.move_to_end(key)
                logger.debug(f"LRU cache updated: {key}")
            else:
                self._cache[key] = entry
                logger.debug(f"LRU cache set: {key}")

                if len(self._cache) > self.max_size:
                    evicted_key, _ = self._cache.popitem(last=False)
                    self._evictions += 1
                    logger.warning(
                        f"LRU cache eviction: removed {evicted_key} "
                        f"(size={len(self._cache)}/{self.max_size}, evictions={self._evictions})"
                    )

            return True

    async def delete_async(self, key: str) -> bool:
        """
        Remove an entry from cache.

        Args:
            key: The short code to remove

        Returns:
            True if key was found and deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
                logger.debug(f"LRU cache delete: {key}")
                return True
            logger.debug(f"LRU cache delete failed: {key} (not found)")
            return False

    def clear(self) -> None:
        """Clear all entries and reset statistics."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def size(self) -> int:
        """Get current number of entries in cache."""
        with self._lock:
            return len(self._cache)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.

        Useful for monitoring how well the cache is performing.

        Returns:
            Dictionary with:
            - hits: Number of successful cache lookups
            - misses: Number of cache misses (had to query DB)
            - evictions: Number of items removed due to cache being full
            - size: Current number of items in cache
            - hit_rate: Percentage of requests served from cache (higher is better!)
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0

            return {
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "size": len(self._cache),
                "hit_rate": round(hit_rate, 2),  # e.g., 85.5% means 85.5% of requests from cache
                "max_size": self.max_size,
                "ttl_seconds": self.ttl_seconds
            }

    def cleanup_expired(self) -> int:
        """
        Manually remove all expired entries.

        Normally not needed (expired entries removed automatically on access),
        but useful for keeping memory usage low during idle periods.

        Returns:
            Number of expired entries removed
        """
        with self._lock:
            # Find all keys with expired entries
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]

            # Remove them
            for key in expired_keys:
                self._cache.pop(key)

            if expired_keys:
                logger.info(
                    f"LRU cache cleanup: removed {len(expired_keys)} expired entries "
                    f"(size={len(self._cache)}/{self.max_size})"
                )

            return len(expired_keys)
