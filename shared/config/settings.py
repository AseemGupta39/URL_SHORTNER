"""
Application settings configuration.
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database
    # For SQLite (development): "urls.db"
    # For PostgreSQL (production): Set DATABASE_URL environment variable
    database_url: str = "sqlite+aiosqlite:///urls.db"  # Default to SQLite

    # Connection Pooling (for PostgreSQL + PgBouncer)
    db_pool_size: int = 10  # Max connections in pool (keep low for serverless)
    db_pool_max_overflow: int = 5  # Additional connections when pool is full
    db_pool_timeout: int = 30  # Seconds to wait for connection from pool
    db_pool_recycle: int = 3600  # Recycle connections after 1 hour
    db_pool_pre_ping: bool = True  # Test connection health before using
    db_echo_pool: bool = False  # Log pool events for debugging

    # ID Generator Configuration
    datacenter_id: int = 0
    worker_id: int = 0
    epoch_sec: int = 1704067200  # 2024-01-01 00:00:00 UTC

    # Bit Allocation (47 bits total for 8 characters)
    timestamp_bits: int = 31   # near about 50 years
    datacenter_bits: int = 4   # 16 datacenters
    worker_bits: int = 2       # 4 workers per DC
    sequence_bits: int = 10     # 1024 IDs/second per worker

    # Application
    base_domain: str = "short.ly"
    base_url_scheme: str = "https"  # http or https

    # Server Configuration
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = True  # Auto-reload for development

    # CORS Configuration
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080,http://localhost:5500,http://127.0.0.1:5500"  # Comma-separated list of allowed origins

    # Logging Configuration
    log_level: str = "DEBUG"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

    # Cache Configuration
    cache_enabled: bool = True  # Enable/disable caching
    cache_max_size: int = 1000  # Maximum number of entries in cache
    cache_ttl_seconds: int = 3600  # Time to live (1 hour default)

    # Redis Configuration (for Upstash Redis)
    redis_url: str = ""  # Redis connection URL (e.g., redis://localhost:6379 or Upstash URL)
    redis_enabled: bool = False  # Enable Redis cache and queue

    # Redis Connection Pooling (like PgBouncer for PostgreSQL)
    # Each service gets its own connection pool (singleton pattern in dependencies.py)
    # Pool size should match expected concurrent requests per service
    redis_pool_max_connections: int = 50  # Max connections in pool (tune based on load)
    redis_socket_timeout: int = 5  # Socket operation timeout in seconds
    redis_socket_connect_timeout: int = 5  # Connection timeout in seconds

    # Queue Configuration
    queue_enabled: bool = False  # Enable async batch processing
    batch_size: int = 100  # Number of URLs to batch insert at once
    batch_interval_seconds: int = 10  # Process queue every N seconds
    enable_background_scheduler: bool = False  # Background processing (set True in local .env for dev)

    class Config:
        # Look for .env in current working directory
        # When running from services/shorten/, it will find services/shorten/.env
        # When running from project root, it will find .env
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"  # Ignore extra fields in .env


# Global settings instance
# This is created when the module is imported, using .env from the current working directory
settings = Settings()


def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings
