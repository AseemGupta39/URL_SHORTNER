"""
Vercel serverless function entry point for URL shortener/redirect services.

This aggregates both shorten and redirect services into a single FastAPI app for Vercel deployment.
"""
import sys
from pathlib import Path

# Add parent directory to path so we can import services
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import HttpUrl
from services.shorten.main import app as shorten_app
from services.redirect.main import app as redirect_app

# Create main app that mounts both services
app = FastAPI(title="URL Shortener API")

# Mount shorten service at /shorten
app.mount("/shorten", shorten_app)

# Mount redirect service at root for short URL resolution
app.mount("/", redirect_app)

# Export for Vercel
__all__ = ['app']
