"""
Application settings configuration.
"""
from typing import Any
from pydantic_settings import BaseSettings
from pydantic import field_validator, model_validator, ValidationInfo


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
    cache_max_size: int = 1000  # Maximum number of entries in cache
    cache_ttl_seconds: int = 3600  # Time to live (1 hour default)

    # Redis Configuration (for Upstash Redis)
    redis_url: str = ""  # Redis connection URL (e.g., redis://localhost:6379 or Upstash URL)
    redis_enabled: bool = False  # Enable Redis cache and queue

    # Redis Connection Pooling (like PgBouncer for PostgreSQL)
    # Each service gets its own connection pool (singleton pattern in dependencies.py)
    # Pool size should match expected concurrent requests per service
    redis_pool_max_connections: int = 50  # Max connections in pool (tune based on load)

    # Redis Timeout Configuration
    # Different timeouts for cache vs queue operations (cache is non-critical, queue is important)
    redis_cache_socket_timeout: int = 1  # Cache read/write timeout (fail fast, cache miss is ok)
    redis_cache_connect_timeout: int = 1  # Cache connection timeout
    redis_queue_socket_timeout: int = 3  # Queue read/write timeout (try harder, queue is important)
    redis_queue_connect_timeout: int = 2  # Queue connection timeout

    # Queue Configuration (REQUIRED - Redis queue is fundamental to architecture)
    batch_size: int = 100  # Number of URLs to batch insert at once
    batch_interval_seconds: int = 10  # Process queue every N seconds
    enable_background_scheduler: bool = False  # Background processing (set True in local .env for dev)

    # Click Analytics Configuration
    click_batch_interval_seconds: int = 30  # Process click queue every N seconds

    # Batch DB Retry Configuration (exponential backoff: base, base*2, base*4 ...)
    batch_db_max_retries: int = 3  # Total attempts per batch_create call
    batch_db_backoff_base_seconds: float = 1.0  # First wait between attempts

    # Validators
    @field_validator('datacenter_id')
    @classmethod
    def validate_datacenter_id(cls, v: Any, info: ValidationInfo) -> int:
        """Validate datacenter_id is within valid range (0-15 for 4 bits)."""
        max_value = (1 << info.data.get('datacenter_bits', 4)) - 1
        if v < 0 or v > max_value:
            raise ValueError(f"datacenter_id must be between 0 and {max_value}")
        return v

    @field_validator('worker_id')
    @classmethod
    def validate_worker_id(cls, v: Any, info: ValidationInfo) -> int:
        """Validate worker_id is within valid range (0-3 for 2 bits)."""
        max_value = (1 << info.data.get('worker_bits', 2)) - 1
        if v < 0 or v > max_value:
            raise ValueError(f"worker_id must be between 0 and {max_value}")
        return v

    @field_validator('timestamp_bits', 'datacenter_bits', 'worker_bits', 'sequence_bits')
    @classmethod
    def validate_bit_fields(cls, v: Any, info: ValidationInfo) -> int:
        """Validate bit field sizes are positive."""
        if v <= 0:
            raise ValueError(f"{info.field_name} must be positive")
        return v

    @model_validator(mode='after')
    def validate_total_bits(self) -> "Settings":
        """Validate total bit allocation is exactly 47 for 8-character base62 codes."""
        total_bits = (
            self.timestamp_bits +
            self.datacenter_bits +
            self.worker_bits +
            self.sequence_bits
        )
        # 47 bits produces 8-character base62 codes (this is a resume project, not commercial)
        if total_bits != 47:
            raise ValueError(
                f"Total bits must be exactly 47 for 8-character codes (got {total_bits}). "
                f"Current allocation: timestamp={self.timestamp_bits}, "
                f"datacenter={self.datacenter_bits}, worker={self.worker_bits}, "
                f"sequence={self.sequence_bits}"
            )
        return self

    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: Any) -> str:
        """Validate log level is a valid Python logging level."""
        valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v_upper

    @field_validator('base_url_scheme')
    @classmethod
    def validate_url_scheme(cls, v: Any) -> str:
        """Validate URL scheme is http or https."""
        if v not in ['http', 'https']:
            raise ValueError("base_url_scheme must be 'http' or 'https'")
        return v

    @field_validator('batch_size')
    @classmethod
    def validate_batch_size(cls, v: Any) -> int:
        """Validate batch size is reasonable."""
        if v <= 0:
            raise ValueError("batch_size must be positive")
        if v > 10000:
            raise ValueError("batch_size should not exceed 10000 for performance reasons")
        return v

    @field_validator('batch_interval_seconds', 'click_batch_interval_seconds')
    @classmethod
    def validate_interval_seconds(cls, v: Any) -> int:
        """Validate interval is reasonable."""
        if v <= 0:
            raise ValueError(f"Interval must be positive")
        if v > 3600:
            raise ValueError(f"Interval should not exceed 3600 seconds (1 hour)")
        return v

    @field_validator('cache_ttl_seconds')
    @classmethod
    def validate_cache_ttl(cls, v: Any) -> int:
        """Validate cache TTL is reasonable."""
        if v <= 0:
            raise ValueError("cache_ttl_seconds must be positive")
        return v

    @field_validator('db_pool_size', 'db_pool_max_overflow')
    @classmethod
    def validate_pool_sizes(cls, v: Any) -> int:
        """Validate pool sizes are reasonable."""
        if v < 0:
            raise ValueError("Pool size must be non-negative")
        if v > 1000:
            raise ValueError("Pool size should not exceed 1000")
        return v

    @field_validator('redis_pool_max_connections')
    @classmethod
    def validate_redis_pool(cls, v: Any) -> int:
        """Validate Redis pool size is reasonable."""
        if v <= 0:
            raise ValueError("redis_pool_max_connections must be positive")
        if v > 1000:
            raise ValueError("redis_pool_max_connections should not exceed 1000")
        return v

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
