"""
Retry an async callable with exponential backoff.
"""
import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


async def retry_with_backoff(
    operation: Callable[[], Awaitable[_T]],
    *,
    max_retries: int = 3,
    backoff_base_seconds: float = 1.0,
    operation_name: str = "operation",
) -> _T:
    """
    Retry an async callable with exponential backoff.

    Sleeps backoff_base_seconds * 2**attempt between attempts
    (e.g. 1s, 2s, 4s with defaults). Reraises the final exception
    after max_retries attempts. The last failing attempt does not sleep.

    Pass a no-arg callable. To bind args, use a lambda:
        await retry_with_backoff(lambda: repo.batch_create(items), ...)
    """
    for attempt in range(max_retries):
        try:
            return await operation()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait_seconds = backoff_base_seconds * (2 ** attempt)
            logger.warning(
                "Operation failed, retrying",
                extra={
                    "operation": operation_name,
                    "attempt": attempt + 1,
                    "wait_seconds": wait_seconds,
                    "error": str(e),
                },
            )
            await asyncio.sleep(wait_seconds)