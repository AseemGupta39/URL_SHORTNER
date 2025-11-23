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
from shared.config.dependencies import get_url_service
from shared.core.services import URLService
from shared.core.schemas import ShortenRequest, ShortenResponse
from shared.utils.logger import AppLogger, get_logger
from shared.middleware.request_id import RequestIDMiddleware

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

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check for load balancer."""
    return {
        "service": "shorten",
        "status": "healthy",
        "datacenter_id": settings.datacenter_id,
        "worker_id": settings.worker_id
    }

# Shorten endpoint (only this service handles shortening)
@app.post("/v1/shorten", response_model=ShortenResponse, tags=["Shorten"])
async def shorten_url(
    request: ShortenRequest,
    url_service: URLService = Depends(get_url_service)
):
    """
    Create a short URL from a long URL.

    This service uses Snowflake ID generation with unique DATACENTER_ID/WORKER_ID.
    """
    logger.info(f"Shortening URL: {request.original_url}")
    result = await url_service.shorten(request.original_url)
    return result

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
