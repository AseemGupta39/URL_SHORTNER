"""
Business logic layer for URL shortening service.
"""
from datetime import datetime
from typing import Optional
from pydantic import HttpUrl

from app.core.schemas import URLData, ShortenResponse, RedirectResponse
from app.data.repositories import URLRepository
from app.utils.id_generator import IDGenerator
from app.utils.cache import Cache
from app.core.exceptions import ShortCodeNotFoundException
from app.utils.logger import get_logger

logger = get_logger()


class URLService:
    """
    Service layer handling URL shortening and resolution business logic.

    Coordinates between ID generation, caching, and data persistence layers.
    Cache at service layer allows flexibility (in-memory, Redis, etc.)
    """

    def __init__(
        self,
        url_repo: URLRepository,
        id_generator: IDGenerator,
        base_domain: str = "short.ly",
        base_url_scheme: str = "https",
        cache: Optional[Cache] = None
    ):
        """
        Initialize URL service.

        Args:
            url_repo: Repository for URL data persistence
            id_generator: Generator for unique short codes
            base_domain: Base domain for constructing short URLs
            base_url_scheme: URL scheme (http or https)
            cache: Optional cache (in-memory or Redis) for performance
        """
        self.url_repo = url_repo
        self.id_generator = id_generator
        self.base_domain = base_domain
        self.base_url_scheme = base_url_scheme
        self.cache = cache

    async def shorten(self, original_url: HttpUrl) -> ShortenResponse:
        """
        Shorten a URL to a unique short code.

        Args:
            original_url: The original URL to shorten

        Returns:
            ShortenResponse containing short code, short URL, and creation timestamp

        Process:
        1. Generate unique short code via ID generator
        2. Create URLData with current timestamp
        3. Warm cache first (for immediate availability)
        4. Persist to repository
        5. Return response with constructed short URL
        """
        # Generate unique short code
        short_code = await self.id_generator.generate_short_code()
        logger.debug(f"Generated short code: {short_code} for URL: {original_url}")

        # Create URL data with current timestamp
        url_data = URLData(
            short_code=short_code,
            original_url=str(original_url),
            created_at=datetime.now()
        )

        # Warm cache first before DB operation
        if self.cache:
            self.cache.set(short_code, url_data)
            logger.debug(f"Cache warmed with new short code: {short_code}")

        # Persist to repository
        created_url = await self.url_repo.create(url_data)

        # Construct short URL
        short_url = f"{self.base_url_scheme}://{self.base_domain}/{short_code}"

        # Return response
        return ShortenResponse(
            short_code=created_url.short_code,
            short_url=short_url,
            created_at=created_url.created_at
        )

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
        # Check cache first (if enabled)
        if self.cache:
            cached_data = self.cache.get(short_code)
            if cached_data is not None:
                logger.debug(f"Cache HIT: {short_code}")
                return RedirectResponse(
                    original_url=HttpUrl(cached_data.original_url),
                    status="found"
                )
            logger.debug(f"Cache MISS: {short_code}")

        # Query repository on cache miss
        url_data = await self.url_repo.get_by_short_code(short_code)

        if url_data is None:
            logger.warning(f"Short code not found: {short_code}")
            raise ShortCodeNotFoundException(short_code)

        # Warm cache for future requests
        if self.cache:
            self.cache.set(short_code, url_data)
            logger.debug(f"Cache updated: {short_code}")

        return RedirectResponse(
            original_url=HttpUrl(url_data.original_url),
            status="found"
        )
