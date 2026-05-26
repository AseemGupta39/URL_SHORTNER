"""
Click Analytics Background Worker

Handles periodic batch processing of click events from Redis queue to database.

Only runs when ENABLE_BACKGROUND_SCHEDULER=true (local dev).
In production (Docker/AWS), use scheduled cron job instead.
"""
import asyncio
import uuid
from datetime import datetime
import logging

from shared.utils.timer import Timer

from shared.config.settings import get_settings
from shared.data.interfaces.click_repository import ClickRepository
from shared.core.schemas import ClickData
from shared.core.queue_messages import ClickQueueMessage, DeadLetterQueueMessage
from shared.utils import request_context
from shared.utils.interfaces.queue import Queue
from shared.middleware.metrics import (
    track_queue_operation,
    track_db_operation,
    update_queue_size,
    track_batch_processed
)
from shared.middleware.metrics_enums import QueueOperation, DBOperation

logger = logging.getLogger(__name__)
settings = get_settings()


class ClickBatchResult:
    """Strongly-typed result for click batch processing (no dynamic dict)."""

    def __init__(
        self,
        batch_id: str,
        processed: int,
        queue_size_before: int,
        queue_size_after: int,
        duration_ms: float,
        failed_parse: int
    ):
        self.batch_id = batch_id
        self.processed = processed
        self.queue_size_before = queue_size_before
        self.queue_size_after = queue_size_after
        self.duration_ms = duration_ms
        self.failed_parse = failed_parse

    def to_dict(self) -> dict:
        """Convert to dict for logging/serialization only."""
        return {
            "batch_id": self.batch_id,
            "processed": self.processed,
            "queue_size_before": self.queue_size_before,
            "queue_size_after": self.queue_size_after,
            "duration_ms": self.duration_ms,
            "failed_parse": self.failed_parse
        }


