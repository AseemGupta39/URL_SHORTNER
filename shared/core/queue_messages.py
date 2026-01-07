"""
Queue message schemas for batch processing.
"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Any


class URLQueueMessage(BaseModel):
    """Message format for URL data in queue."""
    short_code: str
    original_url: str
    created_at: str  # ISO format timestamp
    request_id: str  # Required for end-to-end traceability (auto-captured from context)

    @classmethod
    def from_url_data(cls, short_code: str, original_url: str, created_at: datetime) -> "URLQueueMessage":
        """
        Create queue message from URL data.

        Automatically captures request_id from context for end-to-end traceability.
        The request_id survives in the queue and can be restored by batch workers.
        """
        from shared.utils import request_context

        return cls(
            short_code=short_code,
            original_url=original_url,
            created_at=created_at.isoformat(),
            request_id=request_context.get_request_id()
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for queue serialization."""
        return {
            "short_code": self.short_code,
            "original_url": self.original_url,
            "created_at": self.created_at,
            "request_id": self.request_id
        }


class ClickQueueMessage(BaseModel):
    """Message format for click analytics data in queue."""
    short_code: str
    original_url: str
    clicked_at: str  # ISO format timestamp
    ip_address: str
    user_agent: str
    referrer: Optional[str] = None
    request_id: str  # Required for end-to-end traceability (auto-captured from context)

    @classmethod
    def from_click_data(
        cls,
        short_code: str,
        original_url: str,
        clicked_at: datetime,
        ip_address: str,
        user_agent: str,
        referrer: Optional[str] = None
    ):
        """
        Create queue message from click data.

        Automatically captures request_id from context for end-to-end traceability.
        The request_id survives in the queue and can be restored by batch workers.
        """
        from shared.utils import request_context

        return cls(
            short_code=short_code,
            original_url=original_url,
            clicked_at=clicked_at.isoformat(),
            ip_address=ip_address,
            user_agent=user_agent,
            referrer=referrer,
            request_id=request_context.get_request_id()
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for queue serialization."""
        return {
            "short_code": self.short_code,
            "original_url": self.original_url,
            "clicked_at": self.clicked_at,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "referrer": self.referrer,
            "request_id": self.request_id
        }


class DeadLetterQueueMessage(BaseModel):
    """Message format for dead-letter queue (failed/unparseable messages)."""
    original_message: dict[str, Any]  # The original failed message
    error: str  # Error message
    error_type: str  # Exception type (e.g., "ValidationError")
    failed_at: str  # ISO format timestamp when parsing failed
    batch_id: str  # Batch ID where failure occurred
    request_id: str  # Original request ID from the message

    @classmethod
    def from_failed_parse(
        cls,
        original_message: dict[str, Any],
        exception: Exception,
        batch_id: str
    ):
        """
        Create DLQ message from a failed parse attempt.

        Args:
            original_message: The raw message that failed to parse
            exception: The exception that was raised
            batch_id: The batch ID where the failure occurred
        """
        return cls(
            original_message=original_message,
            error=str(exception),
            error_type=type(exception).__name__,
            failed_at=datetime.utcnow().isoformat(),
            batch_id=batch_id,
            request_id=original_message.get('request_id', 'unknown')
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for queue serialization."""
        return {
            "original_message": self.original_message,
            "error": self.error,
            "error_type": self.error_type,
            "failed_at": self.failed_at,
            "batch_id": self.batch_id,
            "request_id": self.request_id
        }
