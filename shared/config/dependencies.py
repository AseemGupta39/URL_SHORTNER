"""
Dependency injection factories for FastAPI.
"""
from fastapi import Depends
import logging
import asyncio

from shared.config.settings import settings
from shared.utils.interfaces.id_generator import IDGenerator
from shared.utils.snowflake_id_generator import SnowflakeIDGenerator
from shared.data.repositories import URLRepository, SQLiteURLRepository
from shared.data.interfaces.click_repository import ClickRepository
from shared.data.repositories.click_repository import SQLiteClickRepository
from shared.core.services import URLService
from shared.core.services.click_analytics_service import ClickAnalyticsService
from shared.utils.interfaces.cache import Cache
from shared.utils.lru_cache import LRUCache
from shared.utils.redis_cache import RedisCache
from shared.utils.interfaces.queue import Queue
from shared.utils.redis_queue import RedisQueue

logger = logging.getLogger(__name__)


# Global ID generator instance (singleton)
_id_generator_instance: IDGenerator | None = None
_id_generator_lock = asyncio.Lock()


async def get_id_generator() -> IDGenerator:
    """
    Get the global ID generator instance (singleton).

    IMPORTANT: Must be singleton to maintain sequence state across requests.
    Creating a new instance per request would reset sequence to 0,
    causing duplicate IDs for concurrent requests in the same second.

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance (avoids lock on every call)

    Returns:
        SnowflakeIDGenerator configured from settings
    """
    global _id_generator_instance

    # Fast path: instance already exists (no lock needed)
    if _id_generator_instance is None:
        # Slow path: acquire lock for initialization
        async with _id_generator_lock:
            # Double-check: another coroutine may have initialized while we waited
            if _id_generator_instance is None:
                logger.info("Initializing SnowflakeIDGenerator (singleton)")
                _id_generator_instance = SnowflakeIDGenerator(
                    datacenter_id=settings.datacenter_id,
                    worker_id=settings.worker_id,
                    epoch_sec=settings.epoch_sec,
                    timestamp_bits=settings.timestamp_bits,
                    datacenter_bits=settings.datacenter_bits,
                    worker_bits=settings.worker_bits,
                    sequence_bits=settings.sequence_bits
                )

    return _id_generator_instance


# Global cache instance (singleton)
_cache_instance: Cache | None = None
_cache_lock = asyncio.Lock()


async def get_cache() -> Cache:
    """
    Get the global cache instance (singleton with connection pooling).

    Redis Connection Pooling:
    - Like PgBouncer for PostgreSQL, redis-py provides built-in connection pooling
    - Connections are reused across requests for better performance
    - Pool size configured via settings.redis_pool_max_connections

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance

    Returns:
        RedisCache if Redis is enabled, otherwise LRUCache
    """
    global _cache_instance

    # Fast path: instance already exists
    if _cache_instance is None:
        # Slow path: acquire lock for initialization
        async with _cache_lock:
            # Double-check: another coroutine may have initialized while we waited
            if _cache_instance is None:
                if settings.redis_enabled and settings.redis_url:
                    logger.info("Initializing RedisCache with connection pooling")
                    _cache_instance = RedisCache(
                        redis_url=settings.redis_url,
                        ttl_seconds=settings.cache_ttl_seconds,
                        max_connections=settings.redis_pool_max_connections,
                        socket_timeout=settings.redis_cache_socket_timeout,
                        socket_connect_timeout=settings.redis_cache_connect_timeout
                    )
                    await _cache_instance.connect()
                else:
                    logger.info("Initializing LRUCache")
                    _cache_instance = LRUCache(
                        max_size=settings.cache_max_size,
                        ttl_seconds=settings.cache_ttl_seconds
                    )

    return _cache_instance


# Global URL queue instance (singleton)
_url_queue_instance: Queue | None = None
_url_queue_lock = asyncio.Lock()


async def get_url_queue() -> Queue:
    """
    Get the global URL queue instance (singleton with connection pooling).

    Used for batching URL shortening operations.

    Redis Connection Pooling:
    - Like PgBouncer for PostgreSQL, redis-py provides built-in connection pooling
    - Connections are reused across requests for better performance
    - Pool size configured via settings.redis_pool_max_connections

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance

    Returns:
        RedisQueue for URL batch processing (queue_name="url_batch_queue")
    """
    global _url_queue_instance

    # Fast path: instance already exists
    if _url_queue_instance is None:
        # Slow path: acquire lock for initialization
        async with _url_queue_lock:
            # Double-check: another coroutine may have initialized while we waited
            if _url_queue_instance is None:
                if not settings.redis_url:
                    raise RuntimeError(
                        "Redis queue is required for async batch processing architecture. "
                        "Please set REDIS_URL in your .env file. "
                        "Example: REDIS_URL=redis://localhost:6379"
                    )

                logger.info("Initializing URL Queue (url_batch_queue)")
                _url_queue_instance = RedisQueue(
                    redis_url=settings.redis_url,
                    queue_name="url_batch_queue",
                    max_connections=settings.redis_pool_max_connections,
                    socket_timeout=settings.redis_queue_socket_timeout,
                    socket_connect_timeout=settings.redis_queue_connect_timeout
                )
                await _url_queue_instance.connect()

    return _url_queue_instance


# Global Click queue instance (singleton)
_click_queue_instance: Queue | None = None
_click_queue_lock = asyncio.Lock()


