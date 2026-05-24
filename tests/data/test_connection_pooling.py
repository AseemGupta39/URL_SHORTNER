"""
Tests for database connection pooling configuration.

These tests verify that connection pooling is properly configured
for PostgreSQL production deployments with PgBouncer.
"""
import pytest
from shared.data.repositories import PostgresURLRepository
from shared.config.settings import Settings


class TestConnectionPoolingConfiguration:
    """Test connection pooling configuration for production databases."""

    def test_repository_accepts_pool_settings(self):
        repo = PostgresURLRepository(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            pool_size=20,
            max_overflow=10,
            pool_timeout=60,
            pool_recycle=7200,
            pool_pre_ping=True,
            echo_pool=True,
        )

        assert repo.db_url == "postgresql+asyncpg://user:pass@localhost:5432/db"
        assert repo.pool_size == 20
        assert repo.max_overflow == 10
        assert repo.pool_timeout == 60
        assert repo.pool_recycle == 7200
        assert repo.pool_pre_ping is True
        assert repo.echo_pool is True

    def test_repository_uses_default_pool_settings(self):
        repo = PostgresURLRepository(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/db"
        )

        assert repo.pool_size == 10
        assert repo.max_overflow == 5
        assert repo.pool_timeout == 30
        assert repo.pool_recycle == 3600
        assert repo.pool_pre_ping is True
        assert repo.echo_pool is False

    def test_settings_has_pool_configuration(self):
        settings = Settings()

        assert hasattr(settings, "db_pool_size")
        assert hasattr(settings, "db_pool_max_overflow")
        assert hasattr(settings, "db_pool_timeout")
        assert hasattr(settings, "db_pool_recycle")
        assert hasattr(settings, "db_pool_pre_ping")
        assert hasattr(settings, "db_echo_pool")

        assert settings.db_pool_size == 10
        assert settings.db_pool_max_overflow == 5
        assert settings.db_pool_timeout == 30
        assert settings.db_pool_recycle == 3600
        assert settings.db_pool_pre_ping is True
        assert settings.db_echo_pool is False

    def test_connection_pool_settings_for_serverless(self):
        settings = Settings()

        assert settings.db_pool_size <= 20
        assert settings.db_pool_max_overflow <= 10

        total_connections = settings.db_pool_size + settings.db_pool_max_overflow
        assert total_connections <= 30

    def test_pool_recycle_prevents_stale_connections(self):
        settings = Settings()

        assert 1800 <= settings.db_pool_recycle <= 7200

    def test_pool_pre_ping_enabled_for_reliability(self):
        settings = Settings()

        assert settings.db_pool_pre_ping is True


class TestPostgreSQLURLFormat:
    """Test PostgreSQL connection URL format compatibility."""

    def test_asyncpg_url_format(self):
        repo = PostgresURLRepository(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/dbname"
        )
        assert "postgresql" in repo.db_url

    def test_pgbouncer_url_format(self):
        repo = PostgresURLRepository(
            db_url="postgresql+asyncpg://user:pass@pgbouncer-host:6432/dbname"
        )
        assert "postgresql" in repo.db_url


class TestPgBouncerCompatibility:
    """Test PgBouncer compatibility settings."""

    def test_pool_settings_compatible_with_pgbouncer(self):
        settings = Settings()

        assert settings.db_pool_size <= 20

    def test_pool_pre_ping_works_with_pgbouncer(self):
        settings = Settings()

        assert settings.db_pool_pre_ping is True

    def test_pool_recycle_works_with_pgbouncer(self):
        settings = Settings()

        assert settings.db_pool_recycle > 0
        assert settings.db_pool_recycle <= 7200