async def process_click_batch_from_queue(
    click_repo: ClickRepository,
    queue: Queue,
    dlq: Queue,
    batch_size: int = None
) -> ClickBatchResult:
    """
    Process a batch of click events from queue and insert into database.

    Args:
        click_repo: Click repository for database operations
        queue: Queue instance (Redis or other implementation)
        dlq: Dead-letter queue for failed/unparseable messages
        batch_size: Maximum number of clicks to process (defaults to settings)

    Returns:
        ClickBatchResult with processing statistics
    """
    if batch_size is None:
        batch_size = settings.batch_size

    # Generate unique batch ID for tracking (logged automatically via request_context)
    batch_id = str(uuid.uuid4())[:12]
    request_context.set_batch_id(f"click-batch-{batch_id}")

    timer = Timer()
    outcome = "unknown"
    processed = 0
    failed_parse_count = 0
    db_time_ms = 0.0
    queue_size_before = 0

    try:
        queue_size_before = await queue.size()
        update_queue_size(queue_size_before, "click_analytics")

        if queue_size_before == 0:
            logger.debug("Click queue empty, skipping batch processing")
            outcome = "empty"
            return ClickBatchResult(
                batch_id=batch_id,
                processed=0,
                queue_size_before=0,
                queue_size_after=0,
                duration_ms=0,
                failed_parse=0
            )

        logger.info("Starting click batch processing", extra={"queue_size": queue_size_before})

        # Peek at items WITHOUT removing (prevents data loss on DB failure)
        items = await queue.peek(count=batch_size)

        if not items:
            outcome = "empty"
            return ClickBatchResult(
                batch_id=batch_id,
                processed=0,
                queue_size_before=queue_size_before,
                queue_size_after=queue_size_before,
                duration_ms=0,
                failed_parse=0
            )

        # Parse queue messages into ClickData instances
        click_data_list = []

        for item in items:
            # Push the original shorten-request's request_id into the worker's
            # contextvar for this iteration. The logging factory will then
            # auto-stamp every log in this loop. Token + reset prevents leakage.
            item_request_id = item.get("request_id", "") if isinstance(item, dict) else ""
            request_id_token = request_context.request_id_var.set(item_request_id)
            try:
                try:
                    msg = ClickQueueMessage(**item)

                    logger.debug("Processing queued click", extra={"short_code": msg.short_code, "original_url": msg.original_url})

                    click_data = ClickData(
                        short_code=msg.short_code,
                        original_url=msg.original_url,
                        clicked_at=datetime.fromisoformat(msg.clicked_at),
                        ip_address=msg.ip_address,
                        user_agent=msg.user_agent,
                        referrer=msg.referrer
                    )
                    click_data_list.append(click_data)

                except Exception as e:
                    failed_parse_count += 1
                    logger.error("Failed to parse click queue message", extra={"error": str(e)}, exc_info=True)

                    # Move failed message to dead-letter queue for later inspection
                    try:
                        dlq_msg = DeadLetterQueueMessage.from_failed_parse(
                            original_message=item,
                            exception=e,
                            batch_id=batch_id
                        )
                        await dlq.enqueue(dlq_msg.to_dict())
                        logger.info("Moved failed message to DLQ", extra={"error_type": dlq_msg.error_type})
                    except Exception as dlq_error:
                        logger.critical("Message lost: failed to enqueue to DLQ", extra={"error": str(dlq_error), "lost_message": item}, exc_info=True)
            finally:
                request_context.request_id_var.reset(request_id_token)

        if len(click_data_list) == 0:
            logger.warning("All click items failed to parse", extra={"total_items": len(items), "failed_parse": failed_parse_count})
            outcome = "all_parse_failed"
            remaining_size = await queue.size()
            return ClickBatchResult(
                batch_id=batch_id,
                processed=0,
                queue_size_before=queue_size_before,
                queue_size_after=remaining_size,
                duration_ms=timer.total(),
                failed_parse=failed_parse_count
            )

        # Insert to database
        db_timer = Timer()

        try:
            inserted_count = await click_repo.batch_create(click_data_list)
            db_time_ms = db_timer.total()
            db_duration_seconds = db_time_ms / 1000

            # Track DB operation with timing
            track_db_operation(DBOperation.BATCH_WRITE, db_duration_seconds, "click_analytics")

            # CRITICAL: Only remove from queue AFTER successful DB insert
            # This prevents data loss if DB fails
            items_to_remove = len(items)  # Total items peeked (including failed parses)
            await queue.remove_first(items_to_remove)  # raises on failure — caught by outer except, items reprocessed on next run
            logger.debug("Removed click items from queue after successful DB insert", extra={"queue_size": items_to_remove})
            track_queue_operation(QueueOperation.DEQUEUE, "click_analytics")

            remaining_size = await queue.size()
            update_queue_size(remaining_size, "click_analytics")

            total_duration = timer.total()

            # Track business event
            track_batch_processed(inserted_count, "click_analytics")

            outcome = "success"
            processed = inserted_count

            return ClickBatchResult(
                batch_id=batch_id,
                processed=inserted_count,
                queue_size_before=queue_size_before,
                queue_size_after=remaining_size,
                duration_ms=total_duration,
                failed_parse=failed_parse_count
            )

        except Exception as e:
            db_time_ms = db_timer.total()
            logger.error("Click batch INSERT failed", extra={"error": str(e)}, exc_info=True)
            outcome = "failed"
            raise

    except Exception as e:
        logger.error("Click batch processing failed", extra={"error": str(e)}, exc_info=True)
        outcome = "failed"
        raise
    finally:
        # NOTE: batch_id is already on every LogRecord via the factory in
        # logging_config.py (set via set_batch_id above). Adding it here
        # would raise KeyError.
        logger.info("canonical", extra={
            "outcome": outcome,
            "processed": processed,
            "failed_parse": failed_parse_count,
            "queue_size_before": queue_size_before,
            "db_time_ms": round(db_time_ms, 2),
            "duration_ms": round(timer.total(), 2),
            "worker": "click_batch",
        })
        request_context.clear_batch_id()


async def background_click_batch_processor(
    click_repo: ClickRepository,
    queue: Queue,
    dlq: Queue,
    interval_seconds: int = None
) -> None:
    """
    Background task that periodically processes click batches from queue.

    This function runs indefinitely and processes batches at regular intervals.

    Only runs when ENABLE_BACKGROUND_SCHEDULER=true (local dev).
    In production (Docker/AWS), use scheduled cron job instead.

    Args:
        click_repo: Click repository for database operations
        queue: Queue instance (Redis or other implementation)
        dlq: Dead-letter queue for failed/unparseable messages
        interval_seconds: Seconds to wait between batch processing (defaults to settings.click_batch_interval_seconds)
    """
    if interval_seconds is None:
        interval_seconds = settings.click_batch_interval_seconds

    logger.info("Click analytics background scheduler started", extra={"interval_seconds": interval_seconds, "batch_size": settings.batch_size})

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await process_click_batch_from_queue(click_repo, queue, dlq)

        except asyncio.CancelledError:
            logger.info("Click analytics background scheduler cancelled gracefully")
            break
        except Exception as e:
            logger.error("Click analytics batch processing error", extra={"error": str(e)}, exc_info=True)
            # Continue running despite errors
