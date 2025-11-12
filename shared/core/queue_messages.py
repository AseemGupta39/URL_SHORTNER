"""
Queue message schemas for batch processing.
"""
from datetime import datetime
from pydantic import BaseModel


class URLQueueMessage(BaseModel):
    """Message format for URL data in queue."""
    short_code: str
    original_url: str
    created_at: str  # ISO format timestamp

    @classmethod
    def from_url_data(cls, short_code: str, original_url: str, created_at: datetime):
        """Create queue message from URL data."""
        return cls(
            short_code=short_code,
            original_url=original_url,
            created_at=created_at.isoformat()
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for queue serialization."""
        return {
            "short_code": self.short_code,
            "original_url": self.original_url,
            "created_at": self.created_at
        }
