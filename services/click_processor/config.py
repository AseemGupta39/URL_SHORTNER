"""
Click Processor Service specific settings.
This service processes queued click analytics and inserts them into database in batches.
Port: 8004
"""
from pydantic_settings import BaseSettings


class ClickProcessorServiceSettings(BaseSettings):
    """Settings specific to Click Processor Service."""

    # Database Configuration
    database_url: str = "sqlite+aiosqlite:///urls.db"
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = True
    db_echo_pool: bool = False

    # Server Configuration (Port 8004)
    host: str = "0.0.0.0"
    port: int = 8004
    reload: bool = True

    # CORS Configuration
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"

    # Logging
    log_level: str = "DEBUG"

    # Redis Configuration (for queue)
    redis_url: str = ""
    redis_pool_max_connections: int = 50
    redis_queue_socket_timeout: int = 3
    redis_queue_connect_timeout: int = 2

    # Queue Configuration
    batch_size: int = 100
    click_batch_interval_seconds: int = 5  # Process clicks frequently
    enable_background_scheduler: bool = True  # True for local dev, False for production (use cron)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global singleton instance
settings = ClickProcessorServiceSettings()


def get_settings() -> ClickProcessorServiceSettings:
    """Get the click processor service settings instance."""
    return settings
