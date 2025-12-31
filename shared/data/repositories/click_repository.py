"""
SQLite/PostgreSQL repository implementation for click analytics storage using SQLAlchemy ORM.
"""
from typing import List
from datetime import datetime
import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from shared.data.interfaces.click_repository import ClickRepository
from shared.data.models import ClickModel, Base
from shared.core.schemas import ClickData

logger = logging.getLogger(__name__)


class SQLiteClickRepository(ClickRepository):
    """
    SQLite/PostgreSQL implementation of click analytics repository using SQLAlchemy ORM.

    Provides async click storage with:
    - Database-agnostic ORM (SQLite, PostgreSQL, MySQL)
    - Automatic database and table initialization
    - Connection pooling for high-performance production use
    - Index on short_code and clicked_at for fast analytics queries
    - Composite index for time-series queries
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
        """
        if self.engine is not None:
            return  # Already initialized

        logger.debug("Initializing click analytics database connection")

        # Check if we're using SQLite or PostgreSQL
        is_sqlite = self.db_url.startswith("sqlite")

        if is_sqlite:
            # SQLite: No connection pooling (not supported)
            self.engine = create_async_engine(
                self.db_url,
                echo=False,
                future=True
            )
            logger.debug("Click analytics database: SQLite (development, no pooling)")
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
                f"Click analytics database: PostgreSQL with connection pooling "
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

        logger.info("Click analytics database initialized successfully")

    async def close(self) -> None:
        """Close database connection."""
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.async_session = None
            logger.debug("Click analytics database connection closed")

    async def batch_create(self, click_data_list: List[ClickData]) -> int:
        """
        Store click events in a single transaction.

        Args:
            click_data_list: List of ClickData instances to store (can be single item)

        Returns:
            Number of successfully inserted records
        """
        if not click_data_list:
            return 0

        await self.initialize()

        logger.debug(f"Batch inserting {len(click_data_list)} click events")

        async with self.async_session() as session:
            click_models = [
                ClickModel(
                    short_code=click_data.short_code,
                    original_url=click_data.original_url,
                    clicked_at=click_data.clicked_at,
                    ip_address=click_data.ip_address,
                    user_agent=click_data.user_agent,
                    referrer=click_data.referrer,
                    created_at=datetime.utcnow()
                )
                for click_data in click_data_list
            ]
            session.add_all(click_models)
            await session.commit()

        logger.info(f"Batch insert completed: {len(click_data_list)} click events saved")

        return len(click_data_list)

    async def get_clicks_by_short_code(self, short_code: str, limit: int = 100) -> List[ClickData]:
        """
        Retrieve recent clicks for a short code.

        Args:
            short_code: The short code to query
            limit: Maximum number of clicks to return

        Returns:
            List of ClickData instances, ordered by clicked_at DESC
        """
        await self.initialize()

        logger.debug(f"Querying clicks for short_code={short_code}, limit={limit}")

        async with self.async_session() as session:
            stmt = (
                select(ClickModel)
                .where(ClickModel.short_code == short_code)
                .order_by(ClickModel.clicked_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            click_models = result.scalars().all()

            click_data_list = [
                ClickData(
                    short_code=click.short_code,
                    original_url=click.original_url,
                    clicked_at=click.clicked_at,
                    ip_address=click.ip_address,
                    user_agent=click.user_agent,
                    referrer=click.referrer
                )
                for click in click_models
            ]

            logger.info(f"Retrieved {len(click_data_list)} clicks for short_code={short_code}")

            return click_data_list

    async def get_click_count_for_short_code(self, short_code: str) -> int:
        """
        Get total click count for a short code.

        Args:
            short_code: The short code to query

        Returns:
            Total number of clicks
        """
        await self.initialize()

        logger.debug(f"Counting clicks for short_code={short_code}")

        async with self.async_session() as session:
            stmt = (
                select(func.count())
                .select_from(ClickModel)
                .where(ClickModel.short_code == short_code)
            )
            result = await session.execute(stmt)
            count = result.scalar_one()

            logger.info(f"Click count for short_code={short_code}: {count}")

            return count
