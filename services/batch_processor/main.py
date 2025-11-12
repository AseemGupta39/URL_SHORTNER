"""
Batch Processor Service - Processes queued URLs and inserts them into database.
Runs on Vercel Cron or as a standalone scheduled job.
"""
import sys
from pathlib import Path
from datetime import datetime
import asyncio
import uuid

service_dir = Path(__file__).parent
env_file = service_dir / ".env"

from dotenv import load_dotenv
load_dotenv(env_file, override=True)

project_root = service_dir.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from shared.config.settings import get_settings
from shared.config.dependencies import get_url_repository
from shared.data.repositories import URLRepository
from shared.utils.redis_queue import get_redis_queue
from shared.core.schemas import URLData
from shared.core.queue_messages import URLQueueMessage
from shared.utils.logger import get_logger
from shared.utils import request_context

logger = get_logger()
settings = get_settings()

app = FastAPI(
    title="Batch Processor Service",
    version="1.0.0",
    description="Processes queued URL insertions in batches"
)

# Global instances (initialized in startup event)
url_repo: URLRepository = None
redis_queue = None

# Background task control
background_task = None


async def background_batch_processor():
    """
    Background task that processes batch queue periodically.
    Only runs when ENABLE_BACKGROUND_SCHEDULER=true (local dev).
    In production, Vercel Cron calls the endpoint directly.
    """
    logger.info(f"Background scheduler started (interval={settings.batch_interval_seconds}s)")

    while True:
        try:
            await asyncio.sleep(settings.batch_interval_seconds)

            if not redis_queue:
                continue

            queue_size = await redis_queue.size()

            if queue_size == 0:
                logger.debug("Queue empty, skipping batch processing")
                continue

            # Generate unique batch ID (first 12 chars of UUID for tracking)
            batch_id = str(uuid.uuid4())[:12]
            request_context.set_request_id(f"batch-{batch_id}")

            logger.info(f"Starting batch processing (queue_size={queue_size})")

            items = await redis_queue.dequeue(count=settings.batch_size)

            if not items:
                continue

            url_data_list = []
            for item in items:
                try:
                    msg = URLQueueMessage(**item)
                    url_data = URLData(
                        short_code=msg.short_code,
                        original_url=msg.original_url,
                        created_at=datetime.fromisoformat(msg.created_at)
                    )
                    url_data_list.append(url_data)
                except Exception as e:
                    logger.error(f"Failed to parse queue message: {e}")
                    continue

            if url_data_list:
                inserted_count = await url_repo.batch_create(url_data_list)
                remaining_size = await redis_queue.size()
                logger.info(
                    f"Batch completed: {inserted_count} URLs inserted (remaining={remaining_size})"
                )

            # Clear batch context
            request_context.clear_request_id()

        except asyncio.CancelledError:
            logger.info("Background scheduler cancelled")
            break
        except Exception as e:
            logger.error(f"Background batch processing error: {e}")
            request_context.clear_request_id()


@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup."""
    global background_task, url_repo, redis_queue

    logger.info("Batch Processor Service starting up")

    # Initialize repository with connection pooling
    url_repo = await get_url_repository()
    await url_repo.initialize()

    # Initialize queue if enabled
    if settings.queue_enabled:
        redis_queue = get_redis_queue(settings.redis_url)
        await redis_queue.connect()

    logger.info(f"Batch processor ready (batch_size={settings.batch_size})")

    if settings.enable_background_scheduler:
        logger.info("Starting background scheduler (dev mode)")
        background_task = asyncio.create_task(background_batch_processor())
    else:
        logger.info("Background scheduler disabled (using Vercel Cron)")


@app.on_event("shutdown")
async def shutdown_event():
    """Close connections on shutdown."""
    global background_task

    logger.info("Batch Processor Service shutting down")

    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass

    await url_repo.close()

    if redis_queue:
        await redis_queue.close()


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "batch_processor"}


@app.post("/api/cron/process-batch")
async def process_batch():
    """
    Process a batch of URLs from the queue and insert into database.

    This endpoint is called by Vercel Cron every N seconds.

    Returns:
        JSON with processing statistics
    """
    if not redis_queue:
        raise HTTPException(status_code=503, detail="Queue not enabled")

    # Generate unique batch ID (first 12 chars of UUID for tracking)
    batch_id = str(uuid.uuid4())[:12]
    request_context.set_request_id(f"batch-{batch_id}")

    start_time = datetime.now()

    try:
        queue_size = await redis_queue.size()
        logger.info(f"Processing batch (queue_size={queue_size})")

        if queue_size == 0:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "Queue is empty",
                    "batch_id": batch_id,
                    "processed": 0,
                    "queue_size": 0,
                    "duration_ms": 0
                }
            )

        items = await redis_queue.dequeue(count=settings.batch_size)

        if not items:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "success",
                    "message": "No items to process",
                    "batch_id": batch_id,
                    "processed": 0,
                    "queue_size": queue_size,
                    "duration_ms": 0
                }
            )

        url_data_list = []
        for item in items:
            try:
                msg = URLQueueMessage(**item)
                url_data = URLData(
                    short_code=msg.short_code,
                    original_url=msg.original_url,
                    created_at=datetime.fromisoformat(msg.created_at)
                )
                url_data_list.append(url_data)
            except Exception as e:
                logger.error(f"Failed to parse queue message: {e}")
                continue

        if not url_data_list:
            return JSONResponse(
                status_code=200,
                content={
                    "status": "error",
                    "message": "All items failed to parse",
                    "batch_id": batch_id,
                    "processed": 0,
                    "queue_size": queue_size,
                    "duration_ms": 0
                }
            )

        inserted_count = await url_repo.batch_create(url_data_list)

        end_time = datetime.now()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        remaining_queue_size = await redis_queue.size()

        logger.info(
            f"Batch processed: {inserted_count} URLs inserted "
            f"(duration={duration_ms}ms, remaining={remaining_queue_size})"
        )

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": f"Batch processed successfully",
                "batch_id": batch_id,
                "processed": inserted_count,
                "queue_size_before": queue_size,
                "queue_size_after": remaining_queue_size,
                "duration_ms": duration_ms
            }
        )

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Batch processing failed: {str(e)}")
    finally:
        # Clear batch context
        request_context.clear_request_id()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower()
    )
