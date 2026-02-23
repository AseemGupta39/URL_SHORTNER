"""
Shorten Service specific settings.
This service creates short URLs with unique IDs.
Port: 8001
"""
from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator


class ShortenServiceSettings(BaseSettings):
    """Settings specific to Shorten Service."""

    # Database Configuration
    database_url: str = "sqlite+aiosqlite:///urls.db"
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = True
    db_echo_pool: bool = False

    # ID Generator Configuration (REQUIRED - generates unique IDs)
    datacenter_id: int = 0
    worker_id: int = 0
    epoch_sec: int = 1704067200

    # Bit Allocation
    timestamp_bits: int = 31
    datacenter_bits: int = 4
    worker_bits: int = 2
    sequence_bits: int = 10

    # Application Configuration (REQUIRED - builds short URLs)
    base_domain: str = "localhost:8002"
    base_url_scheme: str = "http"

    # Server Configuration (Port 8001)
    host: str = "0.0.0.0"
    port: int = 8001
    reload: bool = True

    # Concurrency limiter (semaphore) — limits requests in flight at once
    # 0 = unlimited. Tune per hardware: 50-100 for Docker/constrained, 500+ for bare metal
    max_concurrent_requests: int = 100

    # ID Buffer — pre-generates short codes off the hot path to eliminate lock contention
    # refill_threshold: background refill triggers when queue drops below this
    id_buffer_size: int = 4000
    id_buffer_refill_threshold: int = 2000

    # CORS Configuration
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"

    # Logging
    log_level: str = "DEBUG"

    # Cache Configuration (REQUIRED - caches created URLs)
    cache_max_size: int = 1000
    cache_ttl_seconds: int = 3600

    # Redis Configuration (for cache + queue)
    redis_url: str = ""
    redis_enabled: bool = False
    redis_pool_max_connections: int = 50
    redis_socket_timeout: int = 5
    redis_socket_connect_timeout: int = 5

    # Queue Configuration (REQUIRED - enqueues URLs for batch insert)
    batch_size: int = 100
    batch_interval_seconds: int = 10
    enable_background_scheduler: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global singleton instance
settings = ShortenServiceSettings()


def get_settings() -> ShortenServiceSettings:
    """Get the shorten service settings instance."""
    return settings
