"""
Vercel serverless function entry point for URL shortener/redirect services.

This aggregates both shorten and redirect services into a single FastAPI app for Vercel deployment.
"""
import sys
from pathlib import Path

# Add parent directory to path so we can import services
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.shorten.main import app as shorten_app
from services.redirect.main import app as redirect_app

# Create main app with disabled docs (we'll use sub-app docs)
app = FastAPI(
    title="URL Shortener API Gateway",
    description="Unified API for URL shortening and redirect services",
    version="1.0.0",
    docs_url=None,
    redoc_url=None
)

# Configure CORS for main app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount services with proper paths
# Shorten service mounted at /api - exposes docs at /api/docs
app.mount("/api", shorten_app)

# Redirect service mounted at root - exposes docs at /docs
# This must be last as it catches all remaining routes including /{short_code}
app.mount("/", redirect_app)

# Export for Vercel
__all__ = ['app']
