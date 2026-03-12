"""
ResolveService — resolves short codes to original URLs.

Used by the redirect service only. Has no dependency on IDBuffer,
IDGenerator, or the URL queue — those are shorten-only concerns.
"""
from pydantic import HttpUrl
import logging

from shared.core.schemas import URLData, RedirectResponse
from shared.data.repositories import URLRepository
from shared.utils.interfaces.cache import Cache
from shared.utils.timer import Timer
from shared.core.exceptions import ShortCodeNotFoundException
from shared.middleware.metrics import (
    track_cache_operation,
    track_url_redirected,
)
from shared.middleware.metrics_enums import CacheOperation, CacheResult

logger = logging.getLogger(__name__)


class ResolveService:
    """
    Resolves short codes to original URLs.
    Flow: Redis cache → DB fallback → warm cache → return.
    """

    def __init__(
        self,
        url_repo: URLRepository,
        cache: Cache,
        service_name: str = "redirect",
    ):
        self.url_repo = url_repo
        self.cache = cache
        self.service_name = service_name

    async def resolve(self, short_code: str) -> RedirectResponse:
        """
        Resolve a short code to its original URL.

        Returns RedirectResponse on success.
        Raises ShortCodeNotFoundException if not found.
        """
        try:
            cached_data = await self.cache.get_async(short_code)
            if cached_data is not None:
                logger.info(f"Cache HIT: short_code={short_code} | original_url={cached_data.original_url}")
                track_cache_operation(CacheOperation.GET, CacheResult.HIT, self.service_name)
                track_url_redirected(self.service_name)
                return RedirectResponse(
                    original_url=HttpUrl(cached_data.original_url),
                    status="found",
                )

            logger.debug(f"Cache MISS: short_code={short_code}")
            track_cache_operation(CacheOperation.GET, CacheResult.MISS, self.service_name)

            db_timer = Timer()
            url_data = await self.url_repo.get_by_short_code(short_code)
            db_duration = db_timer.total()

            if url_data is None:
                logger.warning(f"Short code NOT FOUND: short_code={short_code} | db_query_time={db_duration:.2f}ms")
                raise ShortCodeNotFoundException(short_code)

            logger.info(f"DB lookup successful: short_code={short_code} | original_url={url_data.original_url} | db_query_time={db_duration:.2f}ms")

            cache_ok = await self.cache.set_async(short_code, url_data)
            if cache_ok:
                logger.debug(f"Cache WARM successful: short_code={short_code}")
                track_cache_operation(CacheOperation.SET, CacheResult.SUCCESS, self.service_name)
            else:
                logger.error(f"Cache WARM failed: short_code={short_code}")
                track_cache_operation(CacheOperation.SET, CacheResult.FAILURE, self.service_name)

            track_url_redirected(self.service_name)
            return RedirectResponse(
                original_url=HttpUrl(url_data.original_url),
                status="found",
            )

        except ShortCodeNotFoundException:
            raise
        except Exception as e:
            logger.error(f"Failed to resolve short_code={short_code} | error={str(e)}", exc_info=True)
            raise
