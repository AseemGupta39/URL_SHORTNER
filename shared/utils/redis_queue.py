"""
Redis-based queue implementation.
"""
import json
import redis.asyncio as aioredis
from typing import Optional, List, Dict, Any
import logging

from shared.utils.interfaces.queue import Queue
from shared.utils.timer import Timer

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
                logger.info(
                    f"RedisQueue connected | queue={self.queue_name} | pool_size={self.max_connections} | "
                    f"timeout={self.socket_timeout}s | connect_time={timer.total():.2f}ms"
                )
            except Exception as e:
                logger.error(f"RedisQueue connection failed: {e} | connect_time={timer.total():.2f}ms")
                raise

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("RedisQueue disconnected")

    async def enqueue(self, data: Dict[str, Any]) -> None:
        """
        Add item to queue (FIFO order). Raises on failure.

        Uses RPUSH to add to right side, maintaining FIFO order with LRANGE from left.

        Args:
            data: Dictionary to enqueue
        """
        if not self._client:
            raise RuntimeError("RedisQueue not connected")

        timer = Timer()
        try:
            data_json = json.dumps(data)
            await self._client.rpush(self.queue_name, data_json)
            logger.debug("Enqueued to queue", extra={"queue_name": self.queue_name, "redis_time_ms": round(timer.total(), 2)})

        except Exception as e:
            logger.error("RedisQueue enqueue error", extra={"queue_name": self.queue_name, "error": str(e), "redis_time_ms": round(timer.total(), 2)})
            raise

    async def dequeue(self, count: int = 1) -> List[Dict[str, Any]]:
        """
        Remove and return items from queue. Raises on Redis error. Returns [] on empty queue.

        Args:
            count: Number of items to dequeue

        Returns:
            List of dictionaries, empty list if queue is empty
        """
        if not self._client:
            raise RuntimeError("RedisQueue not connected")

        timer = Timer()
        try:
            if count == 1:
                result = await self._client.rpop(self.queue_name)
                if result:
                    logger.debug("Dequeued 1 item", extra={"queue_name": self.queue_name, "redis_time_ms": round(timer.total(), 2)})
                    return [json.loads(result)]
                return []
            else:
                results = await self._client.rpop(self.queue_name, count)
                if results:
                    logger.debug("Dequeued items", extra={"queue_name": self.queue_name, "count": len(results), "redis_time_ms": round(timer.total(), 2)})
                    return [json.loads(item) for item in results]
                return []

        except Exception as e:
            logger.error("RedisQueue dequeue error", extra={"queue_name": self.queue_name, "error": str(e), "redis_time_ms": round(timer.total(), 2)})
            raise

    async def size(self) -> int:
        """Get number of items in queue. Raises on Redis error."""
        if not self._client:
            raise RuntimeError("RedisQueue not connected")

        try:
            return await self._client.llen(self.queue_name)

        except Exception as e:
            logger.error("RedisQueue size error", extra={"queue_name": self.queue_name, "error": str(e)})
            raise

    async def clear(self) -> None:
        """Clear all items from queue. Raises on failure."""
        if not self._client:
            raise RuntimeError("RedisQueue not connected")

        try:
            await self._client.delete(self.queue_name)
            logger.info("Cleared queue", extra={"queue_name": self.queue_name})

        except Exception as e:
            logger.error("RedisQueue clear error", extra={"queue_name": self.queue_name, "error": str(e)})
            raise

    async def peek(self, count: int = 1) -> List[Dict[str, Any]]:
        """
        Peek at items without removing them from queue (FIFO order). Raises on Redis error. Returns [] on empty queue.

        Uses LRANGE to read from left side, maintaining FIFO order with RPUSH to right.

        Args:
            count: Number of items to peek at

        Returns:
            List of dictionaries in FIFO order (oldest first), empty list if queue is empty
        """
        if not self._client:
            raise RuntimeError("RedisQueue not connected")

        timer = Timer()
        try:
            results = await self._client.lrange(self.queue_name, 0, count - 1)
            if results:
                logger.debug("Peeked items", extra={"queue_name": self.queue_name, "count": len(results), "redis_time_ms": round(timer.total(), 2)})
                return [json.loads(item) for item in results]
            return []

        except Exception as e:
            logger.error("RedisQueue peek error", extra={"queue_name": self.queue_name, "error": str(e), "redis_time_ms": round(timer.total(), 2)})
            raise

    async def remove_first(self, count: int) -> None:
        """
        Remove first N items from queue (FIFO order). Raises on failure.

        Uses LTRIM to remove items from left side AFTER successful processing.
        Works with RPUSH enqueue and LRANGE peek to maintain FIFO order.

        Args:
            count: Number of items to remove from front (oldest items)
        """
        if not self._client:
            raise RuntimeError("RedisQueue not connected")

        timer = Timer()
        try:
            await self._client.ltrim(self.queue_name, count, -1)
            logger.debug("Removed first N items from queue", extra={"queue_name": self.queue_name, "count": count, "redis_time_ms": round(timer.total(), 2)})

        except Exception as e:
            logger.error("RedisQueue remove_first error", extra={"queue_name": self.queue_name, "count": count, "error": str(e), "redis_time_ms": round(timer.total(), 2)})
            raise
