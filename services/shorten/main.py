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

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from services.shorten.config import settings  # Service-specific settings
from shared.utils.logging_config import setup_logging
from shared.middleware.request_id import RequestIDMiddleware
from shared.middleware.metrics import PrometheusMiddleware, metrics_endpoint
from shared.config.dependencies import get_url_repository, get_cache
from shared.utils.health import check_database, check_redis, check_all_dependencies
from services.shorten.controllers import url_router

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
# IMPORTANT: Must be defined BEFORE including url_router to ensure proper route precedence
@app.get("/health")
async def health_check():
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
async def full_health_check():
    """
    Comprehensive health check including all dependencies.
    Checks database and Redis connectivity.
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

    result = await check_all_dependencies(
        service_name="shorten",
        repository=repository,
        cache=cache
    )
    return result


@app.get("/health/db")
async def database_health_check():
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
async def redis_health_check():
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


@app.get("/metrics", tags=["Metrics"])
async def metrics():
    """Expose Prometheus metrics."""
    return metrics_endpoint()

# Include API routers (AFTER defining /metrics to prevent route conflicts)
app.include_router(url_router)

logger.info(f"Shorten Service started (DC={settings.datacenter_id}, W={settings.worker_id})")

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
