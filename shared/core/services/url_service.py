"""
Business logic layer for URL shortening service.
"""
from datetime import datetime
from typing import Optional
from pydantic import HttpUrl
import logging
import asyncio

from shared.core.schemas import URLData, ShortenResponse, RedirectResponse
from shared.core.queue_messages import URLQueueMessage
from shared.data.repositories import URLRepository
from shared.utils.interfaces.id_generator import IDGenerator
from shared.utils.interfaces.cache import Cache
from shared.utils.interfaces.queue import Queue
from shared.utils.id_buffer import IDBuffer
from shared.core.exceptions import ShortCodeNotFoundException
from shared.utils.timer import Timer
from shared.middleware.metrics import (
    track_cache_operation,
    track_queue_operation,
    track_url_shortened,
    track_url_redirected
)
from shared.middleware.metrics_enums import (
    CacheOperation,
    CacheResult,
    QueueOperation
)

logger = logging.getLogger(__name__)


class URLService:
    """
    Service layer handling URL shortening and resolution business logic.

    Architecture: Cache-first with async queue-based persistence.
    """

    def __init__(
        self,
        url_repo: URLRepository,
        id_generator: IDGenerator,
        cache: Cache,
        queue: Queue,
        base_domain: str = "short.ly",
        base_url_scheme: str = "https",
        service_name: str = "shorten",
        id_buffer: Optional[IDBuffer] = None,
    ):
        """
        Initialize URL service.

        Args:
            url_repo: Repository for URL data persistence
            id_generator: Generator for unique short codes
            cache: Cache for immediate availability (Redis or LRU)
            queue: Queue for batch processing (Redis, Kafka, etc.)
            base_domain: Base domain for constructing short URLs
            base_url_scheme: URL scheme (http or https)
            service_name: Service name for metrics (shorten/redirect/batch_processor)
            id_buffer: Pre-generation buffer for lock-free ID hot path (optional).
                       When provided, shorten() calls buffer.get() (~0ms, no lock).
                       Falls back to id_generator.generate_short_code() if None
                       (redirect and batch_processor services do not shorten URLs).
        """
        self.url_repo = url_repo
        self.id_generator = id_generator
        self.cache = cache
        self.queue = queue
        self.base_domain = base_domain
        self.base_url_scheme = base_url_scheme
        self.service_name = service_name
        self.id_buffer = id_buffer

    async def shorten(self, original_url: HttpUrl) -> ShortenResponse:
        """
        Shorten a URL to a unique short code.

        Args:
            original_url: The original URL to shorten

        Returns:
            ShortenResponse containing short code, short URL, and creation timestamp

        Process:
        1. Generate unique short code
        2. Create URLData with timestamp
        3. Write to cache (immediate availability)
        4. Queue for batch DB insert
        5. Return response instantly
        """
        timer = Timer()
        logger.info(f"Shortening URL: {original_url}")

        try:
            # Generate short code — use pre-generation buffer (lock-free, ~0ms) when
            # available, fall back to direct generator (acquires asyncio.Lock) otherwise.
            if self.id_buffer is not None:
                short_code = await self.id_buffer.get()
            else:
                short_code = await self.id_generator.generate_short_code()
            timer.checkpoint('id_gen')
            logger.debug(f"Generated short_code={short_code} for url={original_url} | id_gen_time={timer.elapsed(end='id_gen'):.2f}ms")

            url_data = URLData(
                short_code=short_code,
                original_url=str(original_url),
                created_at=datetime.utcnow()
            )

            # Concurrent cache + queue writes for optimal latency
            # Sequential: cache (1s timeout) + queue (3s timeout) = 4s worst case
            # Concurrent: max(1s, 3s) = 3s worst case (25% faster!)
            queue_msg = URLQueueMessage.from_url_data(
                short_code=url_data.short_code,
                original_url=url_data.original_url,
                created_at=url_data.created_at
            )

            # Create tasks for parallel execution (same thread, interleaved by event loop)
            cache_task = asyncio.create_task(self.cache.set_async(short_code, url_data))
            queue_task = asyncio.create_task(self.queue.enqueue(queue_msg.to_dict()))

            # Execute both concurrently, handle exceptions gracefully
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
                    # CRITICAL: Both queue AND DB failed - rollback cache to prevent orphaned entry
                    pool_status = self.url_repo.get_pool_status()
                    logger.error(
                        f"CRITICAL: Queue and DB both failed, rolling back cache: "
                        f"short_code={short_code} | pool_status={pool_status} | error={db_error}",
                        exc_info=True
                    )

                    # Rollback cache write (compensating transaction)
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

                    # Re-raise DB error to fail the request (user gets 500, not 200)
                    raise

            short_url = f"{self.base_url_scheme}://{self.base_domain}/{short_code}"

            # Track business event
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

    async def resolve(self, short_code: str) -> RedirectResponse:
        """
        Resolve a short code to its original URL with caching support.

        Args:
            short_code: The short code to resolve

        Returns:
            RedirectResponse containing the original URL

        Raises:
            ShortCodeNotFoundException: If the short code doesn't exist
        """
        logger.info(f"Resolving short_code={short_code}")

        try:
            # Check cache first
            cached_data = await self.cache.get_async(short_code)
            if cached_data is not None:
                logger.info(
                    f"Cache HIT: short_code={short_code} | "
                    f"original_url={cached_data.original_url}"
                )
                track_cache_operation(CacheOperation.GET, CacheResult.HIT, self.service_name)
                track_url_redirected(self.service_name)
                return RedirectResponse(
                    original_url=HttpUrl(cached_data.original_url),
                    status="found"
                )
            logger.debug(f"Cache MISS: short_code={short_code}")
            track_cache_operation(CacheOperation.GET, CacheResult.MISS, self.service_name)

            # Query repository on cache miss
            logger.debug(f"Querying DB for short_code={short_code}")
            db_timer = Timer()

            url_data = await self.url_repo.get_by_short_code(short_code)

            db_duration = db_timer.total()

            if url_data is None:
                logger.warning(
                    f"Short code NOT FOUND: short_code={short_code} | "
                    f"db_query_time={db_duration:.2f}ms"
                )
                raise ShortCodeNotFoundException(short_code)

            logger.info(
                f"DB lookup successful: short_code={short_code} | "
                f"original_url={url_data.original_url} | "
                f"db_query_time={db_duration:.2f}ms"
            )

            # Warm cache for future requests
            cache_warm_success = await self.cache.set_async(short_code, url_data)
            if cache_warm_success:
                logger.debug(f"Cache WARM successful: short_code={short_code}")
                track_cache_operation(CacheOperation.SET, CacheResult.SUCCESS, self.service_name)
            else:
                logger.error(f"Cache WARM failed: short_code={short_code}", exc_info=True)
                track_cache_operation(CacheOperation.SET, CacheResult.FAILURE, self.service_name)
                # Don't fail the request if cache warm fails

            # Track business event
            track_url_redirected(self.service_name)

            return RedirectResponse(
                original_url=HttpUrl(url_data.original_url),
                status="found"
            )

        except ShortCodeNotFoundException:
            # Re-raise as-is (already logged above)
            raise
        except Exception as e:
            logger.error(
                f"Failed to resolve short_code={short_code} | error={str(e)}",
                exc_info=True
            )
            raise
