"""
Dependency injection factories for FastAPI.
"""
from fastapi import Depends
import logging

from shared.config.settings import settings
from shared.utils.interfaces.id_generator import IDGenerator
from shared.utils.snowflake_id_generator import SnowflakeIDGenerator
from shared.data.repositories import URLRepository, SQLiteURLRepository
from shared.core.services import URLService
from shared.utils.interfaces.cache import Cache
from shared.utils.lru_cache import LRUCache
from shared.utils.redis_cache import RedisCache
from shared.utils.interfaces.queue import Queue
from shared.utils.redis_queue import RedisQueue

logger = logging.getLogger(__name__)


# Global ID generator instance (singleton)
_id_generator_instance: IDGenerator | None = None


async def get_id_generator() -> IDGenerator:
    """
    Get the global ID generator instance (singleton).

    IMPORTANT: Must be singleton to maintain sequence state across requests.
    Creating a new instance per request would reset sequence to 0,
    causing duplicate IDs for concurrent requests in the same second.

    Returns:
        SnowflakeIDGenerator configured from settings
    """
    global _id_generator_instance

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


async def get_cache() -> Cache:
    """
    Get the global cache instance (singleton with connection pooling).

    Redis Connection Pooling:
    - Like PgBouncer for PostgreSQL, redis-py provides built-in connection pooling
    - Connections are reused across requests for better performance
    - Pool size configured via settings.redis_pool_max_connections

    Returns:
        RedisCache if Redis is enabled, otherwise LRUCache
    """
    global _cache_instance

    if _cache_instance is None:
        if settings.redis_enabled and settings.redis_url:
            logger.info("Initializing RedisCache with connection pooling")
            _cache_instance = RedisCache(
                redis_url=settings.redis_url,
                ttl_seconds=settings.cache_ttl_seconds,
                max_connections=settings.redis_pool_max_connections,
                socket_timeout=settings.redis_socket_timeout,
                socket_connect_timeout=settings.redis_socket_connect_timeout
            )
            await _cache_instance.connect()
        else:
            logger.info("Initializing LRUCache")
            _cache_instance = LRUCache(
                max_size=settings.cache_max_size,
                ttl_seconds=settings.cache_ttl_seconds
            )

    return _cache_instance


# Global queue instance (singleton)
_queue_instance: Queue | None = None


async def get_queue() -> Queue:
    """
    Get the global queue instance (singleton with connection pooling).

    Redis Connection Pooling:
    - Like PgBouncer for PostgreSQL, redis-py provides built-in connection pooling
    - Connections are reused across requests for better performance
    - Pool size configured via settings.redis_pool_max_connections

    Returns:
        RedisQueue for batch processing
    """
    global _queue_instance

    if _queue_instance is None:
        if settings.queue_enabled and settings.redis_url:
            logger.info("Initializing RedisQueue with connection pooling")
            _queue_instance = RedisQueue(
                redis_url=settings.redis_url,
                max_connections=settings.redis_pool_max_connections,
                socket_timeout=settings.redis_socket_timeout,
                socket_connect_timeout=settings.redis_socket_connect_timeout
            )
            await _queue_instance.connect()
        else:
            raise RuntimeError("Queue is required but not enabled in settings")

    return _queue_instance


# Global URL repository instance (singleton)
_url_repository_instance: URLRepository | None = None


async def get_url_repository() -> URLRepository:
    """
    Get the global URL repository instance (singleton).

    IMPORTANT: Must be singleton to reuse database connection pool.
    Creating a new instance per request would create a new engine with
    its own connection pool, wasting database connections.

    Returns:
        SQLiteURLRepository configured from settings with connection pooling.
        - SQLite (development): No pooling
        - PostgreSQL (production): Full connection pooling for PgBouncer
    """
    global _url_repository_instance

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


async def get_url_service(
    url_repo: URLRepository = Depends(get_url_repository),
    id_generator: IDGenerator = Depends(get_id_generator),
    cache: Cache = Depends(get_cache),
    queue: Queue = Depends(get_queue)
) -> URLService:
    """
    Get the global URL service instance (singleton).

    IMPORTANT: Must be singleton for consistency and to avoid
    creating unnecessary service objects per request.

    Returns:
        URLService with cache-first and queue-based batch processing
    """
    global _url_service_instance

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
