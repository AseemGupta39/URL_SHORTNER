"""
Batch Processing Controller

Handles batch URL processing endpoints.
Note: /health endpoint and startup/shutdown events remain in main.py
"""
from typing import Optional
import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from shared.config.settings import get_settings
from shared.config.dependencies import get_url_repository, get_url_queue, get_url_dlq
from shared.data.repositories import URLRepository
from shared.utils.interfaces.queue import Queue

# Import worker function from separate module
from services.batch_processor.batch_worker import process_batch_from_queue

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

# Module-level instances (initialized by main.py startup event)
url_repo: Optional[URLRepository] = None
url_queue: Optional[Queue] = None
url_dlq: Optional[Queue] = None


def set_dependencies(repo: URLRepository, queue: Queue, dlq: Queue) -> None:
    """Set repository, queue, and DLQ instances (called from main.py startup)."""
    global url_repo, url_queue, url_dlq
    url_repo = repo
    url_queue = queue
    url_dlq = dlq


async def ensure_queue_initialized() -> Queue:
    """Ensure URL queue is initialized (lazy initialization for serverless)."""
    global url_queue

    if url_queue is None:
        logger.info("Lazy-initializing URL queue for serverless environment", extra={"queue_name": "url_batch_queue"})
        url_queue = await get_url_queue()
        logger.info("URL queue initialized successfully", extra={"queue_name": "url_batch_queue"})

    return url_queue


async def ensure_repo_initialized() -> URLRepository:
    """Ensure URL repository is initialized (lazy initialization for serverless)."""
    global url_repo

    if url_repo is None:
        logger.info("Lazy-initializing URL repository for serverless environment", extra={"component": "url_repository"})
        url_repo = await get_url_repository()
        await url_repo.initialize()
        logger.info("URL repository initialized successfully", extra={"component": "url_repository"})

    return url_repo


async def ensure_dlq_initialized() -> Queue:
    """Ensure DLQ is initialized (lazy initialization for serverless)."""
    global url_dlq

    if url_dlq is None:
        logger.info("Lazy-initializing DLQ for serverless environment", extra={"queue_name": "url_batch_queue_dlq"})
        url_dlq = await get_url_dlq()
        logger.info("DLQ initialized successfully", extra={"queue_name": "url_batch_queue_dlq"})

    return url_dlq


@router.get("/status")
async def get_status() -> dict:
    """
    Get batch processor status and queue information.

    Returns queue size, configuration, and last processing stats.
    """
    try:
        # Lazy-initialize queue for serverless
        queue = await ensure_queue_initialized()

        if not queue:
            return {
                "status": "error",
                "message": "Failed to initialize Redis queue",
                "queue_size": 0,
                "debug": {
                    "redis_url_set": bool(settings.redis_url)
                }
            }

        queue_size = await queue.size()

        return {
            "status": "healthy",
            "service": "batch_processor",
            "queue_size": queue_size,
            "config": {
                "batch_size": settings.batch_size,
                "batch_interval_seconds": settings.batch_interval_seconds,
            },
            "info": "Use POST /api/cron/process-batch to manually trigger processing"
        }
    except Exception as e:
        logger.error(
            "Failed to get batch status",
            extra={"error": str(e)},
            exc_info=True,
        )
        return {
            "status": "error",
            "message": str(e),
            "queue_size": 0
        }


@router.post("/api/cron/process-batch")
async def process_batch() -> JSONResponse:
    """
    Process a batch of URLs from the queue and insert into database.

    This endpoint can be called manually or via scheduled cron job.

    Returns:
        JSON with processing statistics
    """
    try:
        # Lazy-initialize queue, repo, and DLQ
        queue = await ensure_queue_initialized()
        repo = await ensure_repo_initialized()
        dlq = await ensure_dlq_initialized()

        if not queue:
            raise HTTPException(
                status_code=503,
                detail="Queue not enabled or failed to initialize"
            )

        # Process batch using worker function
        result = await process_batch_from_queue(repo, queue, dlq)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Batch processed successfully",
                "batch_id": result["batch_id"],
                "processed": result["processed"],
                "queue_size_before": result["queue_size_before"],
                "queue_size_after": result["queue_size_after"],
                "duration_ms": result["duration_ms"],
                "failed_parse": result.get("failed_parse", 0)
            }
        )

    except Exception as e:
        logger.error(
            "Batch processing failed",
            extra={"error": str(e)},
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Batch processing failed: {str(e)}"
        )
