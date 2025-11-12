"""
Vercel serverless function entry point for batch processor service.

This wraps the batch processor service for Vercel Cron jobs.
"""
import sys
from pathlib import Path

# Add parent directory to path so we can import services
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.batch_processor.main import app

# Export for Vercel
__all__ = ['app']
