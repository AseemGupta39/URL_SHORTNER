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

from fastapi import FastAPI
import logging

from services.batch_processor.config import get_settings  # Service-specific settings
from shared.utils.logging_config import setup_logging
from shared.middleware.request_id import RequestIDMiddleware
from shared.middleware.metrics import PrometheusMiddleware, metrics_endpoint
from shared.config.dependencies import get_url_repository, get_cache, get_url_queue, get_click_queue, get_url_dlq
from shared.data.repositories import URLRepository
from shared.utils.redis_queue import get_redis_queue
from shared.utils.health import check_database, check_redis, check_queue, check_all_dependencies
from services.batch_processor.controllers import batch_router, set_dependencies
from services.batch_processor.batch_worker import background_batch_processor

settings = get_settings()

# Setup per-service logging
setup_logging(
    service_name="batch_processor",
    log_level=settings.log_level,
    enable_console=True,
    enable_file=True
)
logger = logging.getLogger(__name__)

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

# Add Prometheus metrics middleware
app.add_middleware(PrometheusMiddleware, service_name="batch_processor")

# Health check endpoints (kept in main.py - see ARCHITECTURE.md for reasoning)
# IMPORTANT: Must be defined BEFORE including batch_router to ensure proper route precedence
@app.get("/health")
async def health_check() -> dict:
    """
    Basic health check for load balancer.
    Returns simple status without checking dependencies.
    """
    return {"status": "healthy", "service": "batch_processor"}


@app.get("/health/full")
async def full_health_check() -> dict:
    """
    Comprehensive health check including all dependencies.
    Checks database, Redis cache, and queues connectivity.
    """
    try:
        repository = await get_url_repository()
    except Exception as e:
        repository = None
        logger.error(f"Failed to get repository for health check: {e}")

    try:
        cache = await get_cache()
    except Exception as e:
        cache = None
        logger.error(f"Failed to get cache for health check: {e}")

    try:
        # Check URL queue (batch processor uses it)
        queue = await get_url_queue()
    except Exception as e:
        queue = None
        logger.error(f"Failed to get URL queue for health check: {e}")

    result = await check_all_dependencies(
        service_name="batch_processor",
        repository=repository,
        cache=cache,
        queue=queue
    )
    return result


@app.get("/health/db")
async def database_health_check() -> dict:
    """Check database connectivity and performance."""
    try:
        repository = await get_url_repository()
        result = await check_database(repository)
    except Exception as e:
        logger.error(f"Failed to get repository for health check: {e}")
        from shared.utils.health import DependencyHealth
        result = DependencyHealth(
            status="unhealthy",
            message="Failed to initialize database connection",
            error=str(e)
        )
    return result


@app.get("/health/redis")
async def redis_health_check() -> dict:
    """Check Redis connectivity and performance."""
    try:
        cache = await get_cache()
        result = await check_redis(cache)
    except Exception as e:
        logger.error(f"Failed to get cache for health check: {e}")
        from shared.utils.health import DependencyHealth
        result = DependencyHealth(
            status="unhealthy",
            message="Failed to initialize Redis connection",
            error=str(e)
        )
    return result


@app.get("/health/queue")
async def queue_health_check() -> dict:
    """Check Redis queue connectivity and performance."""
    try:
        queue = await get_url_queue()
        result = await check_queue(queue)
    except Exception as e:
        logger.error(f"Failed to get queue for health check: {e}")
        from shared.utils.health import DependencyHealth
        result = DependencyHealth(
            status="unhealthy",
            message="Failed to initialize queue connection",
            error=str(e)
        )
    return result


@app.get("/metrics", tags=["Metrics"])
async def metrics() -> str:
    """Expose Prometheus metrics."""
    return metrics_endpoint()

# Include API routers (AFTER defining /metrics)
app.include_router(batch_router)

# Global instances (initialized in startup event)
url_repo: URLRepository = None
redis_queue = None
redis_dlq = None

# Background task control
background_task = None


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize connections on startup."""
    global background_task, url_repo, redis_queue, redis_dlq

    logger.info("Batch Processor Service starting up")

    # Get repository instance (will be initialized by singleton on first call)
    url_repo = await get_url_repository()

    # Initialize queue (always required for batch processor)
    redis_queue = get_redis_queue(settings.redis_url)
    await redis_queue.connect()

    # Initialize dead-letter queue (always required for failed message handling)
    redis_dlq = await get_url_dlq()

    # Pass dependencies to controller
    set_dependencies(url_repo, redis_queue, redis_dlq)

    logger.info(f"Batch processor ready (batch_size={settings.batch_size})")

    if settings.enable_background_scheduler:
        logger.info("Starting background scheduler (dev mode)")
        background_task = asyncio.create_task(background_batch_processor(url_repo, redis_queue, redis_dlq))
    else:
        logger.info("Background scheduler disabled (production: use cron or scheduler)")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Close connections on shutdown to prevent resource leaks."""
    global background_task

    logger.info("Batch Processor Service shutting down")

    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass

    await url_repo.close()
    logger.debug("URL repository closed")

    if redis_queue:
        await redis_queue.close()
        logger.debug("Redis queue closed")

    if redis_dlq:
        await redis_dlq.close()
        logger.debug("Redis DLQ closed")

    logger.info("Batch Processor Service shutdown complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower()
    )
