"""
Redirect Controller

Handles HTTP routes for URL redirection operations.
"""
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse as FastAPIRedirect
import logging
import re

from shared.core.services import ResolveService
from shared.core.services.click_analytics_service import ClickAnalyticsService
from shared.config.dependencies import get_resolve_service, get_click_analytics_service
from shared.core.exceptions import ShortCodeNotFoundException
from shared.utils.request_context import set_canonical_field
from services.redirect.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Short code validation pattern: exactly 8 alphanumeric characters (Base62)
SHORT_CODE_PATTERN = re.compile(r'^[A-Za-z0-9]{8}$')

# Concurrency limiter — prevents event loop starvation under spike load
# 0 = unlimited. See docs/SEMAPHORE_FINDINGS.md for benchmarks
_concurrency_limiter = (
    asyncio.Semaphore(settings.max_concurrent_requests)
    if settings.max_concurrent_requests > 0
    else None
)
logger.info("Concurrency limiter configured", extra={"max_concurrent_requests": settings.max_concurrent_requests or "unlimited"})


@router.get("/{short_code}", tags=["Redirect"])
async def redirect_url(
    short_code: str,
    request: Request,
    url_service: ResolveService = Depends(get_resolve_service),
    click_service: ClickAnalyticsService = Depends(get_click_analytics_service)
):
    """
    Redirect to original URL using short code and track click analytics.

    Returns 302 redirect to original URL.
    Raises 400 if short code format is invalid.
    Raises 404 if short code not found.

    Click tracking is fail-open: redirect works even if tracking fails.
    """
    # Validate short code format BEFORE any processing (and before semaphore)
    # Prevents cache pollution, path traversal, and DoS attacks
    if not SHORT_CODE_PATTERN.match(short_code):
        logger.warning("Invalid short code format", extra={"short_code": short_code})
        set_canonical_field("short_code", short_code)
        raise HTTPException(
            status_code=400,
            detail="Invalid short code format. Must be exactly 8 alphanumeric characters."
        )

    if _concurrency_limiter:
        async with _concurrency_limiter:
            return await _resolve_and_redirect(short_code, request, url_service, click_service)
    else:
        return await _resolve_and_redirect(short_code, request, url_service, click_service)


async def _resolve_and_redirect(short_code, request, url_service, click_service):
    """Resolve short code and redirect. Extracted to avoid code duplication in semaphore branches."""
    set_canonical_field("short_code", short_code)
    try:
        logger.info("Resolving short code", extra={"short_code": short_code})
        result = await url_service.resolve(short_code)

        # Track click asynchronously (fail-open - don't block redirect)
        try:
            # Extract client information from request
            ip_address = request.client.host if request.client else "unknown"
            user_agent = request.headers.get("user-agent", "unknown")
            referrer = request.headers.get("referer", None)  # Note: HTTP spec uses "referer" (typo)

            # Track click (async, non-blocking, fail-open)
            await click_service.track_click(
                short_code=short_code,
                original_url=str(result.original_url),
                ip_address=ip_address,
                user_agent=user_agent,
                referrer=referrer
            )
        except Exception as e:
            # Log but don't fail redirect
            logger.error("Click tracking failed", extra={"short_code": short_code, "error": str(e)}, exc_info=True)

        return FastAPIRedirect(
            url=str(result.original_url),
            status_code=302
        )
    except ShortCodeNotFoundException:
        logger.warning("Short code not found", extra={"short_code": short_code})
        raise HTTPException(status_code=404, detail="Short code not found")
