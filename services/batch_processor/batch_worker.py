"""
Background Batch Worker

Handles periodic batch processing of URLs from Redis queue to database.
Runs as a background task or scheduled cron job.
"""
import asyncio
import uuid
import time
from datetime import datetime
import logging

from shared.config.settings import get_settings
from shared.data.repositories import URLRepository
from shared.core.schemas import URLData
from shared.core.queue_messages import URLQueueMessage
from shared.utils import request_context
from shared.middleware.metrics import (
    track_queue_operation,
    track_db_operation,
    update_queue_size,
    track_batch_processed
)
from shared.middleware.metrics_enums import QueueOperation, DBOperation

logger = logging.getLogger(__name__)
settings = get_settings()


async def process_batch_from_queue(
    url_repo: URLRepository,
    redis_queue, # why not queue :Queue here 
    batch_size: int = None
) -> dict:
    """
    Process a batch of URLs from queue and insert into database.

    Args:
        url_repo: URL repository for database operations
        redis_queue: Redis queue instance
        batch_size: Maximum number of URLs to process (defaults to settings)

    Returns:
        dict with processing statistics
    """
    if batch_size is None:
        batch_size = settings.batch_size

    # Generate unique batch ID for tracking
    batch_id = str(uuid.uuid4())[:12]
    request_context.set_request_id(f"batch-{batch_id}")

    try:
        queue_size = await redis_queue.size()
        update_queue_size(queue_size, "batch_processor")

        if queue_size == 0:
            logger.debug("Queue empty, skipping batch processing")
            return {
                "batch_id": batch_id,
                "processed": 0,
                "queue_size_before": 0,
                "queue_size_after": 0,
                "duration_ms": 0,
                "failed_parse": 0
            }

        logger.info(f"Starting batch processing: batch_id={batch_id} | queue_size={queue_size}")

        start_time = time.time()

        # Peek at items WITHOUT removing (prevents data loss on DB failure)
        items = await redis_queue.peek(count=batch_size)

        if not items:
            return {
                "batch_id": batch_id,
                "processed": 0,
                "queue_size_before": queue_size,
                "queue_size_after": queue_size,
                "duration_ms": 0,
                "failed_parse": 0
            }

        # Parse queue messages
        url_data_list = []
        failed_parse_count = 0

        for item in items:
            try:
                msg = URLQueueMessage(**item)
                url_data = URLData(
                    short_code=msg.short_code,
                    original_url=msg.original_url,
                    created_at=datetime.fromisoformat(msg.created_at)
                )
                url_data_list.append(url_data)
            except Exception as e:
                failed_parse_count += 1
                logger.error(
                    f"Failed to parse queue message: error={str(e)} | item={item}",
                    exc_info=True
                )
                continue

        if not url_data_list:
            logger.warning(
                f"All queue items failed to parse: batch_id={batch_id} | "
                f"failed_count={failed_parse_count}"
            )
            return {
                "batch_id": batch_id,
                "processed": 0,
                "queue_size_before": queue_size,
                "queue_size_after": queue_size,
                "duration_ms": 0,
                "failed_parse": failed_parse_count
            }

        # Insert to database
        db_start = time.time()

        try:
            inserted_count = await url_repo.batch_create(url_data_list)
            db_duration_ms = (time.time() - db_start) * 1000
            db_duration_seconds = db_duration_ms / 1000

            # Track DB operation with timing
            track_db_operation(DBOperation.BATCH_WRITE, db_duration_seconds, "batch_processor")

            # CRITICAL: Only remove from queue AFTER successful DB insert
            # This prevents data loss if DB fails
            items_to_remove = len(items)  # Total items peeked (including failed parses)
            remove_success = await redis_queue.remove_first(items_to_remove)
            if remove_success:
                logger.debug(f"Removed {items_to_remove} items from queue after successful DB insert")
                track_queue_operation(QueueOperation.DEQUEUE, "batch_processor")
            else:
                logger.error(
                    f"Failed to remove items from queue after DB insert | "
                    f"Items will be reprocessed on next run (duplicate inserts will be ignored)"
                )

            remaining_size = await redis_queue.size()
            update_queue_size(remaining_size, "batch_processor")

            total_duration_ms = (time.time() - start_time) * 1000

            # Track business event
            track_batch_processed(inserted_count, "batch_processor")

            logger.info(
                f"Batch INSERT successful: batch_id={batch_id} | "
                f"inserted={inserted_count} | db_time={db_duration_ms:.2f}ms | "
                f"total_time={total_duration_ms:.0f}ms | remaining_queue={remaining_size} | "
                f"failed_parse={failed_parse_count}"
            )

            return {
                "batch_id": batch_id,
                "processed": inserted_count,
                "queue_size_before": queue_size,
                "queue_size_after": remaining_size,
                "duration_ms": int(total_duration_ms),
                "failed_parse": failed_parse_count
            }

        except Exception as e:
            db_duration_ms = (time.time() - db_start) * 1000
            logger.error(
                f"Batch INSERT failed: batch_id={batch_id} | "
                f"count={len(url_data_list)} | db_time={db_duration_ms:.2f}ms | error={str(e)}",
                exc_info=True
            )
            raise

    finally:
        request_context.clear_request_id()


async def background_batch_processor(url_repo: URLRepository, redis_queue):
    """
    Background task that processes batch queue periodically.

    Only runs when ENABLE_BACKGROUND_SCHEDULER=true (local dev).
    In production (Docker/AWS), use scheduled cron job instead.

    Args:
        url_repo: URL repository for database operations
        redis_queue: Redis queue instance
    """
    logger.info(f"Background scheduler started (interval={settings.batch_interval_seconds}s)")

    while True:
        try:
            await asyncio.sleep(settings.batch_interval_seconds)

            if not redis_queue:
                continue

            # Process batch
            await process_batch_from_queue(url_repo, redis_queue)

        except asyncio.CancelledError:
            logger.info("Background scheduler cancelled gracefully")
            break
        except Exception as e:
            logger.error(
                f"Background batch processing error: error={str(e)}",
                exc_info=True
            )
            # Continue running despite errors
