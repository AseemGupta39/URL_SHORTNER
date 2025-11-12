"""
Queue abstraction for async batch processing.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class Queue(ABC):
    """Abstract base class for queue implementations."""

    @abstractmethod
    async def connect(self):
        """Establish connection to queue backend."""
        pass

    @abstractmethod
    async def close(self):
        """Close connection to queue backend."""
        pass

    @abstractmethod
    async def enqueue(self, data: Dict[str, Any]) -> bool:
        """
        Add item to queue.

        Args:
            data: Dictionary to enqueue

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    async def dequeue(self, count: int = 1) -> List[Dict[str, Any]]:
        """
        Remove and return items from queue.

        Args:
            count: Number of items to dequeue

        Returns:
            List of dictionaries
        """
        pass

    @abstractmethod
    async def size(self) -> int:
        """Get number of items in queue."""
        pass

    @abstractmethod
    async def clear(self) -> bool:
        """Clear all items from queue."""
        pass
