"""
Business logic layer for URL shortening service.
"""
from datetime import datetime
from typing import Optional
from pydantic import HttpUrl
import logging

from shared.core.schemas import URLData, ShortenResponse, RedirectResponse
from shared.core.queue_messages import URLQueueMessage
from shared.data.repositories import URLRepository
from shared.utils.interfaces.id_generator import IDGenerator
from shared.utils.interfaces.cache import Cache
from shared.utils.interfaces.queue import Queue
from shared.core.exceptions import ShortCodeNotFoundException

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
        base_url_scheme: str = "https"
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
        """
        self.url_repo = url_repo
        self.id_generator = id_generator
        self.cache = cache
        self.queue = queue
        self.base_domain = base_domain
        self.base_url_scheme = base_url_scheme

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
        logger.info(f"Shortening URL: {original_url}")

        try:
            # Generate short code
            short_code = await self.id_generator.generate_short_code()
            logger.debug(f"Generated short_code={short_code} for url={original_url}")

            url_data = URLData(
                short_code=short_code,
                original_url=str(original_url),
                created_at=datetime.now()
            )

            # Write to cache first for immediate availability
            if self.cache:
                try:
                    await self.cache.set_async(short_code, url_data)
                    logger.debug(f"Cache WRITE successful: short_code={short_code}")
                except Exception as e:
                    logger.error(
                        f"Cache WRITE failed: short_code={short_code} | error={str(e)}",
                        exc_info=True
                    )
                    # Continue even if cache fails - queue will persist to DB

            # Queue for batch insert
            if self.queue:
                try:
                    queue_msg = URLQueueMessage.from_url_data(
                        short_code=url_data.short_code,
                        original_url=url_data.original_url,
                        created_at=url_data.created_at
                    )
                    await self.queue.enqueue(queue_msg.to_dict())
                    logger.debug(f"Queue ENQUEUE successful: short_code={short_code}")
                except Exception as e:
                    logger.error(
                        f"Queue ENQUEUE failed: short_code={short_code} | error={str(e)}",
                        exc_info=True
                    )
                    # Critical: if queue fails, URL won't persist to DB!
                    raise

            short_url = f"{self.base_url_scheme}://{self.base_domain}/{short_code}"

            logger.info(
                f"URL shortened successfully: short_code={short_code} | "
                f"short_url={short_url} | original_url={original_url}"
            )

            return ShortenResponse(
                short_code=short_code,
                short_url=short_url,
                created_at=url_data.created_at
            )

        except Exception as e:
            logger.error(
                f"Failed to shorten URL: original_url={original_url} | error={str(e)}",
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
            # Check cache first (if enabled)
            if self.cache:
                try:
                    cached_data = await self.cache.get_async(short_code)
                    if cached_data is not None:
                        logger.info(
                            f"Cache HIT: short_code={short_code} | "
                            f"original_url={cached_data.original_url}"
                        )
                        return RedirectResponse(
                            original_url=HttpUrl(cached_data.original_url),
                            status="found"
                        )
                    logger.debug(f"Cache MISS: short_code={short_code}")
                except Exception as e:
                    logger.error(
                        f"Cache READ failed: short_code={short_code} | error={str(e)}",
                        exc_info=True
                    )
                    # Continue to DB lookup on cache error

            # Query repository on cache miss
            logger.debug(f"Querying DB for short_code={short_code}")
            import time
            db_start = time.time()

            url_data = await self.url_repo.get_by_short_code(short_code)

            db_duration_ms = (time.time() - db_start) * 1000

            if url_data is None:
                logger.warning(
                    f"Short code NOT FOUND: short_code={short_code} | "
                    f"db_query_time={db_duration_ms:.2f}ms"
                )
                raise ShortCodeNotFoundException(short_code)

            logger.info(
                f"DB lookup successful: short_code={short_code} | "
                f"original_url={url_data.original_url} | "
                f"db_query_time={db_duration_ms:.2f}ms"
            )

            # Warm cache for future requests
            if self.cache:
                try:
                    await self.cache.set_async(short_code, url_data)
                    logger.debug(f"Cache WARM successful: short_code={short_code}")
                except Exception as e:
                    logger.error(
                        f"Cache WARM failed: short_code={short_code} | error={str(e)}",
                        exc_info=True
                    )
                    # Don't fail the request if cache warm fails

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
