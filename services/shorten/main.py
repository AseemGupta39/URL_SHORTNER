"""
Shorten Service - Creates short URLs with unique IDs.
Handles POST /v1/shorten endpoint with Snowflake ID generation.
"""
import sys
from pathlib import Path

# Load service-specific environment variables BEFORE importing shared modules
service_dir = Path(__file__).parent
env_file = service_dir / ".env"

from dotenv import load_dotenv
load_dotenv(env_file, override=True)

# Add project root to Python path for imports
project_root = service_dir.parent.parent
sys.path.insert(0, str(project_root))

import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from services.shorten.config import settings  # Service-specific settings
from shared.utils.logging_config import setup_logging
from shared.middleware.request_id import RequestIDMiddleware
from shared.middleware.canonical_log import CanonicalLogMiddleware
from shared.middleware.metrics import PrometheusMiddleware, metrics_endpoint
from shared.config.dependencies import get_url_repository, get_cache, get_url_queue
from shared.utils.health import check_database, check_redis, check_queue, check_all_dependencies, ServiceHealth
from services.shorten.controllers import shorten_router

QUEUE_DEPTH_POLL_INTERVAL = 10  # seconds


async def _poll_queue_depth() -> None:
    """Background task: logs queue depth every QUEUE_DEPTH_POLL_INTERVAL seconds.

    Runs for the lifetime of the service. Errors are logged but never crash the poller —
    a transient Redis blip should not kill the monitoring loop.
    """
    while True:
        await asyncio.sleep(QUEUE_DEPTH_POLL_INTERVAL)
        try:
            queue = await get_url_queue()
            depth = await queue.size()
            logger.info("Queue depth", extra={"depth": depth})
        except Exception as e:
            logger.error("Queue depth poll failed", extra={"error": str(e)})

# Setup per-service logging
setup_logging(
    service_name="shorten",
    log_level=settings.log_level,
    enable_console=True,
    enable_file=True
)
logger = logging.getLogger(__name__)

# Initialize FastAPI application
app = FastAPI(
    title="URL Shortener - Shorten Service",
    description="Service for creating short URLs with unique IDs",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Add Request ID middleware (must be added before CORS)
app.add_middleware(CanonicalLogMiddleware, service_name="shorten")
app.add_middleware(RequestIDMiddleware)

# Add Prometheus metrics middleware
app.add_middleware(PrometheusMiddleware, service_name="shorten")

# Configure CORS
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check endpoints (kept in main.py - see ARCHITECTURE.md for reasoning)
@app.get("/health")
async def health_check() -> dict:
    """
    Basic health check for load balancer.
    Returns simple status without checking dependencies.
    """
    return {
        "service": "shorten",
        "status": "healthy",
        "datacenter_id": settings.datacenter_id,
        "worker_id": settings.worker_id
    }


@app.get("/health/full")
async def full_health_check() -> ServiceHealth:
    """
    Comprehensive health check including all dependencies.
    Checks database, Redis cache, and queue connectivity.
    """
    try:
        repository = await get_url_repository()
    except Exception as e:
        repository = None
        logger.error("Failed to get repository for health check", extra={"error": str(e)})

    try:
        cache = await get_cache()
    except Exception as e:
        cache = None
        logger.error("Failed to get cache for health check", extra={"error": str(e)})

    try:
        queue = await get_url_queue()
    except Exception as e:
        queue = None
        logger.error("Failed to get queue for health check", extra={"error": str(e)})

    result = await check_all_dependencies(
        service_name="shorten",
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
        logger.error("Failed to get repository for health check", extra={"error": str(e)})
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
        logger.error("Failed to get cache for health check", extra={"error": str(e)})
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

@app.on_event("startup")
async def startup_event() -> None:
    """Warm ID buffer and start background tasks on service startup."""
    from shared.config.dependencies import init_id_buffer
    await init_id_buffer(
        size=settings.id_buffer_size,
        refill_threshold=settings.id_buffer_refill_threshold,
    )
    asyncio.create_task(_poll_queue_depth())
    logger.info("Queue depth poller started", extra={"interval_seconds": QUEUE_DEPTH_POLL_INTERVAL})


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Close singleton resources on shutdown to prevent leaks."""
    logger.info("Shorten Service shutting down - closing connections", extra={"service": "shorten"})

    from shared.config.dependencies import _instances
    for key in ("url_repository", "cache", "url_queue"):
        instance = _instances.get(key)
        if instance and hasattr(instance, "close"):
            await instance.close()
            logger.debug("Connection closed", extra={"resource": key})

    logger.info("Shorten Service shutdown complete", extra={"service": "shorten"})

app.include_router(shorten_router)

logger.info("Shorten Service started", extra={"datacenter_id": settings.datacenter_id, "worker_id": settings.worker_id})

# For local debugging in VSCode (press F5)
# In production, Vercel imports 'app' directly and this block never runs
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower()
    )
