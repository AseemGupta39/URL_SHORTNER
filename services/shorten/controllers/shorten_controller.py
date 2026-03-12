"""
Shorten Controller

Handles HTTP routes for URL shortening operations.
"""
import asyncio
from fastapi import APIRouter, Depends
import logging

from shared.core.schemas import ShortenRequest, ShortenResponse
from shared.core.services import ShortenService
from shared.config.dependencies import get_shorten_service
from services.shorten.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Concurrency limiter — prevents event loop starvation under spike load
# 0 = unlimited. See docs/SEMAPHORE_FINDINGS.md for benchmarks
_concurrency_limiter = (
    asyncio.Semaphore(settings.max_concurrent_requests)
    if settings.max_concurrent_requests > 0
    else None
)
logger.info(f"Concurrency limiter: {settings.max_concurrent_requests or 'unlimited'}")


@router.post("/v1/shorten", response_model=ShortenResponse, tags=["Shorten"])
async def shorten_url(
    request: ShortenRequest,
    shorten_service: ShortenService = Depends(get_shorten_service)
):
    """
    Create a short URL from a long URL.

    Uses Snowflake ID generation with pre-filled IDBuffer for lock-free ID generation.
    """
    logger.info(f"Shortening URL: {request.original_url}")
    if _concurrency_limiter:
        async with _concurrency_limiter:
            return await shorten_service.shorten(request.original_url)
    else:
        return await shorten_service.shorten(request.original_url)
