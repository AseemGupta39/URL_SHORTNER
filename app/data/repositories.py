"""
Repository implementations for URL storage using SQLAlchemy ORM.
"""
from abc import ABC, abstractmethod
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.data.models import URLModel, Base
from app.core.schemas import URLData
from app.utils.logger import get_logger

logger = get_logger()


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

    def __init__(self, db_url: str = "sqlite+aiosqlite:///urls.db"):
        """
        Initialize repository with database URL.

        Args:
            db_url: Database connection URL
                    - SQLite: "sqlite+aiosqlite:///urls.db"
                    - PostgreSQL: "postgresql+asyncpg://user:pass@host:port/dbname"
        """
        self.db_url = db_url
        self.engine = None
        self.async_session = None

    async def initialize(self) -> None:
        """
        Initialize database engine and create tables if needed.

        Uses lazy initialization - only connects when needed.
        Safe to call multiple times - will only initialize once.

        Creates:
        - urls table with schema matching URLData
        - Index on created_at for time-based queries
        """
        if self.engine is not None:
            return  # Already initialized

        logger.debug("Initializing database connection")

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

        logger.info("Database initialized successfully")

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
        await self.initialize()

        logger.debug(f"Inserting URL mapping: {url_data.short_code} -> {url_data.original_url}")

        async with self.async_session() as session:
            url_model = URLModel(
                short_code=url_data.short_code,
                original_url=url_data.original_url,
                created_at=url_data.created_at
            )
            session.add(url_model)
            await session.commit()

        logger.info(f"URL mapping saved to database: {url_data.short_code} -> {url_data.original_url}")

        return url_data

    async def get_by_short_code(self, short_code: str) -> Optional[URLData]:
        """
        Retrieve URL data by short code.

        Args:
            short_code: The short code to look up

        Returns:
            URLData if found, None otherwise
        """
        await self.initialize()

        logger.debug(f"Looking up short code in database: {short_code}")

        async with self.async_session() as session:
            stmt = select(URLModel).where(URLModel.short_code == short_code)
            result = await session.execute(stmt)
            url_model = result.scalar_one_or_none()

            if url_model is None:
                logger.debug(f"Short code not found in database: {short_code}")
                return None

            logger.info(f"URL mapping found in database: {short_code} -> {url_model.original_url}")
            url_data = URLData(
                short_code=url_model.short_code,
                original_url=url_model.original_url,
                created_at=url_model.created_at
            )

            return url_data

    async def exists(self, short_code: str) -> bool:
        """
        Check if short code exists in database.

        Args:
            short_code: The short code to check

        Returns:
            True if exists, False otherwise
        """
        await self.initialize()

        async with self.async_session() as session:
            stmt = select(URLModel.short_code).where(URLModel.short_code == short_code)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None
