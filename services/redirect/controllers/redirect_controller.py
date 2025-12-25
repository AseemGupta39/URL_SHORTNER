"""
Redirect Controller

Handles HTTP routes for URL redirection operations.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse as FastAPIRedirect
import logging

from shared.core.services import URLService
from shared.config.dependencies import get_url_service
from shared.core.exceptions import ShortCodeNotFoundException

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{short_code}", tags=["Redirect"])
async def redirect_url(
    short_code: str,
    url_service: URLService = Depends(get_url_service)
):
    """
    Redirect to original URL using short code.

    Returns 302 redirect to original URL.
    Raises 404 if short code not found.
    """
    try:
        logger.info(f"Resolving short code: {short_code}")
        result = await url_service.resolve(short_code)
        return FastAPIRedirect(
            url=str(result.original_url),
            status_code=302
        )
    except ShortCodeNotFoundException:
        logger.warning(f"Short code not found: {short_code}")
        raise HTTPException(status_code=404, detail="Short code not found")
