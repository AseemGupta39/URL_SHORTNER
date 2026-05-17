"""
Queue Interface

Abstract base class for queue implementations.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class Queue(ABC):
    """Abstract base class for queue implementations."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to queue backend."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close connection to queue backend."""
        pass

    @abstractmethod
    async def enqueue(self, data: Dict[str, Any]) -> None:
        """
        Add item to queue. Raises on failure.

        Args:
            data: Dictionary to enqueue
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
    async def clear(self) -> None:
        """Clear all items from queue. Raises on failure."""
        pass

    @abstractmethod
    async def peek(self, count: int = 1) -> List[Dict[str, Any]]:
        """
        Peek at items without removing them from queue.

        Args:
            count: Number of items to peek at

        Returns:
            List of dictionaries (items remain in queue)
        """
        pass

    @abstractmethod
    async def remove_first(self, count: int) -> None:
        """
        Remove first N items from queue. Raises on failure.

        Args:
            count: Number of items to remove from front
        """
        pass
