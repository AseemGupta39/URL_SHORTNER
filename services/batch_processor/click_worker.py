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

    try:
        queue_size = await queue.size()
        update_queue_size(queue_size, "click_analytics")

        if queue_size == 0:
            logger.debug("Click queue empty, skipping batch processing")
            return ClickBatchResult(
                batch_id=batch_id,
                processed=0,
                queue_size_before=0,
                queue_size_after=0,
                duration_ms=0,
                failed_parse=0
            )

        logger.info(f"Starting click batch processing: batch_id={batch_id} | queue_size={queue_size}")

        timer = Timer()

        # Peek at items WITHOUT removing (prevents data loss on DB failure)
        items = await queue.peek(count=batch_size)

        if not items:
            return ClickBatchResult(
                batch_id=batch_id,
                processed=0,
                queue_size_before=queue_size,
                queue_size_after=queue_size,
                duration_ms=0,
                failed_parse=0
            )

        # Parse queue messages into ClickData instances
        click_data_list = []
        failed_parse_count = 0

        for item in items:
            try:
                # Parse queue message
                msg = ClickQueueMessage(**item)

                # Log individual item with original request_id for end-to-end traceability
                logger.debug(
                    f"Processing queued click: short_code={msg.short_code} | "
                    f"original_request_id={msg.request_id}"
                )

                # Convert to ClickData (domain model)
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
                logger.error(
                    f"Failed to parse click queue message: error={str(e)} | "
                    f"request_id={item.get('request_id', 'unknown')}",
                    exc_info=True
                )

                # Move failed message to dead-letter queue for later inspection
                try:
                    dlq_msg = DeadLetterQueueMessage.from_failed_parse(
                        original_message=item,
                        exception=e,
                        batch_id=batch_id
                    )
                    await dlq.enqueue(dlq_msg.to_dict())
                    logger.info(
                        f"Moved failed message to DLQ: request_id={dlq_msg.request_id} | "
                        f"error_type={dlq_msg.error_type}"
                    )
                except Exception as dlq_error:
                    logger.error(
                        f"CRITICAL: Failed to enqueue to DLQ: error={dlq_error} | "
                        f"original_message_lost={item}",
                        exc_info=True
                    )

                # Continue processing other items

        if not click_data_list:
            logger.warning(
                f"All items failed to parse: batch_id={batch_id} | "
                f"total_items={len(items)} | failed={failed_parse_count}"
            )
            remaining_size = await queue.size()
            return ClickBatchResult(
                batch_id=batch_id,
                processed=0,
                queue_size_before=queue_size,
                queue_size_after=remaining_size,
                duration_ms=timer.total(),
                failed_parse=failed_parse_count
            )

        # Insert to database
        db_timer = Timer()

        try:
            inserted_count = await click_repo.batch_create(click_data_list)
            db_duration = db_timer.total()
            db_duration_seconds = db_duration / 1000

            # Track DB operation with timing
            track_db_operation(DBOperation.BATCH_WRITE, db_duration_seconds, "click_analytics")

            # CRITICAL: Only remove from queue AFTER successful DB insert
            # This prevents data loss if DB fails
            items_to_remove = len(items)  # Total items peeked (including failed parses)
            remove_success = await queue.remove_first(items_to_remove)
            if remove_success:
                logger.debug(f"Removed {items_to_remove} click items from queue after successful DB insert")
                track_queue_operation(QueueOperation.DEQUEUE, "click_analytics")
            else:
                logger.error(
                    f"Failed to remove click items from queue after DB insert | "
                    f"Items will be reprocessed on next run (duplicate inserts will be ignored)"
                )

            remaining_size = await queue.size()
            update_queue_size(remaining_size, "click_analytics")

            total_duration = timer.total()

            # Track business event
            track_batch_processed(inserted_count, "click_analytics")

            logger.info(
                f"Click batch INSERT successful: batch_id={batch_id} | "
                f"inserted={inserted_count} | db_time={db_duration:.2f}ms | "
                f"total_time={total_duration:.0f}ms | remaining_queue={remaining_size} | "
                f"failed_parse={failed_parse_count}"
            )

            return ClickBatchResult(
                batch_id=batch_id,
                processed=inserted_count,
                queue_size_before=queue_size,
                queue_size_after=remaining_size,
                duration_ms=total_duration,
                failed_parse=failed_parse_count
            )

        except Exception as e:
            logger.error(
                f"Click batch INSERT failed: batch_id={batch_id} | error={str(e)}",
                exc_info=True
            )
            raise

    except Exception as e:
        logger.error(
            f"Click batch processing failed: batch_id={batch_id} | error={str(e)}",
            exc_info=True
        )
        raise
    finally:
        # Clear batch context for explicit lifecycle management
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

    logger.info(
        f"Click analytics background scheduler started: interval={interval_seconds}s | "
        f"batch_size={settings.batch_size}"
    )

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await process_click_batch_from_queue(click_repo, queue, dlq)

        except asyncio.CancelledError:
            logger.info("Click analytics background scheduler cancelled gracefully")
            break
        except Exception as e:
            logger.error(
                f"Click analytics batch processing error: error={str(e)}",
                exc_info=True
            )
            # Continue running despite errors
