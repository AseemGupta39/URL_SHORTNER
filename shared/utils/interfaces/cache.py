"""
Cache Interface

Abstract base class for cache implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


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
