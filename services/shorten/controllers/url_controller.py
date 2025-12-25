"""
URL Shortening Controller

Handles HTTP routes for URL shortening operations.
"""
from fastapi import APIRouter, Depends
import logging

from shared.core.schemas import ShortenRequest, ShortenResponse
from shared.core.services import URLService
from shared.config.dependencies import get_url_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/v1/shorten", response_model=ShortenResponse, tags=["Shorten"])
async def shorten_url(
    request: ShortenRequest,
    url_service: URLService = Depends(get_url_service)
):
    """
    Create a short URL from a long URL.

    This service uses Snowflake ID generation with unique DATACENTER_ID/WORKER_ID.
    """
    logger.info(f"Shortening URL: {request.original_url}")
    result = await url_service.shorten(request.original_url)
    return result
