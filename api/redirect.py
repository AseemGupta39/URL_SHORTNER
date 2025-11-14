"""
Vercel serverless function wrapper for Redirect Service.
Exposes the redirect service as an independent microservice at /api/redirect/*
Also handles short code redirects at /{short_code}
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from services.redirect.main import app as redirect_service

# Create wrapper app
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Mount redirect service at /api/redirect for docs and health
app.mount("/api/redirect", redirect_service)

# Also mount at root for short code redirects /{short_code}
# This must be after /api/redirect to avoid conflicts
app.mount("/", redirect_service)

# Export for Vercel
__all__ = ['app']
