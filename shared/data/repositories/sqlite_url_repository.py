"""
SQLite/PostgreSQL repository implementation for URL storage using SQLAlchemy ORM.
"""
from typing import Optional, List
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from shared.data.interfaces.url_repository import URLRepository
from shared.data.models import URLModel, Base
from shared.core.schemas import URLData

logger = logging.getLogger(__name__)


class SQLiteURLRepository(URLRepository):
    """
    SQLite/PostgreSQL implementation of URL repository using SQLAlchemy ORM.

    Provides async URL storage with:
    - Database-agnostic ORM (SQLite, PostgreSQL, MySQL)
    - Automatic database and table initialization
    - Connection pooling for high-performance production use
    - Primary key on short_code for fast lookups
    - Index on created_at for time-based queries
    """

    def __init__(
        self,
        db_url: str = "sqlite+aiosqlite:///urls.db",
        pool_size: int = 10,
        max_overflow: int = 5,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        echo_pool: bool = False
    ):
        """
        Initialize repository with database URL and connection pooling.

        Args:
            db_url: Database connection URL
                    - SQLite: "sqlite+aiosqlite:///urls.db"
                    - PostgreSQL: "postgresql+asyncpg://user:pass@host:port/dbname"
            pool_size: Max connections in pool (default 10, lower for serverless)
            max_overflow: Additional connections beyond pool_size (default 5)
            pool_timeout: Seconds to wait for connection (default 30)
            pool_recycle: Recycle connections after N seconds (default 3600)
            pool_pre_ping: Test connection health before using (default True)
            echo_pool: Log pool events for debugging (default False)
        """
        self.db_url = db_url
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.pool_pre_ping = pool_pre_ping
        self.echo_pool = echo_pool
        self.engine = None
        self.async_session = None

    async def initialize(self) -> None:
        """
        Initialize database engine with connection pooling and create tables if needed.

        Uses lazy initialization - only connects when needed.
        Safe to call multiple times - will only initialize once.

        Connection Pooling:
        - SQLite: No pooling (not supported by SQLite)
        - PostgreSQL: Full pooling support (for production with PgBouncer)
        - Reduces connection overhead in serverless environments

        Creates:
        - urls table with schema matching URLData
        - Index on created_at for time-based queries
        """
        if self.engine is not None:
            return  # Already initialized

        logger.debug("Initializing database connection")

        # Check if we're using SQLite or PostgreSQL
        is_sqlite = self.db_url.startswith("sqlite")

        if is_sqlite:
            # SQLite: No connection pooling (not supported)
            self.engine = create_async_engine(
                self.db_url,
                echo=False,
                future=True
            )
            logger.debug("Database: SQLite (development, no pooling)")
        else:
            # PostgreSQL: Enable connection pooling for production
            self.engine = create_async_engine(
                self.db_url,
                echo=False,
                echo_pool=self.echo_pool,
                future=True,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                pool_recycle=self.pool_recycle,
                pool_pre_ping=self.pool_pre_ping,
            )
            logger.info(
                f"Database: PostgreSQL with connection pooling "
                f"(pool_size={self.pool_size}, max_overflow={self.max_overflow}, "
                f"timeout={self.pool_timeout}s, recycle={self.pool_recycle}s)"
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

    async def batch_create(self, url_data_list: List[URLData]) -> int:
        """
        Store multiple URL mappings in a single transaction.

        Args:
            url_data_list: List of URLData instances to store

        Returns:
            Number of successfully inserted records
        """
        if not url_data_list:
            return 0

        await self.initialize()

        logger.debug(f"Batch inserting {len(url_data_list)} URL mappings")

        async with self.async_session() as session:
            url_models = [
                URLModel(
                    short_code=url_data.short_code,
                    original_url=url_data.original_url,
                    created_at=url_data.created_at
                )
                for url_data in url_data_list
            ]
            session.add_all(url_models)
            await session.commit()

        logger.info(f"Batch insert completed: {len(url_data_list)} URL mappings saved")

        return len(url_data_list)

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
