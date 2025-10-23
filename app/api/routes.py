"""
FastAPI route definitions for URL shortener API.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse

from app.api.controllers import ShortenController, RedirectController
from app.core.schemas import ShortenRequest, ShortenResponse
from app.core.services import URLService
from app.config.dependencies import get_url_service
from app.config.settings import settings
from app.core.exceptions import (
    ShortCodeNotFoundException,
    ShortCodeAlreadyExistsException,
    InvalidURLException,
    URLShortenerException
)


router = APIRouter()


@router.get("/", tags=["Health"])
async def root():
    """
    Health check endpoint.

    Returns:
        Service status and metadata
    """
    return {
        "service": "URL Shortener",
        "version": "1.0.0",
        "status": "operational",
        "base_domain": settings.base_domain
    }


@router.post(
    "/v1/shorten",
    response_model=ShortenResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["URL Shortening"],
    summary="Shorten a URL",
    description="Generate a short URL for a given long URL"
)
async def shorten_url(
    request: ShortenRequest,
    url_service: URLService = Depends(get_url_service)
) -> ShortenResponse:
    """
    Shorten URL endpoint.

    Args:
        request: ShortenRequest with original_url
        url_service: Injected URLService dependency

    Returns:
        ShortenResponse with short_code, short_url, and created_at

    Raises:
        HTTPException 422: Invalid URL format
        HTTPException 409: Short code collision (rare)
        HTTPException 500: Internal server error

    Example:
        POST /v1/shorten
        {
            "original_url": "https://example.com/very/long/path"
        }

        Response (201):
        {
            "short_code": "abc1234",
            "short_url": "https://short.ly/abc1234",
            "created_at": "2024-01-15T10:30:00Z"
        }
    """
    try:
        controller = ShortenController(url_service)
        response = await controller.handle(request)
        return response

    except InvalidURLException as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid URL: {e.reason}"
        )

    except ShortCodeAlreadyExistsException as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Short code collision: {e.short_code}"
        )

    except URLShortenerException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}"
        )


@router.get(
    "/{short_code}",
    response_class=RedirectResponse,
    status_code=status.HTTP_302_FOUND,
    tags=["URL Redirection"],
    summary="Redirect to original URL",
    description="Resolve short code and redirect to the original URL"
)
async def redirect_url(
    short_code: str,
    url_service: URLService = Depends(get_url_service)
) -> RedirectResponse:
    """
    Redirect endpoint.

    Args:
        short_code: The 7-character short code to resolve
        url_service: Injected URLService dependency

    Returns:
        302 redirect to the original URL

    Raises:
        HTTPException 404: Short code not found
        HTTPException 500: Internal server error

    Example:
        GET /abc1234

        Response (302):
        Location: https://example.com/very/long/path
    """
    try:
        controller = RedirectController(url_service)
        response = await controller.handle(short_code)

        # Return 302 redirect to original URL
        return RedirectResponse(
            url=str(response.original_url),
            status_code=status.HTTP_302_FOUND
        )

    except ShortCodeNotFoundException as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short code not found: {e.short_code}"
        )

    except URLShortenerException as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal error: {str(e)}"
        )


@router.get("/v1/health", tags=["Health"])
async def health_check():
    """
    Detailed health check endpoint.

    Returns:
        Comprehensive service health status
    """
    return {
        "status": "healthy",
        "service": "url-shortener",
        "version": "1.0.0",
        "database": settings.database_path,
        "datacenter_id": settings.datacenter_id,
        "worker_id": settings.worker_id
    }
