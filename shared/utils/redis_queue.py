"""
Redis-based queue implementation.
"""
import json
import redis.asyncio as aioredis
from typing import Optional, List, Dict, Any
import logging

from shared.utils.interfaces.queue import Queue

logger = logging.getLogger(__name__)


class RedisQueue(Queue):
    """
    Redis-based queue for batching URL insertions.

    Connection Pooling:
    - Uses built-in redis-py connection pooling (like PgBouncer for PostgreSQL)
    - Connections are reused across requests for better performance
    - Pool size should match expected concurrent requests
    """

    def __init__(
        self,
        redis_url: str,
        queue_name: str = "url_batch_queue",
        max_connections: int = 50,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 5
    ):
        self.redis_url = redis_url
        self.queue_name = queue_name
        self.max_connections = max_connections
        self.socket_timeout = socket_timeout
        self.socket_connect_timeout = socket_connect_timeout
        self._client: Optional[aioredis.Redis] = None

        logger.info(
            f"RedisQueue initialized (queue={queue_name}, pool_size={max_connections})"
        )

    async def connect(self):
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
                    f"RedisQueue connected (pool_size={self.max_connections}, "
                    f"timeout={self.socket_timeout}s)"
                )
            except Exception as e:
                logger.error(f"RedisQueue connection failed: {e}")
                raise

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("RedisQueue disconnected")

    async def enqueue(self, data: Dict[str, Any]) -> bool:
        """
        Add item to queue.

        Args:
            data: Dictionary to enqueue

        Returns:
            True if successful, False otherwise
        """
        if not self._client:
            logger.warning("RedisQueue not connected")
            return False

        try:
            data_json = json.dumps(data)
            await self._client.lpush(self.queue_name, data_json)
            logger.debug(f"Enqueued to {self.queue_name}")
            return True

        except Exception as e:
            logger.error(f"RedisQueue enqueue error: {e}")
            return False

    async def dequeue(self, count: int = 1) -> List[Dict[str, Any]]:
        """
        Remove and return items from queue.

        Args:
            count: Number of items to dequeue

        Returns:
            List of dictionaries
        """
        if not self._client:
            logger.warning("RedisQueue not connected")
            return []

        try:
            if count == 1:
                result = await self._client.rpop(self.queue_name)
                if result:
                    return [json.loads(result)]
                return []
            else:
                results = await self._client.rpop(self.queue_name, count)
                if results:
                    return [json.loads(item) for item in results]
                return []

        except Exception as e:
            logger.error(f"RedisQueue dequeue error: {e}")
            return []

    async def size(self) -> int:
        """Get number of items in queue."""
        if not self._client:
            logger.warning("RedisQueue not connected")
            return 0

        try:
            return await self._client.llen(self.queue_name)

        except Exception as e:
            logger.error(f"RedisQueue size error: {e}")
            return 0

    async def clear(self) -> bool:
        """Clear all items from queue."""
        if not self._client:
            logger.warning("RedisQueue not connected")
            return False

        try:
            await self._client.delete(self.queue_name)
            logger.info(f"Cleared queue: {self.queue_name}")
            return True

        except Exception as e:
            logger.error(f"RedisQueue clear error: {e}")
            return False


_redis_queue: Optional[RedisQueue] = None


def get_redis_queue(redis_url: str, queue_name: str = "url_batch_queue") -> RedisQueue:
    """Get or create global Redis queue instance."""
    global _redis_queue
    if _redis_queue is None:
        _redis_queue = RedisQueue(redis_url, queue_name)
    return _redis_queue
