"""
Application settings configuration.
"""
from pydantic_settings import BaseSettings


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
