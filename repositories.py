"""
Repository implementations for URL storage using SQLAlchemy ORM.
"""
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Index, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from schemas import URLData


Base = declarative_base()


class URLModel(Base):
    """SQLAlchemy model for URL mappings."""

    __tablename__ = "urls"

    short_code = Column(String(7), primary_key=True)
    original_url = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)

    __table_args__ = (
        Index('idx_created_at', 'created_at'),
    )


class URLRepository(ABC):
    """Abstract base class for URL data storage."""

    @abstractmethod
    async def create(self, url_data: URLData) -> URLData:
        """Store URL mapping, return created entity."""
        pass

    @abstractmethod
    async def get_by_short_code(self, short_code: str) -> Optional[URLData]:
        """Retrieve URL data by short code, return None if not found."""
        pass

    @abstractmethod
    async def exists(self, short_code: str) -> bool:
        """Check if short code already exists."""
        pass


class SQLiteURLRepository(URLRepository):
    """
    SQLite implementation of URL repository using SQLAlchemy ORM.

    Provides async URL storage with:
    - Database-agnostic ORM (easy to switch to PostgreSQL/MySQL)
    - Automatic database and table initialization
    - Primary key on short_code for fast lookups
    - Index on created_at for time-based queries
    """

    def __init__(self, db_path: str = "urls.db"):
        """
        Initialize repository with database path.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_url = f"sqlite+aiosqlite:///{db_path}"
        self.engine = None
        self.async_session = None

    async def initialize(self) -> None:
        """
        Initialize database engine and create tables if needed.

        Creates:
        - urls table with schema matching URLData
        - Index on created_at for time-based queries
        """
        self.engine = create_async_engine(
            self.db_url,
            echo=False,
            future=True
        )

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def close(self) -> None:
        """Close database connection."""
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.async_session = None

    async def create(self, url_data: URLData) -> URLData:
        """
        Store URL mapping in database.

        Args:
            url_data: URLData instance to store

        Returns:
            The stored URLData instance

        Raises:
            sqlalchemy.exc.IntegrityError: If short_code already exists
        """
        if not self.async_session:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        async with self.async_session() as session:
            url_model = URLModel(
                short_code=url_data.short_code,
                original_url=url_data.original_url,
                created_at=url_data.created_at
            )
            session.add(url_model)
            await session.commit()

        return url_data

    async def get_by_short_code(self, short_code: str) -> Optional[URLData]:
        """
        Retrieve URL data by short code.

        Args:
            short_code: The short code to look up

        Returns:
            URLData if found, None otherwise
        """
        if not self.async_session:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        async with self.async_session() as session:
            stmt = select(URLModel).where(URLModel.short_code == short_code)
            result = await session.execute(stmt)
            url_model = result.scalar_one_or_none()

            if url_model is None:
                return None

            return URLData(
                short_code=url_model.short_code,
                original_url=url_model.original_url,
                created_at=url_model.created_at
            )

    async def exists(self, short_code: str) -> bool:
        """
        Check if short code exists in database.

        Args:
            short_code: The short code to check

        Returns:
            True if exists, False otherwise
        """
        if not self.async_session:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        async with self.async_session() as session:
            stmt = select(URLModel.short_code).where(URLModel.short_code == short_code)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
