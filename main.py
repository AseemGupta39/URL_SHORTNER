"""
FastAPI application entry point for URL shortener service.

Main entry point providing:
- POST /v1/shorten - Shorten a URL
- GET /{short_code} - Redirect to original URL
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.api.routes import router
from app.config.settings import settings


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,       # Configurable via CORS_ORIGINS environment variable
    allow_credentials=True,
    allow_methods=["*"],              # Allow all HTTP methods (GET, POST, OPTIONS, etc.)
    allow_headers=["*"],              # Allow all headers
)

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
