"""
Redirect Service specific settings.
This service resolves short codes and redirects to original URLs.
Port: 8002
"""
from pydantic_settings import BaseSettings


class RedirectServiceSettings(BaseSettings):
    """Settings specific to Redirect Service."""

    # Database Configuration
    database_url: str = "sqlite+aiosqlite:///urls.db"
    db_pool_size: int = 10
    db_pool_max_overflow: int = 5
    db_pool_timeout: int = 30
    db_pool_recycle: int = 3600
    db_pool_pre_ping: bool = True
    db_echo_pool: bool = False

    # Server Configuration (Port 8002)
    host: str = "0.0.0.0"
    port: int = 8002
    reload: bool = True

    # CORS Configuration (redirects work from anywhere)
    cors_origins: str = "*"

    # Logging
    log_level: str = "DEBUG"

    # Cache Configuration (REQUIRED - caches URL lookups)
    cache_max_size: int = 1000
    cache_ttl_seconds: int = 3600

    # Redis Configuration (for cache only - no queue needed)
    redis_url: str = ""
    redis_enabled: bool = False
    redis_pool_max_connections: int = 50
    redis_socket_timeout: int = 5
    redis_socket_connect_timeout: int = 5

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Global singleton instance
settings = RedirectServiceSettings()


def get_settings() -> RedirectServiceSettings:
    """Get the redirect service settings instance."""
    return settings
