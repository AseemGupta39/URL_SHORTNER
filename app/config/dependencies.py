"""
Dependency injection factories for FastAPI.
"""
from fastapi import Depends

from app.config.settings import settings
from app.utils.id_generator import IDGenerator, SnowflakeIDGenerator
from app.data.repositories import URLRepository, SQLiteURLRepository
from app.core.services import URLService


async def get_id_generator() -> IDGenerator:
    """
    Dependency injection factory for ID generator.

    Returns:
        SnowflakeIDGenerator configured from settings
    """
    return SnowflakeIDGenerator(
        datacenter_id=settings.datacenter_id,
        worker_id=settings.worker_id,
        epoch_sec=settings.epoch_sec,
        timestamp_bits=settings.timestamp_bits,
        datacenter_bits=settings.datacenter_bits,
        worker_bits=settings.worker_bits,
        sequence_bits=settings.sequence_bits
    )


async def get_url_repository() -> URLRepository:
    """
    Dependency injection factory for URL repository.

    Returns:
        SQLiteURLRepository configured from settings
    """
    repo = SQLiteURLRepository(db_path=settings.database_path)
    await repo.initialize()
    return repo


async def get_url_service(
    url_repo: URLRepository = Depends(get_url_repository),
    id_generator: IDGenerator = Depends(get_id_generator)
) -> URLService:
    """
    Dependency injection factory for URL service.

    Returns:
        URLService with injected dependencies
    """
    return URLService(
        url_repo=url_repo,
        id_generator=id_generator,
        base_domain=settings.base_domain,
        base_url_scheme=settings.base_url_scheme
    )
