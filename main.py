"""
FastAPI application entry point for URL shortener service.

Main entry point providing:
- POST /v1/shorten - Shorten a URL
- GET /{short_code} - Redirect to original URL
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import logging

from app.api.routes import router
from app.config.settings import settings
from app.utils.logger import AppLogger, get_logger
from app.utils.request_context import generate_request_id, set_request_id

# Setup application logger
# Configure log level via LOG_LEVEL environment variable
# Options: DEBUG, INFO, WARNING, ERROR, CRITICAL
log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
AppLogger.setup(
    level=log_level,
    enable_console=True
)
logger = get_logger()


# Initialize FastAPI application
app = FastAPI(
    title="URL Shortener API",
    description="High-performance URL shortening service with distributed ID generation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configure CORS - Allow frontend to make requests
# Parse CORS origins from settings (comma-separated string to list)
cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]

logger.debug(f"Configuring CORS middleware with origins: {cors_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,       # Configurable via CORS_ORIGINS environment variable
    allow_credentials=True,
    allow_methods=["*"],              # Allow all HTTP methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],              # Allow all headers
)

logger.info(f"CORS middleware configured with {len(cors_origins)} allowed origins")


# Request ID Middleware - Generates unique ID for each request
@app.middleware("http")
async def add_request_id_middleware(request, call_next):
    """
    Middleware to generate and set a unique request ID for each incoming request.

    This runs BEFORE the request handler:
    1. Generates a unique UUID
    2. Stores it in ContextVar (accessible everywhere)
    3. Adds it to response headers (useful for debugging)

    After this middleware runs, any code can call get_request_id() to retrieve it.
    Works for both HTTP and HTTPS requests.
    """
    # Generate unique request ID
    request_id = generate_request_id()

    # Store in context so all layers can access it
    set_request_id(request_id)

    # Log the incoming request with ID
    logger.debug(f"[{request_id}] Incoming request: {request.method} {request.url.path}")

    # Process the request (your controllers run here)
    response = await call_next(request)

    # Add request ID to response headers (useful for client-side debugging)
    response.headers["X-Request-ID"] = request_id

    return response


logger.info("Request ID middleware configured")

# Include API routes
app.include_router(router)


if __name__ == "__main__":
    """
    Run the application directly for development.

    For production, use: uvicorn main:app --host 0.0.0.0 --port 8000 --no-reload
    """
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        log_level="info"
    )
