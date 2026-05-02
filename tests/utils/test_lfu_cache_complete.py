import pytest
from datetime import datetime, timezone
from shared.core.schemas import URLData
from shared.utils.lfu_cache import LFUCache

def make_url(short_code: str = "abc12345", url: str = "https://example.com") -> URLData:
    return URLData(short_code=short_code, original_url=url, created_at=datetime.now(timezone.utc))

@pytest.mark.asyncio
class TestLFUCacheComplete:

    async def test_constructor_validation(self):
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            LFUCache(max_size=0)
        with pytest.raises(ValueError, match="max_size must be >= 1"):
            LFUCache(max_size=-5)
        
        cache = LFUCache(max_size=10)
        assert cache._max_size == 10
        assert cache.get_stats()["max_size"] == 10

    async def test_basic_set_get(self):
        cache = LFUCache(max_size=2)
        data1 = make_url("code1")
        data2 = make_url("code2")
        
        assert await cache.set_async("k1", data1) is True
        assert await cache.set_async("k2", data2) is True
        
        assert await cache.get_async("k1") == data1
        assert await cache.get_async("k2") == data2
        assert await cache.get_async("k3") is None

    async def test_frequency_increment_on_get(self):
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        
        # Initial freq is 1
        assert cache._entries["k1"].frequency == 1
        
        await cache.get_async("k1")
        assert cache._entries["k1"].frequency == 2
        
        await cache.get_async("k1")
        assert cache._entries["k1"].frequency == 3

    async def test_frequency_increment_on_set_update(self):
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        assert cache._entries["k1"].frequency == 1
        
        # Updating existing key should increment frequency
        await cache.set_async("k1", "v1_updated")
        assert cache._entries["k1"].frequency == 2
        assert await cache.get_async("k1") == "v1_updated"
        assert cache._entries["k1"].frequency == 3

    async def test_eviction_lfu(self):
        # Capacity 2
        cache = LFUCache(max_size=2)
        await cache.set_async("k1", "v1")
        await cache.set_async("k2", "v2")
        
        # k1 freq: 1, k2 freq: 1
        # Access k1 to make it freq 2
        await cache.get_async("k1")
        
        # Now k1 freq: 2, k2 freq: 1
        # Adding k3 should evict k2 (LFU)
        await cache.set_async("k3", "v3")
        
        assert await cache.get_async("k1") == "v1"
        assert await cache.get_async("k2") is None
        assert await cache.get_async("k3") == "v3"
        
        stats = cache.get_stats()
        assert stats["evictions"] == 1
        assert stats["size"] == 2

    async def test_eviction_fifo_tiebreak(self):
        # Capacity 2
        cache = LFUCache(max_size=2)
        await cache.set_async("k1", "v1") # k1 added first, freq 1
        await cache.set_async("k2", "v2") # k2 added second, freq 1
        
        # Both have freq 1. Eviction should be FIFO (k1)
        await cache.set_async("k3", "v3")
        
        assert await cache.get_async("k1") is None
        assert await cache.get_async("k2") == "v2"
        assert await cache.get_async("k3") == "v3"

    async def test_delete_async(self):
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        await cache.set_async("k2", "v2")
        
        assert await cache.delete_async("k1") is True
        assert await cache.get_async("k1") is None
        assert await cache.delete_async("k1") is False # Already deleted
        assert await cache.delete_async("nonexistent") is False
        
        assert cache.get_stats()["size"] == 1

    async def test_min_freq_updates_on_eviction(self):
        cache = LFUCache(max_size=2)
        await cache.set_async("k1", "v1")
        await cache.set_async("k2", "v2")
        
        # Both freq 1, min_freq = 1
        assert cache._min_freq == 1
        
        await cache.get_async("k1")
        await cache.get_async("k2")
        # Both freq 2, min_freq = 2
        assert cache._min_freq == 2
        
        # Add k3, should evict k1 (FIFO among freq 2)
        await cache.set_async("k3", "v3")
        # k3 added with freq 1, so min_freq should reset to 1
        assert cache._min_freq == 1
        assert await cache.get_async("k1") is None

    async def test_min_freq_updates_on_delete(self):
        cache = LFUCache(max_size=10)
        await cache.set_async("k1", "v1")
        await cache.set_async("k2", "v2")
        
        await cache.get_async("k1") # k1 freq 2
        # k2 freq 1, min_freq = 1
        assert cache._min_freq == 1
        
        await cache.delete_async("k2")
        # k2 gone, only k1 (freq 2) remains. min_freq should be 2
        assert cache._min_freq == 2
        
        await cache.delete_async("k1")
        # Cache empty, min_freq resets to 1
        assert cache._min_freq == 1

    async def test_get_stats(self):
        cache = LFUCache(max_size=5)
        await cache.set_async("k1", "v1")
        await cache.set_async("k2", "v2")
        await cache.get_async("k1") # hit
        await cache.get_async("k3") # miss
        
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 2
        assert stats["max_size"] == 5
        assert stats["evictions"] == 0

    async def test_capacity_one(self):
        cache = LFUCache(max_size=1)
        await cache.set_async("k1", "v1")
        assert await cache.get_async("k1") == "v1"
        
        await cache.set_async("k2", "v2")
        assert await cache.get_async("k1") is None
        assert await cache.get_async("k2") == "v2"

    async def test_complex_scenario(self):
        """
        Mix of hits, updates, deletes, and evictions.
        """
        cache = LFUCache(max_size=3)
        
        # 1. Fill cache
        await cache.set_async("a", 1) # freq 1
        await cache.set_async("b", 2) # freq 1
        await cache.set_async("c", 3) # freq 1
        
        # 2. Update frequencies
        await cache.get_async("a") # a: 2
        await cache.get_async("a") # a: 3
        await cache.get_async("b") # b: 2
        
        # State: a:3, b:2, c:1. min_freq = 1
        assert cache._min_freq == 1
        
        # 3. Evict c
        await cache.set_async("d", 4) # d: 1, c evicted
        assert await cache.get_async("c") is None
        assert cache._min_freq == 1
        
        # 4. Access d multiple times
        await cache.get_async("d") # d: 2
        await cache.get_async("d") # d: 3
        # State: a:3, b:2, d:3. min_freq = 2 (b)
        assert cache._min_freq == 2
        
        # 5. Evict b
        await cache.set_async("e", 5) # e: 1, b evicted
        assert await cache.get_async("b") is None
        assert cache._min_freq == 1
        
        # 6. Delete a
        await cache.delete_async("a")
        # State: d:3, e:1. min_freq = 1 (e)
        assert cache._min_freq == 1
        
        # 7. Check final stats
        stats = cache.get_stats()
        assert stats["size"] == 2
        assert stats["evictions"] == 2
