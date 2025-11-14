"""
Vercel serverless function wrapper for Batch Processor Service.
Exposes the batch processor at /api/batch/* and /api/cron/*
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from services.batch_processor.main import app as batch_service

# Create wrapper app
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

# Mount batch service at /api/batch for health and status
app.mount("/api/batch", batch_service)

# Also mount at /api/cron for cron job endpoint
app.mount("/api/cron", batch_service)

# Export for Vercel
__all__ = ['app']
