"""
Cache Interface

Abstract base class for cache implementations with CacheEntry helper.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime


class Cache(ABC):
    """
    Abstract base class for cache implementations.
    Supports both sync (LRUCache) and async (RedisCache) operations.
    """

    @abstractmethod
    async def get_async(self, key: str) -> Optional[Any]:
        """Get value from cache (async)."""
        pass

    @abstractmethod
    async def set_async(self, key: str, value: Any) -> None:
        """Store value in cache (async). Raises on failure."""
        pass

    @abstractmethod
    async def delete_async(self, key: str) -> None:
        """Delete entry from cache (async). Raises on failure."""
        pass

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        pass


class CacheEntry:
    """
    A simple container for cached data with expiration time.

    Think of it like a sticky note with:
    - The actual data (value)
    - An expiration date (expires_at)
    """

    def __init__(self, value: Any, expires_at: datetime):
        self.value = value
        self.expires_at = expires_at

    def is_expired(self) -> bool:
        """Check if this cache entry is too old and should be deleted."""
        return datetime.utcnow() >= self.expires_at
