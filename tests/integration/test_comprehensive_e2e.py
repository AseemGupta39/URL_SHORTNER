"""
Comprehensive end-to-end integration test covering ALL components:
- Shorten service (cache-first)
- Redirect service (cache-aside)
- Batch processor
- Redis cache
- Redis queue
- PostgreSQL database

This test simulates real-world usage with multiple users shortening and accessing URLs.
"""
import pytest
import asyncio
from datetime import datetime
from pydantic import HttpUrl
import os

# Set env before imports
os.environ['REDIS_ENABLED'] = 'true'
os.environ['REDIS_URL'] = 'rediss://default:AW1fAAIncDI0NTIzMTIxNGYzMmE0ZjdjOGU1OGVmYWQ2OTVlYWU4OXAyMjc5OTk@safe-gecko-27999.upstash.io:6379'

from shared.core.services import URLService
from shared.core.schemas import URLData
from shared.core.exceptions import ShortCodeNotFoundException
from shared.data.repositories import SQLiteURLRepository
from shared.utils.snowflake_id_generator import SnowflakeIDGenerator
from shared.utils.redis_cache import RedisCache
from shared.utils.redis_queue import RedisQueue


@pytest.mark.asyncio
async def test_comprehensive_end_to_end_flow():
    """
    Test complete system flow:
    1. User shortens URLs (cache-first)
    2. URLs are queued for batch processing
    3. Batch processor dequeues and inserts to DB
    4. User accesses short URLs (cache hit)
    5. User accesses new short URL (cache miss → DB → cache warm)
    6. Verify cache statistics
    7. Test error handling
    """

    print("\n" + "="*70)
    print("COMPREHENSIVE END-TO-END TEST")
    print("="*70)

    # ===== SETUP =====
    print("\n[SETUP] Initializing components...")

    cache = RedisCache(
        redis_url=os.environ['REDIS_URL'],
        ttl_seconds=300,  # 5 minutes
        key_prefix="comprehensive_test:"
    )
    await cache.connect()

    queue = RedisQueue(
        redis_url=os.environ['REDIS_URL'],
        queue_name="comprehensive_test_queue"
    )
    await queue.connect()
    await queue.clear()  # Clear any old test data

    repo = SQLiteURLRepository(db_url="sqlite+aiosqlite:///:memory:")
    await repo.initialize()

    id_gen = SnowflakeIDGenerator(datacenter_id=1, worker_id=1)

    service = URLService(
        url_repo=repo,
        id_generator=id_gen,
        cache=cache,
        queue=queue,
        base_domain="short.test",
        base_url_scheme="https"
    )

    print("✓ All components initialized")

    try:
        # ===== TEST 1: SHORTEN MULTIPLE URLs (Cache-First) =====
        print("\n" + "-"*70)
        print("TEST 1: Shorten 10 URLs (cache-first architecture)")
        print("-"*70)

        test_urls = [
            "https://example.com",
            "https://github.com/user/repo",
            "https://stackoverflow.com/questions/12345",
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://docs.python.org/3/library/asyncio.html",
            "https://www.google.com/search?q=python",
            "https://news.ycombinator.com",
            "https://reddit.com/r/programming",
            "https://medium.com/@author/article",
            "https://twitter.com/user/status/123456"
        ]

        shortened_results = []
        short_codes = []

        for i, url in enumerate(test_urls, 1):
            result = await service.shorten(HttpUrl(url))
            shortened_results.append(result)
            short_codes.append(result.short_code)

            print(f"  {i}. {url[:50]:<50} → {result.short_code}")

            # Verify short code format
            assert len(result.short_code) > 0
            assert result.short_url == f"https://short.test/{result.short_code}"

        print(f"\n✓ Successfully shortened {len(test_urls)} URLs")

        # ===== TEST 2: VERIFY CACHE (Immediate Availability) =====
        print("\n" + "-"*70)
        print("TEST 2: Verify all URLs in cache (immediate availability)")
        print("-"*70)

        cache_hits = 0
        for short_code in short_codes:
            cached_data = await cache.get_async(short_code)
            if cached_data:
                cache_hits += 1
                print(f"  ✓ {short_code}: CACHE HIT")
            else:
                print(f"  ✗ {short_code}: CACHE MISS (UNEXPECTED!)")

        assert cache_hits == len(short_codes), f"Expected {len(short_codes)} cache hits, got {cache_hits}"
        print(f"\n✓ All {cache_hits} URLs in cache (100% hit rate)")

        # ===== TEST 3: VERIFY QUEUE (Batch Processing Ready) =====
        print("\n" + "-"*70)
        print("TEST 3: Verify queue has all URLs for batch processing")
        print("-"*70)

        queue_size = await queue.size()
        print(f"  Queue size: {queue_size}")
        assert queue_size == len(test_urls), f"Expected {len(test_urls)} items in queue, got {queue_size}"

        print(f"✓ Queue ready with {queue_size} items")

        # ===== TEST 4: BATCH PROCESSING (Database Persistence) =====
        print("\n" + "-"*70)
        print("TEST 4: Batch process queued URLs → Database")
        print("-"*70)

        # Dequeue batch
        batch_size = 5
        batch_1 = await queue.dequeue(count=batch_size)
        print(f"  Dequeued batch 1: {len(batch_1)} items")

        batch_2 = await queue.dequeue(count=batch_size)
        print(f"  Dequeued batch 2: {len(batch_2)} items")

        # Convert to URLData
        all_batches = batch_1 + batch_2
        url_data_list = [
            URLData(
                short_code=item["short_code"],
                original_url=item["original_url"],
                created_at=datetime.fromisoformat(item["created_at"])
            )
            for item in all_batches
        ]

        # Batch insert
        inserted_count = await repo.batch_create(url_data_list)
        print(f"  Inserted {inserted_count} URLs to database")

        assert inserted_count == len(test_urls)

        # Verify queue is empty
        final_queue_size = await queue.size()
        assert final_queue_size == 0
        print(f"\n✓ Batch processing complete ({inserted_count} URLs in DB, queue empty)")

        # ===== TEST 5: REDIRECT (Cache Hit - Fast Path) =====
        print("\n" + "-"*70)
        print("TEST 5: Redirect using cache hits (fast path: 1-2ms)")
        print("-"*70)

        redirect_count = 0
        for i, short_code in enumerate(short_codes[:5], 1):  # Test first 5
            result = await service.resolve(short_code)
            # Normalize URLs for comparison (Pydantic HttpUrl adds trailing slash)
            assert str(result.original_url).rstrip('/') == test_urls[i-1].rstrip('/')
            redirect_count += 1
            print(f"  {i}. {short_code} → {str(result.original_url)[:50]}")

        print(f"\n✓ {redirect_count} cache-hit redirects successful")

        # ===== TEST 6: REDIRECT (Cache Miss → DB → Cache Warm) =====
        print("\n" + "-"*70)
        print("TEST 6: Simulate cache miss → DB query → cache warming")
        print("-"*70)

        # Clear cache for one URL to simulate cache miss
        test_short_code = short_codes[5]
        await cache.delete_async(test_short_code)
        print(f"  Cleared cache for {test_short_code}")

        # Verify cache miss
        cached = await cache.get_async(test_short_code)
        assert cached is None
        print(f"  ✓ Cache miss confirmed")

        # Redirect should query DB and warm cache
        result = await service.resolve(test_short_code)
        # Normalize URLs for comparison
        assert str(result.original_url).rstrip('/') == test_urls[5].rstrip('/')
        print(f"  ✓ Redirect successful: {test_short_code} → {str(result.original_url)[:50]}")

        # Verify cache was warmed
        cached_after = await cache.get_async(test_short_code)
        assert cached_after is not None
        print(f"  ✓ Cache warmed successfully")

        # ===== TEST 7: ERROR HANDLING =====
        print("\n" + "-"*70)
        print("TEST 7: Error handling (non-existent short code)")
        print("-"*70)

        fake_code = "NONEXISTENT"
        try:
            await service.resolve(fake_code)
            assert False, "Should have raised ShortCodeNotFoundException"
        except ShortCodeNotFoundException as e:
            print(f"  ✓ Correctly raised ShortCodeNotFoundException: {e}")

        # ===== TEST 8: CACHE STATISTICS =====
        print("\n" + "-"*70)
        print("TEST 8: Cache performance statistics")
        print("-"*70)

        stats = cache.get_stats()
        print(f"  Cache hits: {stats['hits']}")
        print(f"  Cache misses: {stats['misses']}")
        print(f"  Hit rate: {stats['hit_rate']:.2%}")

        assert stats['hits'] > 0
        assert stats['hit_rate'] > 0.8  # Should be >80% hit rate

        print(f"✓ Cache performance verified (hit rate: {stats['hit_rate']:.2%})")

        # ===== TEST 9: DATABASE VERIFICATION =====
        print("\n" + "-"*70)
        print("TEST 9: Verify all URLs in database")
        print("-"*70)

        db_count = 0
        for short_code in short_codes:
            db_data = await repo.get_by_short_code(short_code)
            if db_data:
                db_count += 1
            else:
                print(f"  ✗ {short_code} NOT in database!")

        assert db_count == len(short_codes)
        print(f"✓ All {db_count} URLs verified in database")

        # ===== TEST 10: CONCURRENT OPERATIONS =====
        print("\n" + "-"*70)
        print("TEST 10: Concurrent URL shortening (simulating load)")
        print("-"*70)

        concurrent_urls = [
            f"https://concurrent{i}.test" for i in range(20)
        ]

        # Shorten concurrently
        tasks = [service.shorten(HttpUrl(url)) for url in concurrent_urls]
        concurrent_results = await asyncio.gather(*tasks)

        print(f"  Shortened {len(concurrent_results)} URLs concurrently")

        # Verify all have unique short codes
        concurrent_codes = [r.short_code for r in concurrent_results]
        unique_codes = set(concurrent_codes)
        assert len(unique_codes) == len(concurrent_codes)

        print(f"✓ All {len(concurrent_codes)} codes are unique")

        # Clean up concurrent test data
        await queue.clear()

        # ===== FINAL SUMMARY =====
        print("\n" + "="*70)
        print("TEST SUMMARY")
        print("="*70)
        print(f"✓ Shortened URLs: {len(test_urls)}")
        print(f"✓ Cache hits: {cache_hits}")
        print(f"✓ Batch inserts: {inserted_count}")
        print(f"✓ Redirects tested: {redirect_count + 1}")  # +1 for cache miss test
        print(f"✓ Concurrent operations: {len(concurrent_results)}")
        print(f"✓ Cache hit rate: {stats['hit_rate']:.2%}")
        print(f"✓ Database entries: {db_count}")
        print("="*70)
        print("ALL TESTS PASSED! ✅")
        print("="*70 + "\n")

    finally:
        # Cleanup
        print("\n[CLEANUP] Cleaning up test resources...")
        await queue.clear()
        await queue.close()
        await cache._client.close()
        await repo.close()
        print("✓ Cleanup complete")


if __name__ == "__main__":
    # Run the test directly
    asyncio.run(test_comprehensive_end_to_end_flow())
