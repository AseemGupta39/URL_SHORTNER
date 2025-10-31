"""
Caching abstraction with in-memory LRU implementation.

Provides abstract cache interface and concrete implementation
for fast URL lookups with automatic expiration.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from collections import OrderedDict
import threading


class Cache(ABC):
    """
    Abstract base class for cache implementations.

    Defines the interface that all cache implementations must follow.
    This allows us to swap implementations (e.g., Redis, Memcached)
    without changing the code that uses the cache.
    """

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value if found, None otherwise
        """
        pass

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """
        Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        pass

    @abstractmethod
    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all entries from cache."""
        pass

    @abstractmethod
    def size(self) -> int:
        """Get current number of entries in cache."""
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

    def get(self, key: str) -> Optional[Any]:
        """
        Get a value from the cache.

        This is the main method you'll use for lookups.

        Args:
            key: The short code (e.g., "abc123")

        Returns:
            The cached value (e.g., original URL) if found and not expired
            None if not in cache or expired
        """
        with self._lock:  # Lock ensures thread safety
            entry = self._cache.get(key)

            # Case 1: Key not in cache at all
            if entry is None:
                self._misses += 1
                return None

            # Case 2: Key exists but data is too old (expired)
            if entry.is_expired():
                self._cache.pop(key)  # Remove expired entry
                self._misses += 1
                return None

            # Case 3: Key found and still fresh!
            # Move to end to mark as "recently used" (for LRU)
            self._cache.move_to_end(key)
            self._hits += 1
            return entry.value

    def set(self, key: str, value: Any) -> None:
        """
        Store a value in the cache.

        Args:
            key: The short code (e.g., "abc123")
            value: The data to cache (e.g., original URL)
        """
        with self._lock:
            # Calculate when this entry should expire
            expires_at = datetime.utcnow() + timedelta(seconds=self.ttl_seconds)
            entry = CacheEntry(value=value, expires_at=expires_at)

            # If key already exists, update it and mark as recently used
            if key in self._cache:
                self._cache[key] = entry
                self._cache.move_to_end(key)
            else:
                # Add new entry
                self._cache[key] = entry

                # If cache is full, remove the OLDEST item (LRU eviction)
                # popitem(last=False) removes first item = least recently used
                if len(self._cache) > self.max_size:
                    self._cache.popitem(last=False)
                    self._evictions += 1

    def delete(self, key: str) -> bool:
        """
        Remove an entry from cache (useful when URL is deleted).

        Args:
            key: The short code to remove

        Returns:
            True if key was found and deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
                return True
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

            return len(expired_keys)
