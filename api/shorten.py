"""
Vercel serverless function wrapper for Shorten Service.
Exposes the shorten service as an independent microservice at /api/shorten/*
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from services.shorten.main import app as shorten_service

# Create wrapper app that mounts the shorten service
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Mount the shorten service at /api/shorten
# This makes the service's /v1/shorten available at /api/shorten/v1/shorten
app.mount("/api/shorten", shorten_service)

# Export for Vercel
__all__ = ['app']
