"""
Dependency injection configuration and settings management.
"""
from pydantic_settings import BaseSettings
from fastapi import Depends

from id_generation import IDGenerator, SnowflakeIDGenerator
from repositories import URLRepository, SQLiteURLRepository
from services import URLService


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    database_path: str = "urls.db"

    # ID Generator Configuration
    datacenter_id: int = 0
    worker_id: int = 0
    epoch_sec: int = 1704067200  # 2024-01-01 00:00:00 UTC

    # Bit Allocation (41 bits total for 7 characters)
    timestamp_bits: int = 28   # 8.51 years
    datacenter_bits: int = 4   # 16 datacenters
    worker_bits: int = 2       # 4 workers per DC
    sequence_bits: int = 7     # 128 IDs/second per worker

    # Application
    base_domain: str = "short.ly"
    base_url_scheme: str = "https"  # http or https

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()


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
