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

        logger.info(
            f"RedisCache initialized (prefix={key_prefix}, ttl={ttl_seconds}s, "
            f"pool_size={max_connections})"
        )

    async def connect(self) -> None:
        """
        Establish Redis connection with connection pooling.

        Creates a connection pool that reuses connections (like PgBouncer).
        """
        if self._client is None:
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
                logger.info(
                    f"Redis connected (pool_size={self.max_connections}, "
                    f"timeout={self.socket_timeout}s)"
                )
            except Exception as e:
                logger.error(f"Redis connection failed: {e}")
                raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis disconnected")

    def _make_key(self, key: str) -> str:
        return f"{self.key_prefix}{key}"

    async def get_async(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: The short code (e.g., "abc123")

        Returns:
            Cached value if found, None otherwise
        """
        if not self._client:
            logger.warning("Redis not connected")
            return None

        timer = Timer()
        try:
            full_key = self._make_key(key)
            value = await self._client.get(full_key)

            if value is None:
                self._misses += 1
                logger.debug(f"Cache miss: {key} | redis_time={timer.total():.2f}ms")
                return None

            self._hits += 1
            logger.debug(f"Cache hit: {key} | redis_time={timer.total():.2f}ms")

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
            logger.error(f"Redis GET error [{key}]: {e} | redis_time={timer.total():.2f}ms")
            self._misses += 1
            return None

    async def set_async(self, key: str, value: Any) -> bool:
        """
        Store value in cache.

        Args:
            key: The short code (e.g., "abc123")
            value: The data to cache (e.g., original URL)

        Returns:
            True if successful, False otherwise
        """
        if not self._client:
            logger.warning("Redis not connected")
            return False

        timer = Timer()
        try:
            full_key = self._make_key(key)

            # Handle Pydantic models
            if hasattr(value, 'model_dump'):
                value_dict = value.model_dump()
            elif hasattr(value, 'dict'):
                value_dict = value.dict()
            else:
                value_dict = value

            value_json = json.dumps(value_dict, default=str)

            await self._client.set(full_key, value_json, ex=self.ttl_seconds)
            logger.debug(f"Cached: {key} (ttl={self.ttl_seconds}s) | redis_time={timer.total():.2f}ms")
            return True

        except Exception as e:
            logger.error(f"Redis SET error [{key}]: {e} | redis_time={timer.total():.2f}ms")
            return False

    async def delete_async(self, key: str) -> bool:
        """
        Remove entry from cache.

        Args:
            key: The short code to remove

        Returns:
            True if key was found and deleted, False if not found
        """
        if not self._client:
            logger.warning("Redis not connected")
            return False

        try:
            full_key = self._make_key(key)
            result = await self._client.delete(full_key)
            deleted = result > 0

            if deleted:
                logger.debug(f"Deleted: {key}")

            return deleted

        except Exception as e:
            logger.error(f"Redis DELETE error [{key}]: {e}")
            return False

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
