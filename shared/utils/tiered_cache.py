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
            logger.debug("TieredCache L1 hit", extra={"short_code": key})
            return l1_val

        logger.debug("TieredCache L1 miss", extra={"short_code": key})

        # Check L2
        l2_val = await self.l2_cache.get_async(key)
        if l2_val is not None:
            logger.debug("TieredCache L2 hit, backfilling L1", extra={"short_code": key})
            await self.l1_cache.set_async(key, l2_val)
            return l2_val

        logger.debug("TieredCache L2 miss", extra={"short_code": key})
        return None

    async def set_async(self, key: str, value: Any) -> None:
        """
        Store value in cache (async). Raises if both L1 and L2 fail.
        Writes to both L1 and L2. A single layer failing is logged but tolerated.
        """
        try:
            await self.l1_cache.set_async(key, value)
        except Exception as e:
            logger.warning("TieredCache failed to write to L1", extra={"short_code": key, "error": str(e)})

        try:
            await self.l2_cache.set_async(key, value)
        except Exception as e:
            logger.warning("TieredCache failed to write to L2", extra={"short_code": key, "error": str(e)})

    async def delete_async(self, key: str) -> None:
        """
        Delete entry from cache (async). Raises if L2 fails (L2 is source of truth).
        Deletes from both L1 and L2.
        """
        try:
            await self.l1_cache.delete_async(key)
        except Exception as e:
            logger.warning("TieredCache failed to delete from L1", extra={"short_code": key, "error": str(e)})

        await self.l2_cache.delete_async(key)  # L2 failure propagates — caller decides

    def get_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics."""
        return {
            "cache_type": "tiered",
            "l1_stats": self.l1_cache.get_stats(),
            "l2_stats": self.l2_cache.get_stats()
        }
