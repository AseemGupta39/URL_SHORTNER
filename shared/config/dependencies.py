"""
Dependency injection factories for FastAPI.

All singletons use the same double-checked locking pattern, managed by
_get_singleton(). Adding a new singleton = one _instances entry + one getter.
"""
from fastapi import Depends
import logging
import asyncio
from typing import TypeVar, Callable, Awaitable

from shared.config.settings import settings
from shared.utils.interfaces.id_generator import IDGenerator
from shared.utils.snowflake_id_generator import SnowflakeIDGenerator
from shared.utils.id_buffer import IDBuffer
from shared.data.repositories import URLRepository, SQLiteURLRepository
from shared.data.interfaces.click_repository import ClickRepository
from shared.data.repositories.click_repository import SQLiteClickRepository
from shared.core.services import ShortenService, ResolveService
from shared.core.services.click_analytics_service import ClickAnalyticsService
from shared.utils.interfaces.cache import Cache
from shared.utils.redis_cache import RedisCache
from shared.utils.interfaces.queue import Queue
from shared.utils.redis_queue import RedisQueue

logger = logging.getLogger(__name__)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Generic singleton registry
# ---------------------------------------------------------------------------

_KEYS = (
    "id_generator", "cache",
    "url_queue", "click_queue", "url_dlq", "click_dlq",
    "url_repository", "click_repository",
    "shorten_service", "resolve_service", "click_analytics_service",
)

_instances: dict[str, object] = {}
# Locks pre-created at module load — no lazy creation needed.
_locks: dict[str, asyncio.Lock] = {k: asyncio.Lock() for k in _KEYS}


async def _get_singleton(key: str, factory: Callable[[], Awaitable[T]]) -> T:
    """
    Generic double-checked locking singleton.
    factory() is called at most once per key, result cached in _instances.
    """
    if key not in _instances:
        async with _locks[key]:
            if key not in _instances:
                _instances[key] = await factory()
    return _instances[key]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Getters
# ---------------------------------------------------------------------------

async def get_id_generator() -> IDGenerator:
    async def factory() -> IDGenerator:
        logger.info("Initializing SnowflakeIDGenerator (singleton)")
        return SnowflakeIDGenerator(
            datacenter_id=settings.datacenter_id,
            worker_id=settings.worker_id,
            epoch_sec=settings.epoch_sec,
            timestamp_bits=settings.timestamp_bits,
            datacenter_bits=settings.datacenter_bits,
            worker_bits=settings.worker_bits,
            sequence_bits=settings.sequence_bits,
        )
    return await _get_singleton("id_generator", factory)


async def get_cache() -> Cache:
    async def factory() -> Cache:
        if not settings.redis_url:
            raise ValueError("REDIS_URL is required. Redis is fundamental to the architecture.")
        logger.info("Initializing RedisCache with connection pooling")
        instance = RedisCache(
            redis_url=settings.redis_url,
            ttl_seconds=settings.cache_ttl_seconds,
            max_connections=settings.redis_pool_max_connections,
            socket_timeout=settings.redis_cache_socket_timeout,
            socket_connect_timeout=settings.redis_cache_connect_timeout,
        )
        await instance.connect()
        return instance
    return await _get_singleton("cache", factory)


async def _make_queue(queue_name: str) -> Queue:
    if not settings.redis_url:
        raise RuntimeError(
            f"Redis queue is required ({queue_name}). "
            "Please set REDIS_URL in your .env file."
        )
    instance = RedisQueue(
        redis_url=settings.redis_url,
        queue_name=queue_name,
        max_connections=settings.redis_pool_max_connections,
        socket_timeout=settings.redis_queue_socket_timeout,
        socket_connect_timeout=settings.redis_queue_connect_timeout,
    )
    await instance.connect()
    return instance


async def get_url_queue() -> Queue:
    async def factory() -> Queue:
        logger.info("Initializing URL Queue (url_batch_queue)")
        return await _make_queue("url_batch_queue")
    return await _get_singleton("url_queue", factory)


async def get_click_queue() -> Queue:
    async def factory() -> Queue:
        logger.info("Initializing Click Queue (click_batch_queue)")
        return await _make_queue("click_batch_queue")
    return await _get_singleton("click_queue", factory)


