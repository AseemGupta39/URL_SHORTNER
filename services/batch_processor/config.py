"""
Batch Processor Service specific settings.
This service processes queued URLs and inserts them into database in batches.
Port: 8003
"""
from pydantic_settings import BaseSettings


class BatchProcessorServiceSettings(BaseSettings):
    """Settings specific to Batch Processor Service."""

    # Database Configuration
    database_url: str = "sqlite+aiosqlite:///urls.db"
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = True
    db_echo_pool: bool = False

    # Server Configuration (Port 8003)
    host: str = "0.0.0.0"
    port: int = 8003
    reload: bool = True

    # CORS Configuration
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"

    # Logging
    log_level: str = "DEBUG"

    # Redis Configuration (for queue only - no cache needed)
    redis_url: str = ""
    redis_enabled: bool = False
    redis_pool_max_connections: int = 50
    redis_socket_timeout: int = 5
    redis_socket_connect_timeout: int = 5

    # Queue Configuration (REQUIRED - processes queued URLs)
    batch_size: int = 100
    batch_interval_seconds: int = 10
    enable_background_scheduler: bool = True  # True for local dev, False for production (use cron)

    # Click Analytics Configuration
    click_batch_interval_seconds: int = 5  # Process clicks more frequently than URLs

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global singleton instance
settings = BatchProcessorServiceSettings()


def get_settings() -> BatchProcessorServiceSettings:
    """Get the batch processor service settings instance."""
    return settings
