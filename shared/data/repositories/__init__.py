"""
Data repositories for URL shortener.

This module provides repository implementations for data persistence.
"""
from shared.data.interfaces.url_repository import URLRepository
from .sqlite_url_repository import SQLiteURLRepository

__all__ = [
    'URLRepository',
    'SQLiteURLRepository'
]
