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

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse as FastAPIRedirect
import logging

from shared.config.settings import settings
from shared.config.dependencies import get_url_service
from shared.core.services import URLService
from shared.core.exceptions import ShortCodeNotFoundException
from shared.utils.logger import AppLogger, get_logger

# Setup application logger
log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
AppLogger.setup(level=log_level, enable_console=True)
logger = get_logger()

# Initialize FastAPI application
app = FastAPI(
    title="URL Shortener - Redirect Service",
    description="Service for resolving short codes and redirecting to original URLs",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS (lightweight for redirects)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Redirects should work from anywhere
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check for load balancer."""
    return {
        "service": "redirect",
        "status": "healthy"
    }

# Redirect endpoint (only this service handles redirects)
@app.get("/{short_code}", tags=["Redirect"])
async def redirect_url(
    short_code: str,
    url_service: URLService = Depends(get_url_service)
):
    """
    Redirect to original URL using short code.

    Returns 302 redirect to original URL.
    Raises 404 if short code not found.
    """
    try:
        logger.info(f"Resolving short code: {short_code}")
        result = await url_service.resolve(short_code)
        return FastAPIRedirect(
            url=str(result.original_url),
            status_code=302
        )
    except ShortCodeNotFoundException:
        logger.warning(f"Short code not found: {short_code}")
        raise HTTPException(status_code=404, detail="Short code not found")

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
