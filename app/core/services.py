"""
Business logic layer for URL shortening service.
"""
from datetime import datetime
from pydantic import HttpUrl

from app.core.schemas import URLData, ShortenResponse, RedirectResponse
from app.data.repositories import URLRepository
from app.utils.id_generator import IDGenerator
from app.core.exceptions import ShortCodeNotFoundException
from app.utils.logger import get_logger

logger = get_logger()


class URLService:
    """
    Service layer handling URL shortening and resolution business logic.

    Coordinates between ID generation and data persistence layers.
    """

    def __init__(
        self,
        url_repo: URLRepository,
        id_generator: IDGenerator,
        base_domain: str = "short.ly",
        base_url_scheme: str = "https"
    ):
        """
        Initialize URL service.

        Args:
            url_repo: Repository for URL data persistence
            id_generator: Generator for unique short codes
            base_domain: Base domain for constructing short URLs
            base_url_scheme: URL scheme (http or https)
        """
        self.url_repo = url_repo
        self.id_generator = id_generator
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
        1. Generate unique short code via ID generator
        2. Create URLData with current timestamp
        3. Persist to repository
        4. Return response with constructed short URL
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
        Resolve a short code to its original URL.

        Args:
            short_code: The short code to resolve

        Returns:
            RedirectResponse containing the original URL

        Raises:
            ShortCodeNotFoundException: If the short code doesn't exist

        Process:
        1. Look up short code in repository
        2. Raise exception if not found
        3. Return redirect response with original URL
        """
        # Look up URL data
        url_data = await self.url_repo.get_by_short_code(short_code)

        # Check if found
        if url_data is None:
            logger.warning(f"Attempted to resolve non-existent short code: {short_code}")
            raise ShortCodeNotFoundException(short_code)

        # Return redirect response
        return RedirectResponse(
            original_url=HttpUrl(url_data.original_url),
            status="found"
        )