async def get_click_queue() -> Queue:
    """
    Get the global Click queue instance (singleton with connection pooling).

    Used for batching click analytics operations.

    Redis Connection Pooling:
    - Like PgBouncer for PostgreSQL, redis-py provides built-in connection pooling
    - Connections are reused across requests for better performance
    - Pool size configured via settings.redis_pool_max_connections

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance

    Returns:
        RedisQueue for click batch processing (queue_name="click_batch_queue")
    """
    global _click_queue_instance

    # Fast path: instance already exists
    if _click_queue_instance is None:
        # Slow path: acquire lock for initialization
        async with _click_queue_lock:
            # Double-check: another coroutine may have initialized while we waited
            if _click_queue_instance is None:
                if not settings.redis_url:
                    raise RuntimeError(
                        "Redis queue is required for click analytics architecture. "
                        "Please set REDIS_URL in your .env file. "
                        "Example: REDIS_URL=redis://localhost:6379"
                    )

                logger.info("Initializing Click Queue (click_batch_queue)")
                _click_queue_instance = RedisQueue(
                    redis_url=settings.redis_url,
                    queue_name="click_batch_queue",
                    max_connections=settings.redis_pool_max_connections,
                    socket_timeout=settings.redis_queue_socket_timeout,
                    socket_connect_timeout=settings.redis_queue_connect_timeout
                )
                await _click_queue_instance.connect()

    return _click_queue_instance


# Global URL repository instance (singleton)
_url_repository_instance: URLRepository | None = None
_url_repository_lock = asyncio.Lock()


async def get_url_repository() -> URLRepository:
    """
    Get the global URL repository instance (singleton).

    IMPORTANT: Must be singleton to reuse database connection pool.
    Creating a new instance per request would create a new engine with
    its own connection pool, wasting database connections.

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance

    Returns:
        SQLiteURLRepository configured from settings with connection pooling.
        - SQLite (development): No pooling
        - PostgreSQL (production): Full connection pooling for PgBouncer
    """
    global _url_repository_instance

    if _url_repository_instance is None:
        async with _url_repository_lock:
            if _url_repository_instance is None:
                logger.info("Initializing URLRepository (singleton)")
                _url_repository_instance = SQLiteURLRepository(
                    db_url=settings.database_url,
                    pool_size=settings.db_pool_size,
                    max_overflow=settings.db_pool_max_overflow,
                    pool_timeout=settings.db_pool_timeout,
                    pool_recycle=settings.db_pool_recycle,
                    pool_pre_ping=settings.db_pool_pre_ping,
                    echo_pool=settings.db_echo_pool
                )
                await _url_repository_instance.initialize()

    return _url_repository_instance


# Global URL service instance (singleton)
_url_service_instance: URLService | None = None
_url_service_lock = asyncio.Lock()


async def get_url_service(
    url_repo: URLRepository = Depends(get_url_repository),
    id_generator: IDGenerator = Depends(get_id_generator),
    cache: Cache = Depends(get_cache),
    queue: Queue = Depends(get_url_queue)
) -> URLService:
    """
    Get the global URL service instance (singleton).

    IMPORTANT: Must be singleton for consistency and to avoid
    creating unnecessary service objects per request.

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance

    Returns:
        URLService with cache-first and queue-based batch processing
    """
    global _url_service_instance

    if _url_service_instance is None:
        async with _url_service_lock:
            if _url_service_instance is None:
                logger.info("Initializing URLService (singleton)")
                _url_service_instance = URLService(
                    url_repo=url_repo,
                    id_generator=id_generator,
                    cache=cache,
                    queue=queue,
                    base_domain=settings.base_domain,
                    base_url_scheme=settings.base_url_scheme
                )

    return _url_service_instance


# Global Click repository instance (singleton)
_click_repository_instance: ClickRepository | None = None
_click_repository_lock = asyncio.Lock()


async def get_click_repository() -> ClickRepository:
    """
    Get the global Click repository instance (singleton).

    IMPORTANT: Must be singleton to reuse database connection pool.

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance

    Returns:
        SQLiteClickRepository configured from settings with connection pooling.
    """
    global _click_repository_instance

    if _click_repository_instance is None:
        async with _click_repository_lock:
            if _click_repository_instance is None:
                logger.info("Initializing ClickRepository (singleton)")
                _click_repository_instance = SQLiteClickRepository(
                    db_url=settings.database_url,
                    pool_size=settings.db_pool_size,
                    max_overflow=settings.db_pool_max_overflow,
                    pool_timeout=settings.db_pool_timeout,
                    pool_recycle=settings.db_pool_recycle,
                    pool_pre_ping=settings.db_pool_pre_ping,
                    echo_pool=settings.db_echo_pool
                )
                await _click_repository_instance.initialize()

    return _click_repository_instance


# Global Click Analytics service instance (singleton)
_click_analytics_service_instance: ClickAnalyticsService | None = None
_click_analytics_service_lock = asyncio.Lock()


async def get_click_analytics_service(
    click_repo: ClickRepository = Depends(get_click_repository),
    queue: Queue = Depends(get_click_queue)
) -> ClickAnalyticsService:
    """
    Get the global Click Analytics service instance (singleton).

    Thread Safety:
    - Uses asyncio.Lock() to prevent race conditions during initialization
    - Double-checked locking pattern for performance

    Returns:
        ClickAnalyticsService with queue-based batch processing
    """
    global _click_analytics_service_instance

    if _click_analytics_service_instance is None:
        async with _click_analytics_service_lock:
            if _click_analytics_service_instance is None:
                logger.info("Initializing ClickAnalyticsService (singleton)")
                _click_analytics_service_instance = ClickAnalyticsService(
                    click_repo=click_repo,
                    queue=queue
                )

    return _click_analytics_service_instance
