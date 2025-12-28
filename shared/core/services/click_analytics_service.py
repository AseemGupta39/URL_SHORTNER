"""
Click Analytics Service - Handles click tracking and analytics business logic.
"""
from datetime import datetime
from typing import Optional
import logging

from shared.core.schemas import ClickData
from shared.core.queue_messages import ClickQueueMessage
from shared.data.interfaces.click_repository import ClickRepository
from shared.utils.interfaces.queue import Queue

logger = logging.getLogger(__name__)


class ClickAnalyticsService:
    """
    Service layer handling click analytics tracking business logic.

    Responsibilities:
    - Track click events with IP, user agent, referrer
    - Queue clicks for async batch processing
    - Graceful degradation if queue unavailable (log only, don't crash redirect)
    - Retrieve analytics data for reporting

    Architecture:
    - Async queue-based writes (high throughput, don't slow redirects)
    - Batch processing for efficient DB writes
    - Fail-open design: click tracking failure doesn't break redirects
    """

    def __init__(
        self,
        click_repo: ClickRepository,
        queue: Optional[Queue] = None
    ):
        """
        Initialize click analytics service.

        Args:
            click_repo: Repository for click data persistence
            queue: Queue for batch processing (Redis, Kafka, etc.)
        """
        self.click_repo = click_repo
        self.queue = queue

    async def track_click(
        self,
        short_code: str,
        original_url: str,
        ip_address: str,
        user_agent: str,
        referrer: Optional[str] = None
    ) -> bool:
        """
        Track a click event asynchronously.

        Uses fail-open design: never raises exceptions, returns bool for caller flexibility.

        Args:
            short_code: The short code that was clicked
            original_url: The original URL (denormalized for performance)
            ip_address: Client IP address
            user_agent: Client User-Agent header
            referrer: HTTP Referer header (optional, can be None for direct navigation)

        Returns:
            True if click was successfully tracked (queued or saved)
            False if tracking failed (caller decides if this matters)

        Design:
        - Queues click for batch processing (async)
        - Falls back to sync write if queue unavailable (graceful degradation)
        - Never raises exceptions (fail-open for redirect)
        - Returns bool for caller flexibility (redirect ignores, admin dashboard uses)
        """
        try:
            clicked_at = datetime.now()

            # Try to queue for batch processing
            if self.queue:
                try:
                    queue_msg = ClickQueueMessage.from_click_data(
                        short_code=short_code,
                        original_url=original_url,
                        clicked_at=clicked_at,
                        ip_address=ip_address,
                        user_agent=user_agent,
                        referrer=referrer
                    )
                    await self.queue.enqueue(queue_msg.to_dict())
                    logger.debug(
                        f"Click event queued: short_code={short_code} | "
                        f"referrer={referrer or 'direct'}"
                    )
                    return True  # Success - queued for async processing

                except Exception as e:
                    logger.error(
                        f"Click tracking queue FAILED: short_code={short_code} | "
                        f"error={str(e)}",
                        exc_info=True
                    )
                    # Fall through to sync write (graceful degradation)

            # Fallback: synchronous write (queue unavailable or failed)
            click_data = ClickData(
                short_code=short_code,
                original_url=original_url,
                clicked_at=clicked_at,
                ip_address=ip_address,
                user_agent=user_agent,
                referrer=referrer
            )

            # Batch create with single item (efficient)
            await self.click_repo.batch_create([click_data])

            logger.info(
                f"Click event saved (sync fallback): short_code={short_code} | "
                f"referrer={referrer or 'direct'}"
            )
            return True  # Success - saved synchronously

        except Exception as e:
            # FAIL-OPEN: Log error but don't crash redirect
            logger.error(
                f"Click tracking FAILED completely: short_code={short_code} | "
                f"error={str(e)}",
                exc_info=True
            )
            return False  # Failed - caller decides if this matters

    async def get_clicks_for_short_code(self, short_code: str, limit: int = 100) -> list[ClickData]:
        """
        Retrieve recent clicks for a short code.

        Args:
            short_code: The short code to query
            limit: Maximum number of clicks to return (default 100)

        Returns:
            List of ClickData instances, ordered by clicked_at DESC

        Raises:
            Exception: If database query fails
        """
        try:
            clicks = await self.click_repo.get_clicks_by_short_code(short_code, limit)

            logger.info(
                f"Retrieved clicks: short_code={short_code} | "
                f"count={len(clicks)} | limit={limit}"
            )

            return clicks

        except Exception as e:
            logger.error(
                f"Failed to retrieve clicks: short_code={short_code} | error={str(e)}",
                exc_info=True
            )
            raise

    async def get_click_count(self, short_code: str) -> int:
        """
        Get total click count for a short code.

        Args:
            short_code: The short code to query

        Returns:
            Total number of clicks

        Raises:
            Exception: If database query fails
        """
        try:
            count = await self.click_repo.get_click_count_for_short_code(short_code)

            logger.info(f"Click count: short_code={short_code} | count={count}")

            return count

        except Exception as e:
            logger.error(
                f"Failed to get click count: short_code={short_code} | error={str(e)}",
                exc_info=True
            )
            raise
