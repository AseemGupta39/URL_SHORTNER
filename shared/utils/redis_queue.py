"""
Redis-based queue implementation.
"""
import json
import redis.asyncio as aioredis
from typing import Optional, List, Dict, Any
from shared.utils.interfaces.queue import Queue
from shared.utils.logger import get_logger

logger = get_logger()


class RedisQueue(Queue):
    """Redis-based queue for batching URL insertions."""

    def __init__(self, redis_url: str, queue_name: str = "url_batch_queue"):
        self.redis_url = redis_url
        self.queue_name = queue_name
        self._client: Optional[aioredis.Redis] = None

        logger.info(f"RedisQueue initialized (queue={queue_name})")

    async def connect(self):
        """Establish Redis connection."""
        if self._client is None:
            try:
                self._client = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=10
                )
                await self._client.ping()
                logger.info("RedisQueue connected")
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
