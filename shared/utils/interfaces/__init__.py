"""
Abstract interfaces for utility classes.

This module provides abstract base classes for:
- ID generation (Snowflake, etc.)
- Caching (LRU, Redis, etc.)
- Queuing (Redis, etc.)
"""
from .id_generator import IDGenerator
from .cache import Cache
from .queue import Queue

__all__ = [
    'IDGenerator',
    'Cache',
    'Queue'
]