async def get_url_dlq() -> Queue:
    async def factory() -> Queue:
        logger.info("Initializing URL Dead-Letter Queue (url_batch_queue_dlq)")
        return await _make_queue("url_batch_queue_dlq")
    return await _get_singleton("url_dlq", factory)


async def get_click_dlq() -> Queue:
    async def factory() -> Queue:
        logger.info("Initializing Click Dead-Letter Queue (click_batch_queue_dlq)")
        return await _make_queue("click_batch_queue_dlq")
    return await _get_singleton("click_dlq", factory)


async def get_url_repository() -> URLRepository:
    async def factory() -> URLRepository:
        logger.info("Initializing URLRepository (singleton)")
        instance = SQLiteURLRepository(
            db_url=settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=settings.db_pool_pre_ping,
            echo_pool=settings.db_echo_pool,
        )
        await instance.initialize()
        return instance
    return await _get_singleton("url_repository", factory)


async def get_click_repository() -> ClickRepository:
    async def factory() -> ClickRepository:
        logger.info("Initializing ClickRepository (singleton)")
        instance = SQLiteClickRepository(
            db_url=settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_recycle=settings.db_pool_recycle,
            pool_pre_ping=settings.db_pool_pre_ping,
            echo_pool=settings.db_echo_pool,
        )
        await instance.initialize()
        return instance
    return await _get_singleton("click_repository", factory)


async def get_shorten_service(
    url_repo: URLRepository = Depends(get_url_repository),
    cache: Cache = Depends(get_cache),
    queue: Queue = Depends(get_url_queue),
) -> ShortenService:
    async def factory() -> ShortenService:
        logger.info("Initializing ShortenService (singleton)")
        return ShortenService(
            url_repo=url_repo,
            cache=cache,
            queue=queue,
            id_buffer=_id_buffer_instance,
            base_domain=settings.base_domain,
            base_url_scheme=settings.base_url_scheme,
        )
    return await _get_singleton("shorten_service", factory)


async def get_resolve_service(
    url_repo: URLRepository = Depends(get_url_repository),
    cache: Cache = Depends(get_cache),
) -> ResolveService:
    async def factory() -> ResolveService:
        logger.info("Initializing ResolveService (singleton)")
        return ResolveService(
            url_repo=url_repo,
            cache=cache,
        )
    return await _get_singleton("resolve_service", factory)


async def get_click_analytics_service(
    click_repo: ClickRepository = Depends(get_click_repository),
    queue: Queue = Depends(get_click_queue),
) -> ClickAnalyticsService:
    async def factory() -> ClickAnalyticsService:
        logger.info("Initializing ClickAnalyticsService (singleton)")
        return ClickAnalyticsService(click_repo=click_repo, queue=queue)
    return await _get_singleton("click_analytics_service", factory)


# ---------------------------------------------------------------------------
# IDBuffer lifecycle — startup init and hot-path getter
# ---------------------------------------------------------------------------

_id_buffer_instance: IDBuffer | None = None


async def init_id_buffer(size: int = 2000, refill_threshold: int = 700) -> IDBuffer:
    """
    Create and start the global IDBuffer singleton.
    Must be called once in the service startup event before serving requests.

    Persist path is auto-derived from settings.datacenter_id and settings.worker_id
    to guarantee a unique file per worker process — prevents race condition when
    multiple workers share the same filesystem (e.g. 4 uvicorn workers on same machine).
    """
    global _id_buffer_instance

    if _id_buffer_instance is not None:
        logger.warning("init_id_buffer: buffer already initialized, skipping")
        return _id_buffer_instance

    persist_path = f"/tmp/id_buffer_dc{settings.datacenter_id}_w{settings.worker_id}.txt"
    generator = await get_id_generator()
    _id_buffer_instance = IDBuffer(
        generator=generator,
        size=size,
        refill_threshold=refill_threshold,
        persist_path=persist_path,
    )
    await _id_buffer_instance.start()
    return _id_buffer_instance


async def get_id_buffer() -> IDBuffer:
    """
    Get the global IDBuffer singleton for FastAPI dependency injection.
    Raises RuntimeError if called before init_id_buffer() on startup.
    """
    if _id_buffer_instance is None:
        raise RuntimeError(
            "IDBuffer is not initialized. "
            "Ensure init_id_buffer() is called in the service startup event."
        )
    return _id_buffer_instance
