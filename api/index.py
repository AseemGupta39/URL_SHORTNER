"""
Vercel serverless function entry point.

This file adapts the FastAPI app to work as a Vercel serverless function.
"""
from main import app

# Vercel will call this as a serverless function
handler = app
