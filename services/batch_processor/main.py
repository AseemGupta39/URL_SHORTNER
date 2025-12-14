"""
Batch Processor Service - Processes queued URLs and inserts them into database.
Runs in Docker/AWS with background scheduler or cron.
"""
import sys
from pathlib import Path
import asyncio

service_dir = Path(__file__).parent
env_file = service_dir / ".env"

from dotenv import load_dotenv
load_dotenv(env_file, override=True)

project_root = service_dir.parent.parent
sys.path.insert(0, str(project_root))

from fastapi import FastAPI, Depends

from shared.config.settings import get_settings
from shared.config.dependencies import get_url_repository, get_cache
from shared.data.repositories import URLRepository
from shared.utils.redis_queue import get_redis_queue
from shared.utils.logger import get_logger
from shared.utils.health import check_database, check_redis, check_all_dependencies
from shared.middleware.request_id import RequestIDMiddleware
from services.batch_processor.controllers import batch_router, background_batch_processor, set_dependencies

logger = get_logger()
settings = get_settings()

app = FastAPI(
    title="Batch Processor Service",
    version="1.0.0",
    description="Processes queued URL insertions in batches",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add Request ID middleware for HTTP endpoints
app.add_middleware(RequestIDMiddleware)

# Health check endpoints (kept in main.py - see ARCHITECTURE.md for reasoning)
# IMPORTANT: Must be defined BEFORE including batch_router to ensure proper route precedence
@app.get("/health")
async def health_check():
    """
    Basic health check for load balancer.
    Returns simple status without checking dependencies.
    """
    return {"status": "healthy", "service": "batch_processor"}


@app.get("/health/full")
async def full_health_check(
    repository=Depends(get_url_repository),
    cache=Depends(get_cache)
):
    """
    Comprehensive health check including all dependencies.
    Checks database and Redis connectivity.
    """
    result = await check_all_dependencies(
        service_name="batch_processor",
        repository=repository,
        cache=cache
    )
    return result


@app.get("/health/db")
async def database_health_check(repository=Depends(get_url_repository)):
    """Check database connectivity and performance."""
    result = await check_database(repository)
    return result


@app.get("/health/redis")
async def redis_health_check(cache=Depends(get_cache)):
    """Check Redis connectivity and performance."""
    result = await check_redis(cache)
    return result

# Include API routers
app.include_router(batch_router)

# Global instances (initialized in startup event)
url_repo: URLRepository = None
redis_queue = None

# Background task control
background_task = None


@app.on_event("startup")
async def startup_event():
    """Initialize connections on startup."""
    global background_task, url_repo, redis_queue

    logger.info("Batch Processor Service starting up")

    # Get repository instance (will be initialized by singleton on first call)
    url_repo = await get_url_repository()

    # Initialize queue if enabled
    if settings.queue_enabled:
        redis_queue = get_redis_queue(settings.redis_url)
        await redis_queue.connect()

    # Pass dependencies to controller
    set_dependencies(url_repo, redis_queue)

    logger.info(f"Batch processor ready (batch_size={settings.batch_size})")

    if settings.enable_background_scheduler:
        logger.info("Starting background scheduler (dev mode)")
        background_task = asyncio.create_task(background_batch_processor())
    else:
        logger.info("Background scheduler disabled (production: use cron or scheduler)")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower()
    )
