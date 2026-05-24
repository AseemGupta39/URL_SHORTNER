"""
Simple end-to-end integration test.
Run this manually to test the full flow with real services.
"""
import pytest
import asyncio
from datetime import datetime
from pydantic import HttpUrl

# Set env before imports
import os
os.environ['REDIS_ENABLED'] = 'true'
os.environ['REDIS_URL'] = 'redis://localhost:6379'

from shared.core.services import ShortenService
from shared.core.schemas import URLData
from shared.data.repositories import PostgresURLRepository
from shared.utils.snowflake_id_generator import SnowflakeIDGenerator
from shared.utils.redis_cache import RedisCache
from shared.utils.redis_queue import RedisQueue
from shared.utils.request_context import set_request_id, generate_request_id


@pytest.mark.asyncio
async def test_end_to_end_batch_flow():
    """Test complete flow: URL shorten → queue → batch process → database."""

    # Setup
    cache = RedisCache(
        redis_url=os.environ['REDIS_URL'],
        ttl_seconds=60,
        key_prefix="e2e_test:"
    )
    await cache.connect()

    queue = RedisQueue(
        redis_url=os.environ['REDIS_URL'],
        queue_name="e2e_test_queue"
    )
    await queue.connect()
    await queue.clear()  # Clear any old test data

    repo = PostgresURLRepository(db_url="postgresql+asyncpg://urlapp:dev123@127.0.0.1:5432/urls")
    await repo.initialize()

    from shared.utils.id_buffer import IDBuffer
    id_gen = SnowflakeIDGenerator(datacenter_id=0, worker_id=0)
    id_buffer = IDBuffer(generator=id_gen, size=100, refill_threshold=20)
    await id_buffer.start()

    service = ShortenService(
        url_repo=repo,
        cache=cache,
        queue=queue,
        id_buffer=id_buffer,
        base_domain="test.ly",
    )

    try:
        # Test 1: Shorten multiple URLs
        print("\n=== Test 1: Shortening 5 URLs ===")
        num_urls = 5
        urls = [HttpUrl(f"https://test{i}.com") for i in range(num_urls)]
        short_codes = []

        set_request_id(generate_request_id())
        for i, url in enumerate(urls):
            result = await service.shorten(url)
            short_codes.append(result.short_code)
            print(f"Shortened URL {i+1}: {url} -> {result.short_url}")

        # Test 2: Verify all in queue
        print(f"\n=== Test 2: Verifying queue ===")
        queue_size = await queue.size()
        print(f"Queue size: {queue_size}")
        assert queue_size == num_urls, f"Expected {num_urls} in queue, got {queue_size}"

        # Test 3: Process batch
        print(f"\n=== Test 3: Processing batch ===")
        items = await queue.dequeue(count=num_urls)
        print(f"Dequeued {len(items)} items")

        url_data_list = [
            URLData(
                short_code=item["short_code"],
                original_url=item["original_url"],
                created_at=datetime.fromisoformat(item["created_at"])
            )
            for item in items
        ]

        inserted = await repo.batch_create(url_data_list)
        print(f"Inserted {inserted} URLs into database")
        assert inserted == num_urls

        # Test 4: Verify in database
        print(f"\n=== Test 4: Verifying database ===")
        for short_code in short_codes:
            db_data = await repo.get_by_short_code(short_code)
            assert db_data is not None, f"Short code {short_code} not found in database"
            print(f"✓ Found {short_code} in database")

        # Test 5: Verify cache still works
        print(f"\n=== Test 5: Verifying cache ===")
        cached = await cache.get_async(short_codes[0])
        assert cached is not None
        print(f"✓ Cache working for {short_codes[0]}")

        # Test 6: Queue should be empty
        final_size = await queue.size()
        assert final_size == 0
        print(f"✓ Queue empty (size={final_size})")

        print(f"\n=== ALL TESTS PASSED ===")

    finally:
        # Cleanup
        await queue.clear()
        await queue.close()
        await cache._client.close()
        await repo.close()


if __name__ == "__main__":
    asyncio.run(test_end_to_end_batch_flow())
