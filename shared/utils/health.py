"""
Health check utilities for monitoring service dependencies.
Provides structured health check responses using Pydantic models.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime
from pydantic import BaseModel, Field
import logging

from shared.data.repositories.sqlite_url_repository import SQLiteURLRepository
from shared.utils.interfaces.cache import Cache
from shared.utils.redis_cache import RedisCache

logger = logging.getLogger(__name__)


class DependencyHealth(BaseModel):
    """Health status for a single dependency."""
    status: str = Field(..., description="healthy, unhealthy, or not_applicable")
    response_time_ms: Optional[float] = Field(None, description="Response time in milliseconds")
    message: str = Field(..., description="Human-readable status message")
    error: Optional[str] = Field(None, description="Error message if unhealthy")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional details")


class ServiceHealth(BaseModel):
    """Overall service health status."""
    service: str = Field(..., description="Service name (shorten, redirect, batch)")
    status: str = Field(..., description="Overall status: healthy or unhealthy")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    total_response_time_ms: Optional[float] = Field(None, description="Total check time")
    dependencies: Optional[Dict[str, DependencyHealth]] = Field(None, description="Dependency statuses")
    unhealthy_services: Optional[List[str]] = Field(None, description="List of unhealthy dependencies")


async def check_database(repository: SQLiteURLRepository) -> DependencyHealth:
    """
    Check database connectivity and performance.

    Args:
        repository: URL repository instance

    Returns:
        DependencyHealth with connection status and response time
    """
    start_time = datetime.now()

    try:
        # Simple query to verify database connectivity
        await repository.initialize()

        async with repository.async_session() as session:
            from sqlalchemy import select
            await session.execute(select(1))

        response_time_ms = (datetime.now() - start_time).total_seconds() * 1000

        # Detect database type from connection URL
        if repository.db_url.startswith("sqlite"):
            db_type = "SQLite"
        elif repository.db_url.startswith("postgresql"):
            db_type = "PostgreSQL"
        elif repository.db_url.startswith("mysql"):
            db_type = "MySQL"
        else:
            db_type = "Unknown"

        return DependencyHealth(
            status="healthy",
            response_time_ms=round(response_time_ms, 2),
            message=f"{db_type} connection successful",
            details={"database_type": db_type}
        )

    except Exception as e:
        response_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"Database health check failed: {e}")

        return DependencyHealth(
            status="unhealthy",
            response_time_ms=round(response_time_ms, 2),
            message="Database connection failed",
            error=str(e)
        )


async def check_redis(cache: Cache) -> DependencyHealth:
    """
    Check Redis connectivity and performance.

    Args:
        cache: Cache instance (RedisCache or LRUCache)

    Returns:
        DependencyHealth with connection status and response time
    """
    start_time = datetime.now()

    # If not using Redis, return N/A status
    if not isinstance(cache, RedisCache):
        return DependencyHealth(
            status="not_applicable",
            message="Redis not enabled (using LRU cache)",
            details={"cache_type": "lru"}
        )

    try:
        # Test Redis connection with PING command
        if cache._client:
            await cache._client.ping()

            response_time_ms = (datetime.now() - start_time).total_seconds() * 1000

            # Get cache stats
            stats = cache.get_stats()

            return DependencyHealth(
                status="healthy",
                response_time_ms=round(response_time_ms, 2),
                message="Redis connection successful",
                details={
                    "cache_type": "redis",
                    "hits": stats.get("hits"),
                    "misses": stats.get("misses"),
                    "hit_rate": stats.get("hit_rate")
                }
            )
        else:
            return DependencyHealth(
                status="unhealthy",
                message="Redis client not initialized",
                error="Redis client not connected",
                details={"cache_type": "redis"}
            )

    except Exception as e:
        response_time_ms = (datetime.now() - start_time).total_seconds() * 1000
        logger.error(f"Redis health check failed: {e}")

        return DependencyHealth(
            status="unhealthy",
            response_time_ms=round(response_time_ms, 2),
            message="Redis connection failed",
            error=str(e),
            details={"cache_type": "redis"}
        )


async def check_all_dependencies(
    service_name: str,
    repository: Optional[SQLiteURLRepository] = None,
    cache: Optional[Cache] = None
) -> ServiceHealth:
    """
    Check health of all service dependencies.

    Args:
        service_name: Name of the service (shorten, redirect, batch)
        repository: URL repository instance (optional)
        cache: Cache instance (optional)

    Returns:
        ServiceHealth with comprehensive status for all dependencies
    """
    start_time = datetime.now()
    dependencies = {}

    # Check database if repository is provided
    if repository:
        dependencies["database"] = await check_database(repository)

    # Check Redis if cache is provided
    if cache:
        dependencies["redis"] = await check_redis(cache)

    # Calculate total response time
    total_time_ms = (datetime.now() - start_time).total_seconds() * 1000

    # Determine overall status
    unhealthy_services = [
        name for name, status in dependencies.items()
        if status.status == "unhealthy"
    ]

    overall_status = "unhealthy" if unhealthy_services else "healthy"

    return ServiceHealth(
        service=service_name,
        status=overall_status,
        timestamp=datetime.now().isoformat(),
        total_response_time_ms=round(total_time_ms, 2),
        dependencies=dependencies if dependencies else None,
        unhealthy_services=unhealthy_services if unhealthy_services else None
    )
