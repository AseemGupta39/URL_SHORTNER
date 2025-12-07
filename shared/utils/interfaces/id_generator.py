"""
ID Generator Interface

Abstract base class for distributed ID generation.
"""
from abc import ABC, abstractmethod


class IDGenerator(ABC):
    """Abstract base class for distributed ID generation"""

    @abstractmethod
    async def generate_id(self) -> int:
        """Generate unique numeric ID across workers"""
        pass

    @abstractmethod
    async def generate_short_code(self) -> str:
        """
        Generate unique short code (base62 encoded).

        Convenience method that generates ID and encodes it.
        Primary method for service layer usage.
        """
        pass
