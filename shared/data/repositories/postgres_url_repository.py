"""
PostgreSQL repository implementation for URL storage using SQLAlchemy ORM.
"""

from typing import Optional, List
import logging

from sqlalchemy import select
from sqlalchemy.orm import class_mapper
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.data.interfaces.url_repository import URLRepository
from shared.data.models import URLModel, Base
from shared.core.schemas import URLData
from shared.utils.timer import Timer

logger = logging.getLogger(__name__)


class PostgresURLRepository(URLRepository):
    """
    PostgreSQL implementation of URL repository using SQLAlchemy ORM.

    Provides async URL storage with:
    - Connection pooling for high-performance production use
    - Idempotent batch inserts via ON CONFLICT DO NOTHING
    - Primary key on short_code for fast lookups
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

        timer = Timer()
        logger.debug("Initializing PostgreSQL connection", extra={"pool_size": self.pool_size, "max_overflow": self.max_overflow})

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
            "PostgreSQL initialized successfully",
            extra={
                "connect_time_ms": round(timer.total(), 2),
                "pool_size": self.pool_size,
                "max_overflow": self.max_overflow,
            },
        )

    async def close(self) -> None:
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.async_session = None

    async def create(self, url_data: URLData) -> URLData:
        await self.initialize()

        logger.debug(
            "Inserting URL mapping",
            extra={"short_code": url_data.short_code, "original_url": url_data.original_url},
        )

        async with self.async_session() as session:
            url_model = URLModel(
                short_code=url_data.short_code,
                original_url=url_data.original_url,
                created_at=url_data.created_at,
            )
            session.add(url_model)
            await session.commit()

        logger.info(
            "URL mapping saved to database",
            extra={"short_code": url_data.short_code, "original_url": url_data.original_url},
        )

        return url_data

    async def batch_create(self, url_data_list: List[URLData]) -> int:
        """
        Insert multiple URL mappings in a single statement.

        Uses ON CONFLICT DO NOTHING so reprocessed batches (crash recovery)
        silently skip already-existing rows instead of raising IntegrityError.
        Returns the number of rows actually inserted — 0 on a full reprocess is correct.
        """
        if not url_data_list:
            return 0

        await self.initialize()

        logger.debug("Batch inserting URL mappings", extra={"count": len(url_data_list)})

        url_models = [
            URLModel(
                short_code=url_data.short_code,
                original_url=url_data.original_url,
                created_at=url_data.created_at,
            )
            for url_data in url_data_list
        ]

        values = [
            {col.key: getattr(m, col.key) for col in class_mapper(URLModel).columns}
            for m in url_models
        ]

        stmt = pg_insert(URLModel).values(values).on_conflict_do_nothing()

        async with self.async_session() as session:
            result = await session.execute(stmt)
            await session.commit()

        inserted_count = result.rowcount
        logger.info("Batch insert completed", extra={"inserted": inserted_count, "sent": len(url_data_list)})

        return inserted_count

    async def get_by_short_code(self, short_code: str) -> Optional[URLData]:
        await self.initialize()

        logger.debug("Looking up short code in database", extra={"short_code": short_code})

        async with self.async_session() as session:
            stmt = select(URLModel).where(URLModel.short_code == short_code)
            result = await session.execute(stmt)
            url_model = result.scalar_one_or_none()

            if url_model is None:
                logger.debug("Short code not found in database", extra={"short_code": short_code})
                return None

            logger.info(
                "URL mapping found in database",
                extra={"short_code": short_code, "original_url": url_model.original_url},
            )

            return URLData(
                short_code=url_model.short_code,
                original_url=url_model.original_url,
                created_at=url_model.created_at,
            )

    async def exists(self, short_code: str) -> bool:
        await self.initialize()

        async with self.async_session() as session:
            stmt = select(URLModel.short_code).where(URLModel.short_code == short_code)
            result = await session.execute(stmt)
            return result.scalar_one_or_none() is not None

    def get_pool_status(self) -> dict:
        if self.engine is None:
            return {"status": "not_initialized"}

        pool = self.engine.pool
        if pool is None:
            return {"status": "no_pool"}

        return {
            "size": pool.size(),
            "checked_in": pool.checkedin(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "max_overflow": self.max_overflow,
            "pool_size": self.pool_size,
            "status": "active",
        }