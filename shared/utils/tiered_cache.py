"""
Tiered cache implementation combining L1 (in-memory) and L2 (distributed) caches.
"""
from typing import Any, Optional, Dict
import logging

from shared.utils.interfaces.cache import Cache

logger = logging.getLogger(__name__)

class TieredCache(Cache):
    """
    A tiered cache that checks L1 first, then L2.
    If L2 hits, it backfills L1.
    Writes and deletes are propagated to both caches.
    """

    def __init__(self, l1_cache: Cache, l2_cache: Cache):
        self.l1_cache = l1_cache
        self.l2_cache = l2_cache
        logger.info("TieredCache initialized with L1 and L2 caches")

    async def get_async(self, key: str) -> Optional[Any]:
        """
        Get value from cache (async).
        Checks L1, then L2. Backfills L1 on L2 hit.
        """
        # Check L1
        l1_val = await self.l1_cache.get_async(key)
        if l1_val is not None:
            logger.debug(f"TieredCache L1 hit for {key}")
            return l1_val

        logger.debug(f"TieredCache L1 miss for {key}")

        # Check L2
        l2_val = await self.l2_cache.get_async(key)
        if l2_val is not None:
            logger.debug(f"TieredCache L2 hit for {key}, backfilling L1")
            await self.l1_cache.set_async(key, l2_val)
            return l2_val

        logger.debug(f"TieredCache L2 miss for {key}")
        return None

    async def set_async(self, key: str, value: Any) -> bool:
        """
        Store value in cache (async).
        Writes to both L1 and L2.
        """
        l1_ok = await self.l1_cache.set_async(key, value)
        l2_ok = await self.l2_cache.set_async(key, value)
        
        if not l1_ok:
            logger.warning(f"TieredCache failed to write to L1 for {key}")
        if not l2_ok:
            logger.warning(f"TieredCache failed to write to L2 for {key}")
            
        return l1_ok and l2_ok

    async def delete_async(self, key: str) -> bool:
        """
        Delete entry from cache (async).
        Deletes from both L1 and L2.
        """
        l1_ok = await self.l1_cache.delete_async(key)
        l2_ok = await self.l2_cache.delete_async(key)
        return l1_ok or l2_ok

    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        return {
            "cache_type": "tiered",
            "l1_stats": self.l1_cache.get_stats(),
            "l2_stats": self.l2_cache.get_stats()
        }
