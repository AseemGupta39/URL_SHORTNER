"""
In-memory LRU cache implementation.
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from collections import OrderedDict
import logging

from shared.utils.interfaces.cache import Cache

logger = logging.getLogger(__name__)


class LRUEntry:
    """Cached value with expiration time."""

    def __init__(self, value: Any, expires_at: datetime):
        self.value = value
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at


class LRUCache(Cache):
    """
    In-memory LRU cache with TTL support.

    asyncio is single-threaded and cooperative — coroutines only interleave at
    await points. All methods here are pure in-memory ops with no awaits, so no
    locking is needed.
    """

    def __init__(self, max_size: int = 1000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._cache: OrderedDict[str, LRUEntry] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        logger.info("LRUCache initialized", extra={"max_size": max_size, "ttl_seconds": ttl_seconds})

    async def get_async(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            logger.debug("LRU cache miss: not found", extra={"short_code": key})
            return None

        if entry.is_expired():
            self._cache.pop(key)
            self._misses += 1
            logger.debug("LRU cache miss: expired", extra={"short_code": key})
            return None

        self._cache.move_to_end(key)
        self._hits += 1
        logger.debug("LRU cache hit", extra={"short_code": key})
        return entry.value

    async def set_async(self, key: str, value: Any) -> None:
        expires_at = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
        entry = LRUEntry(value=value, expires_at=expires_at)

        if key in self._cache:
            self._cache[key] = entry
            self._cache.move_to_end(key)
            logger.debug("LRU cache updated", extra={"short_code": key})
        else:
            self._cache[key] = entry
            logger.debug("LRU cache set", extra={"short_code": key})

            if len(self._cache) > self.max_size:
                evicted_key, _ = self._cache.popitem(last=False)
                self._evictions += 1
                logger.warning("LRU cache eviction", extra={"evicted_key": evicted_key, "size": len(self._cache), "max_size": self.max_size, "evictions": self._evictions})

    async def delete_async(self, key: str) -> None:
        if key in self._cache:
            self._cache.pop(key)
            logger.debug("LRU cache delete", extra={"short_code": key})
        else:
            logger.debug("LRU cache delete: key not found", extra={"short_code": key})

    def clear(self) -> None:
        """Clear all entries and reset statistics."""
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    def size(self) -> int:
        """Get current number of entries in cache."""
        return len(self._cache)

    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "size": len(self._cache),
            "hit_rate": round(hit_rate, 2),
            "max_size": self.max_size,
            "ttl_seconds": self.ttl_seconds
        }

    def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        expired_keys = [k for k, e in self._cache.items() if e.is_expired()]
        for key in expired_keys:
            self._cache.pop(key)
        if expired_keys:
            logger.info("LRU cache cleanup", extra={"removed": len(expired_keys), "size": len(self._cache), "max_size": self.max_size})
        return len(expired_keys)
