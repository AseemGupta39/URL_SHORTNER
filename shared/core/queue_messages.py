"""
Queue message schemas for batch processing.
"""
from datetime import datetime
from pydantic import BaseModel
from typing import Optional


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


class ClickQueueMessage(BaseModel):
    """Message format for click analytics data in queue."""
    short_code: str
    original_url: str
    clicked_at: str  # ISO format timestamp
    ip_address: str
    user_agent: str
    referrer: Optional[str] = None

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
        """Create queue message from click data."""
        return cls(
            short_code=short_code,
            original_url=original_url,
            clicked_at=clicked_at.isoformat(),
            ip_address=ip_address,
            user_agent=user_agent,
            referrer=referrer
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for queue serialization."""
        return {
            "short_code": self.short_code,
            "original_url": self.original_url,
            "clicked_at": self.clicked_at,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "referrer": self.referrer
        }
