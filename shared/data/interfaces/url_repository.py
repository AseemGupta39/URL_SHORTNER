"""
Abstract interface for URL repository.
"""
from abc import ABC, abstractmethod
from typing import Optional, List

from shared.core.schemas import URLData


class URLRepository(ABC):
    """Abstract base class for URL data storage."""

    @abstractmethod
    async def create(self, url_data: URLData) -> URLData:
        """Store URL mapping, return created entity."""
        pass

    @abstractmethod
    async def batch_create(self, url_data_list: List[URLData]) -> int:
        """
        Store multiple URL mappings in a single transaction.

        Args:
            url_data_list: List of URLData instances to store

        Returns:
            Number of successfully inserted records
        """
        pass

    @abstractmethod
    async def get_by_short_code(self, short_code: str) -> Optional[URLData]:
        """Retrieve URL data by short code, return None if not found."""
        pass

    @abstractmethod
    async def exists(self, short_code: str) -> bool:
        """Check if short code already exists."""
        pass
