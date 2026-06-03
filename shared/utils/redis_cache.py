"""
Redis-based distributed cache implementation.
"""
import json
from datetime import datetime
import redis.asyncio as aioredis
from typing import Optional, Dict, Any
import logging

from shared.utils.interfaces.cache import Cache
from shared.core.schemas import URLData
from shared.utils.timer import Timer

logger = logging.getLogger(__name__)


class RedisCache(Cache):
    """
    Redis-based cache implementing the Cache interface.

    Connection Pooling:
    - Uses built-in redis-py connection pooling (like PgBouncer for PostgreSQL)
    - Connections are reused across requests for better performance
    - Pool size should match expected concurrent requests
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 3600,
        key_prefix: str = "url:",
        max_connections: int = 50,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5
    ):
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self._client: Optional[aioredis.Redis] = None
        self._hits = 0
        self._misses = 0

        logger.info("RedisCache initialized", extra={"key_prefix": key_prefix, "ttl_seconds": ttl_seconds, "pool_size": max_connections})

    async def connect(self) -> None:
        """
        Establish Redis connection with connection pooling.

        Creates a connection pool that reuses connections (like PgBouncer).
        """
        if self._client is None:
            timer = Timer()
            try:
                self._client = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=self.max_connections,
                    socket_timeout=self.socket_timeout,
                    socket_connect_timeout=self.socket_connect_timeout
                )
                await self._client.ping()
                logger.info("Redis cache connected", extra={"pool_size": self.max_connections, "timeout_seconds": self.socket_timeout, "connect_time_ms": round(timer.total(), 2)})
            except Exception as e:
                logger.error("Redis cache connection failed", extra={"error": str(e), "connect_time_ms": round(timer.total(), 2)})
                raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis disconnected", extra={"component": "redis_cache"})

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    async def get_async(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: The short code (e.g., "abc123")

        Returns:
            Cached value if found, None on cache miss. Raises on Redis error.
        """
        if not self._client:
            raise RuntimeError("RedisCache not connected")

        timer = Timer()
        try:
            full_key = self._make_key(key)
            value = await self._client.get(full_key)

            if value is None:
                self._misses += 1
                logger.debug("Cache miss", extra={"short_code": key, "redis_time_ms": round(timer.total(), 2)})
                return None

            self._hits += 1
            logger.debug("Cache hit", extra={"short_code": key, "redis_time_ms": round(timer.total(), 2)})

            data_dict = json.loads(value)

            # Reconstruct URLData if it's a dictionary
            if isinstance(data_dict, dict) and 'short_code' in data_dict:
                return URLData(
                    short_code=data_dict['short_code'],
                    original_url=data_dict['original_url'],
                    created_at=datetime.fromisoformat(data_dict['created_at'])
                )

            return data_dict

        except Exception as e:
            logger.error("Redis GET error", extra={"short_code": key, "error": str(e), "redis_time_ms": round(timer.total(), 2)})
            raise

    async def set_async(self, key: str, value: Any) -> None:
        """
        Store value in cache. Raises on failure.

        Args:
            key: The short code (e.g., "abc123")
            value: The data to cache (e.g., original URL)
        """
        if not self._client:
            raise RuntimeError("RedisCache not connected")

        timer = Timer()
        try:
            full_key = self._make_key(key)

            if hasattr(value, 'model_dump'):
                value_dict = value.model_dump()
            elif hasattr(value, 'dict'):
                value_dict = value.dict()
            else:
                value_dict = value

            value_json = json.dumps(value_dict, default=str)

            await self._client.set(full_key, value_json, ex=self.ttl_seconds)
            logger.debug("Cache SET", extra={"short_code": key, "ttl_seconds": self.ttl_seconds, "redis_time_ms": round(timer.total(), 2)})

        except Exception as e:
            logger.error("Redis SET error", extra={"short_code": key, "error": str(e), "redis_time_ms": round(timer.total(), 2)})
            raise

    async def delete_async(self, key: str) -> None:
        """
        Remove entry from cache. Raises on failure.

        Args:
            key: The short code to remove
        """
        if not self._client:
            raise RuntimeError("RedisCache not connected")

        try:
            full_key = self._make_key(key)
            result = await self._client.delete(full_key)
            if result > 0:
                logger.debug("Cache DELETE", extra={"short_code": key})

        except Exception as e:
            logger.error("Redis DELETE error", extra={"short_code": key, "error": str(e)})
            raise

    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache performance statistics.

        Returns:
            Dictionary with hits, misses, and hit rate
        """
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0

        return {
            "cache_type": "redis",
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 2),
            "ttl_seconds": self.ttl_seconds,
            "key_prefix": self.key_prefix
        }
