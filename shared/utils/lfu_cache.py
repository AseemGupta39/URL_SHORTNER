import logging
from typing import Any, Dict, Optional

from shared.utils.interfaces.cache import Cache

logger = logging.getLogger(__name__)


class LFUEntry:
    """
    Wraps a cached value and tracks access frequency for LFU eviction.

    FIFO tie-breaking among same-frequency entries is handled by dict
    insertion order in _freq_buckets — no insertion_order field needed.

    frequency is stored here (not just implied by which bucket the key
    lives in) because _remove_key needs to know which bucket to clean up
    without scanning all buckets.
    """

    def __init__(self, value: Any) -> None:
        self.value: Any = value
        self.frequency: int = 1


class LFUCache(Cache):

    def __init__(self, max_size: int = 1000) -> None:
        if max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {max_size}")
        self._max_size: int = max_size

        # key → LFUEntry
        self._entries: Dict[str, LFUEntry] = {}

        # freq → ordered dict of keys at that frequency
        # dict preserves insertion order (3.7+) — gives FIFO tie-breaking for free
        self._freq_buckets: Dict[int, Dict[str, None]] = {}

        # always know the cheapest eviction candidate without scanning all buckets
        self._min_freq: int = 1

        self._hits: int = 0
        self._misses: int = 0
        self._evictions: int = 0

        logger.info("LFUCache initialized", extra={"max_size": max_size})

    def _update_frequency(self, key: str) -> None:
        """
        Increments the frequency of a key, moves it to the appropriate bucket,
        and updates the min_freq if necessary.
        """
        entry = self._entries[key]
        freq = entry.frequency

        # Remove key from the current frequency bucket
        del self._freq_buckets[freq][key]
        
        # If the bucket is now empty, delete it
        if len(self._freq_buckets[freq]) == 0:
            del self._freq_buckets[freq]
            # If this was the minimum frequency, increment min_freq
            if self._min_freq == freq:
                self._min_freq += 1

        # Increment the entry's frequency
        entry.frequency += 1
        new_freq = entry.frequency

        # Add to the new frequency bucket, initializing if necessary
        if new_freq not in self._freq_buckets:
            self._freq_buckets[new_freq] = {}
        self._freq_buckets[new_freq][key] = None

    def _evict(self) -> None:
        """
        Removes the least frequently used item from the cache.
        If there's a tie, the least recently used item is removed (FIFO).
        """
        # Get the bucket with the minimum frequency
        bucket = self._freq_buckets[self._min_freq]

        # The first key in the bucket is the oldest (FIFO)
        for evict_key in bucket:
            break

        # Remove from tracking dictionaries
        del self._entries[evict_key]
        del bucket[evict_key]

        # Clean up the bucket if it's now empty
        if len(bucket) == 0:
            del self._freq_buckets[self._min_freq]

        self._evictions += 1
        logger.info("LFUCache evicted key", extra={"evicted_key": evict_key})

    async def get_async(self, key: str) -> Optional[Any]:
        """Get value from cache (async)."""
        if key not in self._entries:
            self._misses += 1
            return None

        self._hits += 1
        # Since the item was accessed, we bump its frequency
        self._update_frequency(key)

        return self._entries[key].value

    async def set_async(self, key: str, value: Any) -> None:
        """Store value in cache (async). Raises on failure."""
        if key in self._entries:
            self._entries[key].value = value
            self._update_frequency(key)
            return

        if len(self._entries) >= self._max_size:
            self._evict()

        self._entries[key] = LFUEntry(value)

        if 1 not in self._freq_buckets:
            self._freq_buckets[1] = {}
        self._freq_buckets[1][key] = None

        self._min_freq = 1

    async def delete_async(self, key: str) -> None:
        """Delete entry from cache (async). Raises on failure."""
        if key not in self._entries:
            return

        entry = self._entries[key]
        freq = entry.frequency

        del self._entries[key]
        del self._freq_buckets[freq][key]

        if len(self._freq_buckets[freq]) == 0:
            del self._freq_buckets[freq]

            if self._min_freq == freq:
                if not self._entries:
                    self._min_freq = 1
                else:
                    self._min_freq = min(self._freq_buckets.keys())

    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "size": len(self._entries),
            "max_size": self._max_size,
            "min_freq": self._min_freq
        }