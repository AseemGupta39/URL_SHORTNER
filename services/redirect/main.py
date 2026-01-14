"""
Redirect Service - Resolves short codes to original URLs.
Handles GET /{short_code} endpoint with 302 redirects.
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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from services.redirect.config import settings  # Service-specific settings
from shared.utils.logging_config import setup_logging
from shared.middleware.request_id import RequestIDMiddleware
from shared.middleware.metrics import PrometheusMiddleware, metrics_endpoint
from shared.config.dependencies import get_url_repository, get_cache, get_click_queue
from shared.utils.health import check_database, check_redis, check_queue, check_all_dependencies
from services.redirect.controllers import redirect_router

# Setup per-service logging
setup_logging(
    service_name="redirect",
    log_level=settings.log_level,
    enable_console=True,
    enable_file=True
)
logger = logging.getLogger(__name__)

# Initialize FastAPI application
app = FastAPI(
    title="URL Shortener - Redirect Service",
    description="Service for resolving short codes and redirecting to original URLs",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add Request ID middleware (must be added before CORS)
app.add_middleware(RequestIDMiddleware)

# Add Prometheus metrics middleware
app.add_middleware(PrometheusMiddleware, service_name="redirect")

# Configure CORS (lightweight for redirects)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Redirects should work from anywhere
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Health check endpoints (kept in main.py - see ARCHITECTURE.md for reasoning)
# IMPORTANT: Must be defined BEFORE including redirect_router (which has catch-all /{short_code})
@app.get("/health")
async def health_check() -> dict:
    """
    Basic health check for load balancer.
    Returns simple status without checking dependencies.
    """
    return {
        "service": "redirect",
        "status": "healthy"
    }


@app.get("/health/full")
async def full_health_check() -> dict:
    """
    Comprehensive health check including all dependencies.
    Checks database, Redis cache, and queue connectivity.
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
        # Check click queue (redirect service uses it for analytics)
        queue = await get_click_queue()
    except Exception as e:
        queue = None
        logger.error(f"Failed to get click queue for health check: {e}")

    result = await check_all_dependencies(
        service_name="redirect",
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
        queue = await get_click_queue()
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

# Include API routers (AFTER defining /metrics to prevent /{short_code} from catching it)
app.include_router(redirect_router)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    """Close singleton resources on shutdown to prevent leaks."""
    logger.info("Redirect Service shutting down - closing connections")

    # Close singletons via dependency injection getters
    from shared.config.dependencies import (
        _url_repo_instance,
        _cache_instance,
        _click_queue_instance
    )

    if _url_repo_instance:
        await _url_repo_instance.close()
        logger.debug("URL repository closed")

    if _cache_instance:
        await _cache_instance.close()
        logger.debug("Cache connection closed")

    if _click_queue_instance:
        await _click_queue_instance.close()
        logger.debug("Click queue connection closed")

    logger.info("Redirect Service shutdown complete")


logger.info("Redirect Service started")

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
