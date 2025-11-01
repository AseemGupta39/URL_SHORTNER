"""
Dependency injection factories for FastAPI.
"""
from fastapi import Depends

from app.config.settings import settings
from app.utils.id_generator import IDGenerator, SnowflakeIDGenerator
from app.data.repositories import URLRepository, SQLiteURLRepository
from app.core.services import URLService
from app.utils.cache import Cache, LRUCache


async def get_id_generator() -> IDGenerator:
    """
    Dependency injection factory for ID generator.

    Returns:
        SnowflakeIDGenerator configured from settings
    """
    return SnowflakeIDGenerator(
        datacenter_id=settings.datacenter_id,
        worker_id=settings.worker_id,
        epoch_sec=settings.epoch_sec,
        timestamp_bits=settings.timestamp_bits,
        datacenter_bits=settings.datacenter_bits,
        worker_bits=settings.worker_bits,
        sequence_bits=settings.sequence_bits
    )


# Global cache instance (singleton)
# Created once and reused across all requests for better performance
# Initialized lazily when first accessed
_cache_instance: Cache | None = None


def get_cache() -> Cache | None:
    """
    Get the global cache instance.

    Returns:
        LRUCache instance if caching is enabled, None otherwise
    """
    global _cache_instance

    # Return None if caching is disabled
    if not settings.cache_enabled:
        return None

    # Create cache instance if not already created (lazy initialization)
    if _cache_instance is None:
        _cache_instance = LRUCache(
            max_size=settings.cache_max_size,
            ttl_seconds=settings.cache_ttl_seconds
        )

    return _cache_instance


async def get_url_repository() -> URLRepository:
    """
    Dependency injection factory for URL repository with optional cache support.

    Returns:
        SQLiteURLRepository configured from settings with caching (if enabled).
        Supports both SQLite (development) and PostgreSQL (production).
        Cache significantly reduces database load for read-heavy workloads.
    """
    cache = get_cache()  # Get cache instance (or None if disabled)
    repo = SQLiteURLRepository(db_url=settings.database_url, cache=cache)
    await repo.initialize()
    return repo


async def get_url_service(
    url_repo: URLRepository = Depends(get_url_repository),
    id_generator: IDGenerator = Depends(get_id_generator)
) -> URLService:
    """
    Dependency injection factory for URL service.

    Returns:
        URLService with injected dependencies
    """
    return URLService(
        url_repo=url_repo,
        id_generator=id_generator,
        base_domain=settings.base_domain,
        base_url_scheme=settings.base_url_scheme
    )
