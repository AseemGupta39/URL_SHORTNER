"""
HTTP controllers for URL shortening and redirection endpoints.

Controllers handle HTTP request/response transformation and delegate
business logic to the service layer.
"""
from pydantic import HttpUrl

from app.core.schemas import ShortenRequest, ShortenResponse, RedirectResponse
from app.core.services import URLService


class ShortenController:
    """
    Controller for URL shortening endpoint.

    Handles POST /v1/shorten requests to create short URLs.
    """

    def __init__(self, url_service: URLService) -> None:
        """
        Initialize shorten controller.

        Args:
            url_service: Service handling URL shortening business logic
        """
        self.url_service = url_service

    async def handle(self, request: ShortenRequest) -> ShortenResponse:
        """
        Handle URL shortening request.

        Args:
            request: Validated request containing original URL

        Returns:
            ShortenResponse with short code, short URL, and creation timestamp

        Process:
        1. Extract original URL from request
        2. Delegate to service layer for shortening
        3. Return response with short URL details

        Example:
            >>> request = ShortenRequest(original_url="https://example.com")
            >>> response = await controller.handle(request)
            >>> response.short_code
            'abc1234'
        """
        # Delegate to service layer
        response = await self.url_service.shorten(request.original_url)

        return response


class RedirectController:
    """
    Controller for URL redirection endpoint.

    Handles GET /{short_code} requests to redirect to original URLs.
    """

    def __init__(self, url_service: URLService) -> None:
        """
        Initialize redirect controller.

        Args:
            url_service: Service handling URL resolution business logic
        """
        self.url_service = url_service

    async def handle(self, short_code: str) -> RedirectResponse:
        """
        Handle URL redirection request.

        Args:
            short_code: The 7-character short code to resolve

        Returns:
            RedirectResponse containing the original URL

        Raises:
            ShortCodeNotFoundException: If short code doesn't exist (propagated from service)

        Process:
        1. Receive short code from path parameter
        2. Delegate to service layer for resolution
        3. Return response with original URL

        Example:
            >>> response = await controller.handle("abc1234")
            >>> response.original_url
            HttpUrl('https://example.com')
        """
        # Delegate to service layer
        response = await self.url_service.resolve(short_code)

        return response
