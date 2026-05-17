"""
Click Processor Service - Processes queued click analytics and inserts them into database.
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

from services.click_processor.config import get_settings
from shared.utils.logging_config import setup_logging
from shared.middleware.request_id import RequestIDMiddleware
from shared.middleware.metrics import PrometheusMiddleware, metrics_endpoint
from shared.config.dependencies import get_click_repository, get_click_queue, get_click_dlq
from shared.data.interfaces.click_repository import ClickRepository
from shared.utils.health import check_database, check_redis, check_queue, check_all_dependencies
from services.batch_processor.click_worker import background_click_batch_processor

settings = get_settings()

# Setup per-service logging
setup_logging(
    service_name="click_processor",
    log_level=settings.log_level,
    enable_console=True,
    enable_file=True
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Click Processor Service",
    version="1.0.0",
    description="Processes queued click analytics in batches",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add Request ID middleware for HTTP endpoints
app.add_middleware(RequestIDMiddleware)

# Add Prometheus metrics middleware
app.add_middleware(PrometheusMiddleware, service_name="click_processor")


# Health check endpoints
@app.get("/health")
async def health_check() -> dict:
    """
    Basic health check for load balancer.
    Returns simple status without checking dependencies.
    """
    return {"status": "healthy", "service": "click_processor"}


@app.get("/health/full")
async def full_health_check() -> dict:
    """
    Comprehensive health check including all dependencies.
    Checks database and Redis queue connectivity.
    """
    try:
        repository = await get_click_repository()
    except Exception as e:
        repository = None
        logger.error("Failed to get click repository for health check", extra={"error": str(e)})

    try:
        queue = await get_click_queue()
    except Exception as e:
        queue = None
        logger.error("Failed to get click queue for health check", extra={"error": str(e)})

    result = await check_all_dependencies(
        service_name="click_processor",
        repository=repository,
        cache=None,  # Click processor doesn't use cache
        queue=queue
    )
    return result


@app.get("/health/db")
async def database_health_check() -> dict:
    """Check database connectivity and performance."""
    try:
        repository = await get_click_repository()
        result = await check_database(repository)
    except Exception as e:
        logger.error("Failed to get repository for health check", extra={"error": str(e)})
        from shared.utils.health import DependencyHealth
        result = DependencyHealth(
            status="unhealthy",
            message="Failed to initialize database connection",
            error=str(e)
        )
    return result


@app.get("/health/queue")
async def queue_health_check() -> dict:
    """Check Redis queue connectivity and performance."""
    try:
        queue = await get_click_queue()
        result = await check_queue(queue)
    except Exception as e:
        logger.error("Failed to get queue for health check", extra={"error": str(e)})
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


# Global instances (initialized in startup event)
click_repo: ClickRepository = None
click_queue = None
click_dlq = None

# Background task control
background_task = None


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize connections on startup."""
    global background_task, click_repo, click_queue, click_dlq

    logger.info("Click Processor Service starting up")

    # Get click repository instance (singleton)
    click_repo = await get_click_repository()

    # Initialize click queue (singleton)
    click_queue = await get_click_queue()

    # Initialize click dead-letter queue (singleton)
    click_dlq = await get_click_dlq()

    logger.info("Click processor ready", extra={"batch_size": settings.batch_size, "interval_seconds": settings.click_batch_interval_seconds})

    if settings.enable_background_scheduler:
        logger.info("Starting click background scheduler (dev mode)")
        background_task = asyncio.create_task(
            background_click_batch_processor(
                click_repo,
                click_queue,
                click_dlq,
                interval_seconds=settings.click_batch_interval_seconds
            )
        )
    else:
        logger.info("Background scheduler disabled (production: use cron or scheduler)")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Close connections on shutdown to prevent resource leaks."""
    global background_task

    logger.info("Click Processor Service shutting down")

    if background_task:
        background_task.cancel()
        try:
            await background_task
        except asyncio.CancelledError:
            pass

    if click_repo:
        await click_repo.close()
        logger.debug("Click repository closed")

    if click_queue:
        await click_queue.close()
        logger.debug("Click queue closed")

    if click_dlq:
        await click_dlq.close()
        logger.debug("Click DLQ closed")

    logger.info("Click Processor Service shutdown complete")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower()
    )
