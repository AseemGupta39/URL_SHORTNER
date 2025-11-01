"""
Vercel serverless function entry point.

This file adapts the FastAPI app to work as a Vercel serverless function.
Vercel's Python runtime expects the app to be directly imported or exposed.
"""
from main import app

# Export app directly for Vercel (not as 'handler')
# Vercel looks for 'app' variable in this module
__all__ = ['app']
