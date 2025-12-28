"""
Redirect Controller

Handles HTTP routes for URL redirection operations.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse as FastAPIRedirect
import logging

from shared.core.services import URLService
from shared.core.services.click_analytics_service import ClickAnalyticsService
from shared.config.dependencies import get_url_service, get_click_analytics_service
from shared.core.exceptions import ShortCodeNotFoundException

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{short_code}", tags=["Redirect"])
async def redirect_url(
    short_code: str,
    request: Request,
    url_service: URLService = Depends(get_url_service),
    click_service: ClickAnalyticsService = Depends(get_click_analytics_service)
):
    """
    Redirect to original URL using short code and track click analytics.

    Returns 302 redirect to original URL.
    Raises 404 if short code not found.

    Click tracking is fail-open: redirect works even if tracking fails.
    """
    try:
        logger.info(f"Resolving short code: {short_code}")
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
            logger.error(
                f"Click tracking failed (non-critical): short_code={short_code} | error={str(e)}",
                exc_info=True
            )

        return FastAPIRedirect(
            url=str(result.original_url),
            status_code=302
        )
    except ShortCodeNotFoundException:
        logger.warning(f"Short code not found: {short_code}")
        raise HTTPException(status_code=404, detail="Short code not found")
