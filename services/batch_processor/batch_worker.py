"""
Background Batch Worker

Handles periodic batch processing of URLs from Redis queue to database.
Runs as a background task or scheduled cron job.
"""

import asyncio
import uuid
from datetime import datetime
import logging

from shared.utils.timer import Timer

from shared.config.settings import get_settings
from shared.data.repositories import URLRepository
from shared.core.schemas import URLData
from shared.core.queue_messages import URLQueueMessage, DeadLetterQueueMessage
from shared.utils import request_context
from shared.utils.interfaces.queue import Queue
from shared.middleware.metrics import (
    track_queue_operation,
    track_db_operation,
    update_queue_size,
    track_batch_processed,
)
from shared.middleware.metrics_enums import QueueOperation, DBOperation

logger = logging.getLogger(__name__)
settings = get_settings()


async def process_batch_from_queue(
    url_repo: URLRepository, queue: Queue, dlq: Queue, batch_size: int = None
) -> dict:
    """
    Process a batch of URLs from queue and insert into database.

    Args:
        url_repo: URL repository for database operations
        queue: Queue instance (Redis or other implementation)
        dlq: Dead-letter queue for failed/unparseable messages
        batch_size: Maximum number of URLs to process (defaults to settings)

    Returns:
        dict with processing statistics
    """
    if batch_size is None:
        batch_size = settings.batch_size

    # Generate unique batch ID for tracking
    batch_id = str(uuid.uuid4())[:12]
    request_context.set_batch_id(f"batch-{batch_id}")

    try:
        queue_size = await queue.size()
        update_queue_size(queue_size, "batch_processor")

        if queue_size == 0:
            logger.debug("Queue empty, skipping batch processing")
            return {
                "batch_id": batch_id,
                "processed": 0,
                "queue_size_before": 0,
                "queue_size_after": 0,
                "duration_ms": 0,
                "failed_parse": 0,
            }

        logger.info(
            "Starting batch processing",
            extra={"batch_id": batch_id, "queue_size": queue_size},
        )

        timer = Timer()

        # Peek at items WITHOUT removing (prevents data loss on DB failure)
        items = await queue.peek(count=batch_size)

        if not items:
            return {
                "batch_id": batch_id,
                "processed": 0,
                "queue_size_before": queue_size,
                "queue_size_after": queue_size,
                "duration_ms": 0,
                "failed_parse": 0,
            }

        # Parse queue messages
        url_data_list = []
        failed_parse_count = 0

        for item in items:
            try:
                msg = URLQueueMessage(**item)

                # Log individual item with original request_id for end-to-end traceability
                logger.debug(
                    "Processing queued URL",
                    extra={
                        "short_code": msg.short_code,
                        "original_url": msg.original_url,
                    },
                )

                url_data = URLData(
                    short_code=msg.short_code,
                    original_url=msg.original_url,
                    created_at=datetime.fromisoformat(msg.created_at),
                )
                url_data_list.append(url_data)
            except Exception as e:
                failed_parse_count += 1
                logger.error(
                    "Failed to parse queue message",
                    extra={
                        "error": str(e),
                        "request_id": item.get("request_id", "unknown"),
                    },
                    exc_info=True,
                )

                # Move failed message to dead-letter queue for later inspection
                try:
                    dlq_msg = DeadLetterQueueMessage.from_failed_parse(
                        original_message=item, exception=e, batch_id=batch_id
                    )
                    await dlq.enqueue(dlq_msg.to_dict())
                    logger.info(
                        "Moved failed message to DLQ",
                        extra={"error_type": dlq_msg.error_type},
                    )
                except Exception as dlq_error:
                    logger.critical("Message lost: failed to enqueue to DLQ", extra={"error": str(dlq_error), "lost_message": item}, exc_info=True)

                continue

        if len(url_data_list) == 0:
            logger.warning(
                "All queue items failed to parse",
                extra={"batch_id": batch_id, "failed_count": failed_parse_count},
            )
            return {
                "batch_id": batch_id,
                "processed": 0,
                "queue_size_before": queue_size,
                "queue_size_after": queue_size,
                "duration_ms": 0,
                "failed_parse": failed_parse_count,
            }

        # Insert to database
        db_timer = Timer()

        try:
            inserted_count = await url_repo.batch_create(url_data_list)
            db_duration = db_timer.total()
            db_duration_seconds = db_duration / 1000

            # Track DB operation with timing
            track_db_operation(
                DBOperation.BATCH_WRITE, db_duration_seconds, "batch_processor"
            )

            # CRITICAL: Only remove from queue AFTER successful DB insert
            # This prevents data loss if DB fails
            items_to_remove = len(items)  # Total items peeked (including failed parses)
            remove_success = await queue.remove_first(items_to_remove)
            if remove_success:
                logger.debug(
                    "Removed items from queue after successful DB insert",
                    extra={"queue_size": items_to_remove},
                )
                track_queue_operation(QueueOperation.DEQUEUE, "batch_processor")
            else:
                logger.error(
                    "Failed to remove items from queue after DB insert — will reprocess on next run"
                )

            remaining_size = await queue.size()
            update_queue_size(remaining_size, "batch_processor")

            total_duration = timer.total()

            # Track business event
            track_batch_processed(inserted_count, "batch_processor")

            logger.info(
                "Batch INSERT successful",
                extra={
                    "batch_id": batch_id,
                    "inserted": inserted_count,
                    "db_time_ms": round(db_duration, 2),
                    "total_time_ms": round(total_duration, 2),
                    "queue_size": remaining_size,
                    "failed_parse": failed_parse_count,
                },
            )

            return {
                "batch_id": batch_id,
                "processed": inserted_count,
                "queue_size_before": queue_size,
                "queue_size_after": remaining_size,
                "duration_ms": int(total_duration),
                "failed_parse": failed_parse_count,
            }

        except Exception as e:
            db_duration = db_timer.total()
            pool_status = url_repo.get_pool_status()
            logger.error(
                "Batch INSERT failed",
                extra={
                    "batch_id": batch_id,
                    "count": len(url_data_list),
                    "db_time_ms": round(db_duration, 2),
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    finally:
        request_context.clear_batch_id()


async def background_batch_processor(
    url_repo: URLRepository, queue: Queue, dlq: Queue
) -> None:
    """
    Background task that processes batch queue periodically.

    Only runs when ENABLE_BACKGROUND_SCHEDULER=true (local dev).
    In production (Docker/AWS), use scheduled cron job instead.

    Args:
        url_repo: URL repository for database operations
        queue: Queue instance (Redis or other implementation)
        dlq: Dead-letter queue for failed/unparseable messages
    """
    logger.info(
        "Background scheduler started",
        extra={"interval_seconds": settings.batch_interval_seconds},
    )

    while True:
        try:
            await asyncio.sleep(settings.batch_interval_seconds)

            # Process batch
            await process_batch_from_queue(url_repo, queue, dlq)

        except asyncio.CancelledError:
            logger.info("Background scheduler cancelled gracefully")
            break
        except Exception as e:
            logger.error("Background batch processing error", extra={"error": str(e)}, exc_info=True)
            # Continue running despite errors
