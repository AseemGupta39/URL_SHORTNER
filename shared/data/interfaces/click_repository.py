"""
Abstract interface for Click Analytics repository.
"""
from abc import ABC, abstractmethod
from typing import List

from shared.core.schemas import ClickData


class ClickRepository(ABC):
    """Abstract base class for click analytics data storage."""

    @abstractmethod
    async def batch_create(self, click_data_list: List[ClickData]) -> int:
        """
        Store click events in a single transaction.

        Args:
            click_data_list: List of ClickData instances to store (can be single item)

        Returns:
            Number of successfully inserted records
        """
        pass

    @abstractmethod
    async def get_clicks_by_short_code(self, short_code: str, limit: int = 100) -> List[ClickData]:
        """
        Retrieve recent clicks for a short code.

        Args:
            short_code: The short code to query
            limit: Maximum number of clicks to return

        Returns:
            List of ClickData instances, ordered by clicked_at DESC
        """
        pass

    @abstractmethod
    async def get_click_count_for_short_code(self, short_code: str) -> int:
        """
        Get total click count for a short code.

        Args:
            short_code: The short code to query

        Returns:
            Total number of clicks
        """
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close database connection."""
        pass
