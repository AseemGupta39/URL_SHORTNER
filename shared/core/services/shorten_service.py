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
        logger.info(f"Shortening URL: {original_url}")

        try:
            short_code = await self.id_buffer.get()
            timer.checkpoint('id_gen')
            logger.debug(f"Generated short_code={short_code} for url={original_url} | id_gen_time={timer.elapsed(end='id_gen'):.2f}ms")

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
            cache_success, queue_success = results[0], results[1]

            # Handle cache result
            if isinstance(cache_success, Exception):
                logger.error(
                    f"Cache WRITE raised exception: short_code={short_code} | error={cache_success}",
                    exc_info=True
                )
                track_cache_operation(CacheOperation.SET, CacheResult.FAILURE, self.service_name)
                cache_success = False
            elif cache_success:
                logger.debug(f"Cache WRITE successful: short_code={short_code}")
                track_cache_operation(CacheOperation.SET, CacheResult.SUCCESS, self.service_name)
            else:
                logger.error(f"Cache WRITE failed: short_code={short_code}", exc_info=True)
                track_cache_operation(CacheOperation.SET, CacheResult.FAILURE, self.service_name)

            # Handle queue result
            if isinstance(queue_success, Exception):
                logger.error(
                    f"Queue ENQUEUE raised exception: short_code={short_code} | error={queue_success}",
                    exc_info=True
                )
                queue_success = False
            elif queue_success:
                logger.debug(f"Queue ENQUEUE successful: short_code={short_code}")
                track_queue_operation(QueueOperation.ENQUEUE, self.service_name)
            else:
                logger.error(f"Queue ENQUEUE failed: short_code={short_code}", exc_info=True)

            # Fallback: synchronous DB write if queue unavailable or failed
            if not queue_success:
                logger.warning(
                    f"Using sync DB write (queue unavailable or failed): short_code={short_code}"
                )
                try:
                    await self.url_repo.batch_create([url_data])
                    logger.info(
                        f"URL saved to DB (sync fallback): short_code={short_code} | "
                        f"original_url={original_url}"
                    )
                except Exception as db_error:
                    # CRITICAL: Both queue AND DB failed — rollback cache to prevent orphaned entry
                    pool_status = self.url_repo.get_pool_status()
                    logger.error(
                        f"CRITICAL: Queue and DB both failed, rolling back cache: "
                        f"short_code={short_code} | pool_status={pool_status} | error={db_error}",
                        exc_info=True
                    )

                    if cache_success:
                        rollback_success = await self.cache.delete_async(short_code)
                        if rollback_success:
                            logger.info(f"Cache rollback successful: short_code={short_code}")
                            track_cache_operation(CacheOperation.DELETE, CacheResult.SUCCESS, self.service_name)
                        else:
                            logger.error(
                                f"Cache rollback FAILED: short_code={short_code} | "
                                f"Orphaned cache entry will cause 404 after TTL expires!",
                                exc_info=True
                            )
                            track_cache_operation(CacheOperation.DELETE, CacheResult.FAILURE, self.service_name)

                    raise

            short_url = f"{self.base_url_scheme}://{self.base_domain}/{short_code}"
            track_url_shortened(self.service_name)

            logger.info(
                f"URL shortened successfully: short_code={short_code} | "
                f"short_url={short_url} | original_url={original_url} | "
                f"duration={timer.total():.2f}ms | "
                f"breakdown: id_gen={timer.elapsed(end='id_gen'):.2f}ms, cache_queue={timer.elapsed(end='cache_queue', start='id_gen'):.2f}ms"
            )

            return ShortenResponse(
                short_code=short_code,
                short_url=short_url,
                created_at=url_data.created_at
            )

        except Exception as e:
            try:
                logger.error(
                    f"Failed to shorten URL: short_code={short_code} | "
                    f"original_url={original_url} | error={str(e)} | "
                    f"duration={timer.total():.2f}ms",
                    exc_info=True
                )
            except NameError:
                # short_code wasn't created yet (error during ID generation)
                logger.error(
                    f"Failed to shorten URL: original_url={original_url} | "
                    f"error={str(e)} | duration={timer.total():.2f}ms",
                    exc_info=True
                )
            raise
