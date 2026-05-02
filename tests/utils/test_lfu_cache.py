"""
TDD tests for LFUCache.
Written before implementation — tests define expected behavior.
"""
import pytest
from datetime import datetime, timezone
from shared.core.schemas import URLData
from shared.utils.lfu_cache import LFUCache

def make_url(short_code: str = "abc12345", url: str = "https://example.com") -> URLData:
    return URLData(short_code=short_code, original_url=url, created_at=datetime.now(timezone.utc))

class TestLFUCache:

    # ---------------------------------------------------------------------------
    # Constructor
    # ---------------------------------------------------------------------------

    def test_max_size_validation(self) -> None:
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            LFUCache(max_size=0)
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            LFUCache(max_size=-1)
        
        cache = LFUCache(max_size=10)
        assert cache._max_size == 10

    # ---------------------------------------------------------------------------
    # get_async
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_hit_miss(self) -> None:
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        assert await cache.get_async("k1") == "v1"
        assert await cache.get_async("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_increments_frequency(self) -> None:
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        assert cache._entries["k1"].frequency == 1
        await cache.get_async("k1")
        assert cache._entries["k1"].frequency == 2
        await cache.get_async("k1")
        assert cache._entries["k1"].frequency == 3

    # ---------------------------------------------------------------------------
    # set_async
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_set_new_item(self) -> None:
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        # Frequency starts at 1
        assert cache._entries["k1"].frequency == 1
        assert await cache.get_async("k1") == "v1"
        # get_async increments frequency to 2
        assert cache._entries["k1"].frequency == 2

    @pytest.mark.asyncio
    async def test_set_update_existing_item(self) -> None:
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        assert cache._entries["k1"].frequency == 1
        
        await cache.set_async("k1", "v1_updated")
        # Frequency should increment on update (now 2)
        assert cache._entries["k1"].frequency == 2
        
        assert await cache.get_async("k1") == "v1_updated"
        # Frequency should increment on get (now 3)
        assert cache._entries["k1"].frequency == 3

    @pytest.mark.asyncio
    async def test_set_evicts_lfu(self) -> None:
        cache = LFUCache(max_size=2)
        await cache.set_async("k1", "v1") # f:1
        await cache.set_async("k2", "v2") # f:1
        
        # Access k1 to increase frequency
        await cache.get_async("k1") # f:2
        
        # Adding k3 should evict k2 (freq 1 < freq 2)
        await cache.set_async("k3", "v3")
        assert await cache.get_async("k2") is None
        assert await cache.get_async("k1") == "v1"
        assert await cache.get_async("k3") == "v3"

    @pytest.mark.asyncio
    async def test_set_evicts_fifo_tiebreak(self) -> None:
        cache = LFUCache(max_size=2)
        await cache.set_async("k1", "v1") # Added first
        await cache.set_async("k2", "v2") # Added second
        
        # Both have freq 1. Eviction should be FIFO (k1)
        await cache.set_async("k3", "v3")
        assert await cache.get_async("k1") is None
        assert await cache.get_async("k2") == "v2"
        assert await cache.get_async("k3") == "v3"

    # ---------------------------------------------------------------------------
    # delete_async
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_delete_functionality(self) -> None:
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        assert await cache.delete_async("k1") is True
        assert await cache.get_async("k1") is None
        assert await cache.delete_async("k1") is False
        assert await cache.delete_async("nonexistent") is False

    @pytest.mark.asyncio
    async def test_delete_updates_min_freq(self) -> None:
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1") # f:1
        await cache.set_async("k2", "v2") # f:1
        await cache.get_async("k1")       # f:2
        
        # min_freq is 1 (because of k2)
        assert cache._min_freq == 1
        
        await cache.delete_async("k2")
        # Only k1 (f:2) remains. min_freq should be 2
        assert cache._min_freq == 2
        
        await cache.delete_async("k1")
        # Cache empty, min_freq should reset
        assert cache._min_freq == 1

    # ---------------------------------------------------------------------------
    # Statistics & Edge Cases
    # ---------------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_get_stats(self) -> None:
        cache = LFUCache(max_size=5)
        await cache.set_async("k1", "v1")
        await cache.get_async("k1") # hit
        await cache.get_async("k2") # miss
        await cache.set_async("k2", "v2")
        await cache.set_async("k3", "v3")
        await cache.set_async("k4", "v4")
        await cache.set_async("k5", "v5")
        await cache.set_async("k6", "v6") # evict k2 (f:1, FIFO)
        
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["evictions"] == 1
        assert stats["size"] == 5
        assert stats["max_size"] == 5

    @pytest.mark.asyncio
    async def test_capacity_one(self) -> None:
        cache = LFUCache(max_size=1)
        await cache.set_async("k1", "v1")
        await cache.set_async("k2", "v2") # should evict k1
        assert await cache.get_async("k1") is None
        assert await cache.get_async("k2") == "v2"

    @pytest.mark.asyncio
    async def test_complex_behavior(self) -> None:
        cache = LFUCache(max_size=3)
        
        # Fill
        await cache.set_async("a", 1) # f:1
        await cache.set_async("b", 2) # f:1
        await cache.set_async("c", 3) # f:1
        
        # Access
        await cache.get_async("a") # f:2
        await cache.get_async("a") # f:3
        await cache.get_async("b") # f:2
        
        # State: a:3, b:2, c:1. min_freq: 1
        assert cache._min_freq == 1
        
        # Evict c
        await cache.set_async("d", 4) # d:1, c evicted
        assert await cache.get_async("c") is None
        
        # Access d
        await cache.get_async("d") # f:2
        await cache.get_async("d") # f:3
        # State: a:3, b:2, d:3. min_freq: 2
        assert cache._min_freq == 2
        
        # Evict b
        await cache.set_async("e", 5) # e:1, b evicted
        assert await cache.get_async("b") is None
        assert cache._min_freq == 1
        
        # Final check
        assert cache.get_stats()["evictions"] == 2
        assert cache.get_stats()["size"] == 3

    @pytest.mark.asyncio
    async def test_set_after_delete(self) -> None:
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        assert cache._entries["k1"].frequency == 1
        
        await cache.delete_async("k1")
        assert "k1" not in cache._entries
        
        await cache.set_async("k1", "v2")
        # Should be a fresh start with frequency 1
        assert cache._entries["k1"].frequency == 1
        assert await cache.get_async("k1") == "v2"
        assert cache._entries["k1"].frequency == 2