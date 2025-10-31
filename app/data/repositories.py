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
from app.utils.cache import Cache

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

    def __init__(self, db_url: str = "sqlite+aiosqlite:///urls.db", cache: Optional[Cache] = None):
        """
        Initialize repository with database URL and optional cache.

        Args:
            db_url: Database connection URL
                    - SQLite: "sqlite+aiosqlite:///urls.db"
                    - PostgreSQL: "postgresql+asyncpg://user:pass@host:port/dbname"
            cache: Optional cache implementation for faster lookups
        """
        self.db_url = db_url
        self.cache = cache  # Cache for read-heavy workloads
        self.engine = None
        self.async_session = None

    async def initialize(self) -> None:
        """
        Initialize database engine and create tables if needed.

        Creates:
        - urls table with schema matching URLData
        - Index on created_at for time-based queries
        """
        logger.info(f"Initializing database connection: {self.db_url}")

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
        Store URL mapping in database and warm the cache.

        **Cache Warming Strategy:**
        After saving to database, immediately add to cache.
        This is beneficial because:
        1. Newly created URLs are often accessed immediately (user testing)
        2. Avoids cold cache on first access
        3. No performance penalty (already in memory)

        Args:
            url_data: URLData instance to store

        Returns:
            The stored URLData instance

        Raises:
            sqlalchemy.exc.IntegrityError: If short_code already exists
        """
        if not self.async_session:
            raise RuntimeError("Database not initialized. Call initialize() first.")

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

        # Cache Warming: Pre-populate cache with newly created URL
        # This ensures the first access is fast (no cold cache)
        if self.cache:
            self.cache.set(url_data.short_code, url_data)
            logger.debug(f"Cache warmed with new short code: {url_data.short_code}")

        return url_data

    async def get_by_short_code(self, short_code: str) -> Optional[URLData]:
        """
        Retrieve URL data by short code with cache support.

        **Caching Strategy (Cache-Aside/Lazy Loading Pattern):**
        1. Check cache first (fast: ~0.1ms)
        2. If cache HIT: Return immediately (99% of requests after warming)
        3. If cache MISS: Query database (slower: ~10-50ms)
        4. Store database result in cache for next time

        This pattern is ideal for read-heavy workloads like URL shorteners
        where the same URLs are accessed repeatedly.

        Args:
            short_code: The short code to look up

        Returns:
            URLData if found, None otherwise
        """
        if not self.async_session:
            raise RuntimeError("Database not initialized. Call initialize() first.")

        # Step 1: Try cache first (if enabled)
        if self.cache:
            cached_data = self.cache.get(short_code)
            if cached_data is not None:
                logger.debug(f"Cache HIT for short code: {short_code}")
                return cached_data
            logger.debug(f"Cache MISS for short code: {short_code}, querying database")

        # Step 2: Cache miss or no cache - query database
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

            # Step 3: Store in cache for future lookups (lazy loading)
            if self.cache:
                self.cache.set(short_code, url_data)
                logger.debug(f"Stored in cache: {short_code}")

            return url_data

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
