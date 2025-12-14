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

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from shared.config.settings import settings
from shared.utils.logger import AppLogger, get_logger
from shared.middleware.request_id import RequestIDMiddleware
from shared.config.dependencies import get_url_repository, get_cache
from shared.utils.health import check_database, check_redis, check_all_dependencies
from services.shorten.controllers import url_router

# Setup application logger
log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
AppLogger.setup(level=log_level, enable_console=True)
logger = get_logger()

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
async def full_health_check(
    repository=Depends(get_url_repository),
    cache=Depends(get_cache)
):
    """
    Comprehensive health check including all dependencies.
    Checks database and Redis connectivity.
    """
    result = await check_all_dependencies(
        service_name="shorten",
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
