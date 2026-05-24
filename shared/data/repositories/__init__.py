"""
Data repositories for URL shortener.

This module provides repository implementations for data persistence.
"""
from shared.data.interfaces.url_repository import URLRepository
from .postgres_url_repository import PostgresURLRepository

__all__ = [
    'URLRepository',
    'PostgresURLRepository',
]
