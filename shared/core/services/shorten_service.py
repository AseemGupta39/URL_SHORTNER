"""
ShortenService — shortens long URLs to unique short codes.

Used by the shorten service only. Has no dependency on resolve/redirect concerns.
"""
from datetime import datetime
from pydantic import HttpUrl
import logging
import asyncio

from shared.core.schemas import URLData, ShortenResponse
from shared.core.queue_messages import URLQueueMessage
from shared.data.repositories import URLRepository
from shared.utils.interfaces.cache import Cache
from shared.utils.interfaces.queue import Queue
from shared.utils.id_buffer import IDBuffer
from shared.utils.timer import Timer
from shared.utils.request_context import set_canonical_field
from shared.middleware.metrics import (
    track_cache_operation,
    track_queue_operation,
    track_url_shortened,
)
from shared.middleware.metrics_enums import (
    CacheOperation,
    CacheResult,
    QueueOperation,
)

logger = logging.getLogger(__name__)


class ShortenService:
    """
    Shortens long URLs to unique short codes.

    Architecture: Generate ID → concurrent cache+queue write → return instantly.
    DB persistence is handled asynchronously by the batch processor.
    """

    def __init__(
        self,
        url_repo: URLRepository,
        cache: Cache,
        queue: Queue,
        id_buffer: IDBuffer,
        base_domain: str = "short.ly",
        base_url_scheme: str = "https",
        service_name: str = "shorten",
    ):
        self.url_repo = url_repo
        self.cache = cache
        self.queue = queue
        self.id_buffer = id_buffer
        self.base_domain = base_domain
        self.base_url_scheme = base_url_scheme
        self.service_name = service_name

    async def shorten(self, original_url: HttpUrl) -> ShortenResponse:
        """
        Shorten a URL to a unique short code.

        Process:
        1. Generate unique short code (buffer → lock-free ~0ms, fallback → generator)
        2. Create URLData with timestamp
        3. Concurrent cache + queue writes
        4. Return response instantly (DB write is async via batch processor)
        """
        timer = Timer()
        logger.info("Shortening URL", extra={"original_url": str(original_url)})

        try:
            short_code = await self.id_buffer.get()
            timer.checkpoint('id_gen')
            set_canonical_field("short_code", short_code)
            logger.debug("Generated short code", extra={"short_code": short_code, "original_url": str(original_url), "id_gen_time_ms": round(timer.elapsed(end='id_gen'), 2)})

            url_data = URLData(
                short_code=short_code,
                original_url=str(original_url),
                created_at=datetime.utcnow()
            )

            # Concurrent cache + queue writes for optimal latency
            # Sequential: cache (1s timeout) + queue (3s timeout) = 4s worst case
            # Concurrent: max(1s, 3s) = 3s worst case (25% faster)
            queue_msg = URLQueueMessage.from_url_data(
                short_code=url_data.short_code,
                original_url=url_data.original_url,
                created_at=url_data.created_at
            )

            cache_task = asyncio.create_task(self.cache.set_async(short_code, url_data))
            queue_task = asyncio.create_task(self.queue.enqueue(queue_msg.to_dict()))

            results = await asyncio.gather(cache_task, queue_task, return_exceptions=True)
            timer.checkpoint('cache_queue')
            cache_result, queue_result = results[0], results[1]

            # cache raised = failure; None = success (set_async returns None)
            cache_ok = not isinstance(cache_result, Exception)
            if cache_ok:
                logger.debug("Cache WRITE successful", extra={"short_code": short_code})
                track_cache_operation(CacheOperation.SET, CacheResult.SUCCESS, self.service_name)
            else:
                logger.error("Cache WRITE failed", extra={"short_code": short_code, "error": str(cache_result)})
                track_cache_operation(CacheOperation.SET, CacheResult.FAILURE, self.service_name)
            set_canonical_field("cache_ok", cache_ok)

            # queue raised = failure; None = success (enqueue returns None)
            queue_ok = not isinstance(queue_result, Exception)
            if queue_ok:
                logger.debug("Queue ENQUEUE successful", extra={"short_code": short_code})
                track_queue_operation(QueueOperation.ENQUEUE, self.service_name)
            else:
                logger.error("Queue ENQUEUE failed", extra={"short_code": short_code, "error": str(queue_result)})
            set_canonical_field("queue_ok", queue_ok)

            # Fallback: synchronous DB write if queue failed
            if not queue_ok:
                logger.warning("Using sync DB write (queue failed)", extra={"short_code": short_code})
                set_canonical_field("db_fallback", True)
                try:
                    await self.url_repo.batch_create([url_data])
                    logger.info("URL saved to DB (sync fallback)", extra={"short_code": short_code, "original_url": str(original_url)})
                except Exception as db_error:
                    # Both queue AND DB failed — rollback cache to prevent orphaned entry
                    logger.critical("Queue and DB both failed, rolling back cache", extra={"short_code": short_code, "error": str(db_error)}, exc_info=True)

                    if cache_ok:
                        try:
                            await self.cache.delete_async(short_code)
                            logger.info("Cache rollback successful", extra={"short_code": short_code})
                            track_cache_operation(CacheOperation.DELETE, CacheResult.SUCCESS, self.service_name)
                        except Exception as rollback_error:
                            logger.critical("Cache rollback FAILED — orphaned cache entry will expire after TTL", extra={"short_code": short_code, "error": str(rollback_error)}, exc_info=True)
                            track_cache_operation(CacheOperation.DELETE, CacheResult.FAILURE, self.service_name)

                    raise

            short_url = f"{self.base_url_scheme}://{self.base_domain}/{short_code}"
            track_url_shortened(self.service_name)

            logger.info("URL shortened successfully", extra={"short_code": short_code, "original_url": str(original_url), "total_time_ms": round(timer.total(), 2)})

            return ShortenResponse(
                short_code=short_code,
                short_url=short_url,
                created_at=url_data.created_at
            )

        except Exception as e:
            try:
                logger.error("Failed to shorten URL", extra={"short_code": short_code, "original_url": str(original_url), "error": str(e), "total_time_ms": round(timer.total(), 2)}, exc_info=True)
            except NameError:
                # short_code wasn't created yet (error during ID generation)
                logger.error("Failed to shorten URL", extra={"original_url": str(original_url), "error": str(e), "total_time_ms": round(timer.total(), 2)}, exc_info=True)
            raise
