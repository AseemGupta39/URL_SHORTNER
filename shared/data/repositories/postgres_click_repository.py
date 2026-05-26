"""
PostgreSQL repository implementation for click analytics storage using SQLAlchemy ORM.
"""
from typing import List
from datetime import datetime
import logging

from sqlalchemy import select, func
from sqlalchemy.orm import class_mapper
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.data.interfaces.click_repository import ClickRepository
from shared.data.models import ClickModel, Base
from shared.core.schemas import ClickData

logger = logging.getLogger(__name__)


class PostgresClickRepository(ClickRepository):
    """
    PostgreSQL implementation of click analytics repository using SQLAlchemy ORM.

    Provides async click storage with:
    - Connection pooling for high-performance production use
    - Index on short_code and clicked_at for fast analytics queries
    - Composite index for time-series queries
    """

    def __init__(
        self,
        db_url: str,
        pool_size: int = 10,
        max_overflow: int = 5,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        pool_pre_ping: bool = True,
        echo_pool: bool = False,
    ):
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
        if self.engine is not None:
            return

        logger.debug("Initializing click analytics PostgreSQL connection")

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

        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        logger.info(
            "Click analytics PostgreSQL initialized successfully",
            extra={
                "pool_size": self.pool_size,
                "max_overflow": self.max_overflow,
            },
        )

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.async_session = None
            logger.debug("Click analytics database connection closed")

    async def batch_create(self, click_data_list: List[ClickData]) -> int:
        """
        Insert multiple click events in a single statement.

        Uses ON CONFLICT (id) DO NOTHING so reprocessed batches (crash recovery)
        silently skip already-existing rows. The id (click_id) is producer-supplied
        and stable across reprocesses, so a duplicate batch becomes a no-op.
        Returns the number of rows actually inserted — 0 on a full reprocess is correct.
        """
        if not click_data_list:
            return 0

        await self.initialize()

        logger.debug("Batch inserting click events", extra={"count": len(click_data_list)})

        now = datetime.utcnow()
        click_models = [
            ClickModel(
                id=click_data.click_id,
                short_code=click_data.short_code,
                original_url=click_data.original_url,
                clicked_at=click_data.clicked_at,
                ip_address=click_data.ip_address,
                user_agent=click_data.user_agent,
                referrer=click_data.referrer,
                created_at=now,
            )
            for click_data in click_data_list
        ]

        values = [
            {col.key: getattr(m, col.key) for col in class_mapper(ClickModel).columns}
            for m in click_models
        ]

        stmt = pg_insert(ClickModel).values(values).on_conflict_do_nothing()

        async with self.async_session() as session:
            result = await session.execute(stmt)
            await session.commit()

        inserted_count = result.rowcount
        logger.info("Batch insert completed", extra={"inserted": inserted_count, "sent": len(click_data_list)})

        return inserted_count

    async def get_clicks_by_short_code(self, short_code: str, limit: int = 100) -> List[ClickData]:
        await self.initialize()

        logger.debug("Querying clicks", extra={"short_code": short_code, "limit": limit})

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
                    referrer=click.referrer,
                )
                for click in click_models
            ]

            logger.info("Clicks retrieved", extra={"short_code": short_code, "count": len(click_data_list)})

            return click_data_list

    async def get_click_count_for_short_code(self, short_code: str) -> int:
        await self.initialize()

        logger.debug("Counting clicks", extra={"short_code": short_code})

        async with self.async_session() as session:
            stmt = (
                select(func.count())
                .select_from(ClickModel)
                .where(ClickModel.short_code == short_code)
            )
            result = await session.execute(stmt)
            count = result.scalar_one()

            logger.info("Click count retrieved", extra={"short_code": short_code, "count": count})

            return count
