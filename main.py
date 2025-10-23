"""
FastAPI application entry point for URL shortener service.

Main entry point providing:
- POST /v1/shorten - Shorten a URL
- GET /{short_code} - Redirect to original URL
"""
from fastapi import FastAPI
import uvicorn

from app.api.routes import router


# Initialize FastAPI application
app = FastAPI(
    title="URL Shortener API",
    description="High-performance URL shortening service with distributed ID generation",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Include API routes
app.include_router(router)


if __name__ == "__main__":
    """
    Run the application directly for development.

    For production, use: uvicorn main:app --host 0.0.0.0 --port 8000
    """
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        log_level="info"
    )
