"""
Tests for database connection pooling configuration.

These tests verify that connection pooling is properly configured
for PostgreSQL production deployments with PgBouncer.
"""
import pytest
from shared.data.repositories import SQLiteURLRepository
from shared.config.settings import Settings


class TestConnectionPoolingConfiguration:
    """Test connection pooling configuration for production databases."""

    def test_repository_accepts_pool_settings(self):
        """Test that repository accepts all pool configuration parameters."""
        repo = SQLiteURLRepository(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/db",
            pool_size=20,
            max_overflow=10,
            pool_timeout=60,
            pool_recycle=7200,
            pool_pre_ping=True,
            echo_pool=True
        )

        assert repo.db_url == "postgresql+asyncpg://user:pass@localhost:5432/db"
        assert repo.pool_size == 20
        assert repo.max_overflow == 10
        assert repo.pool_timeout == 60
        assert repo.pool_recycle == 7200
        assert repo.pool_pre_ping is True
        assert repo.echo_pool is True

    def test_repository_uses_default_pool_settings(self):
        """Test that repository uses sensible defaults for pool settings."""
        repo = SQLiteURLRepository(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/db"
        )

        assert repo.pool_size == 10
        assert repo.max_overflow == 5
        assert repo.pool_timeout == 30
        assert repo.pool_recycle == 3600
        assert repo.pool_pre_ping is True
        assert repo.echo_pool is False

    def test_sqlite_repository_accepts_pool_settings_gracefully(self):
        """Test that SQLite repository accepts pool settings (but won't use them)."""
        repo = SQLiteURLRepository(
            db_url="sqlite+aiosqlite:///test.db",
            pool_size=20,
            max_overflow=10
        )

        # SQLite doesn't use pooling but should accept the parameters
        assert repo.db_url == "sqlite+aiosqlite:///test.db"
        assert repo.pool_size == 20
        assert repo.max_overflow == 10

    @pytest.mark.asyncio
    async def test_sqlite_initialize_without_pooling(self):
        """Test that SQLite initializes without connection pooling."""
        repo = SQLiteURLRepository(
            db_url="sqlite+aiosqlite:///:memory:",
            pool_size=20,
            max_overflow=10
        )

        await repo.initialize()

        # Verify engine was created
        assert repo.engine is not None
        assert repo.async_session is not None

        # Verify it's using SQLite
        assert repo.db_url.startswith("sqlite")

        await repo.close()

    def test_settings_has_pool_configuration(self):
        """Test that Settings class includes all pool configuration options."""
        settings = Settings()

        # Verify all pool settings are present
        assert hasattr(settings, "db_pool_size")
        assert hasattr(settings, "db_pool_max_overflow")
        assert hasattr(settings, "db_pool_timeout")
        assert hasattr(settings, "db_pool_recycle")
        assert hasattr(settings, "db_pool_pre_ping")
        assert hasattr(settings, "db_echo_pool")

        # Verify default values are sensible
        assert settings.db_pool_size == 10
        assert settings.db_pool_max_overflow == 5
        assert settings.db_pool_timeout == 30
        assert settings.db_pool_recycle == 3600
        assert settings.db_pool_pre_ping is True
        assert settings.db_echo_pool is False

    def test_connection_pool_settings_for_serverless(self):
        """Test that pool settings are optimized for serverless (low connection count)."""
        settings = Settings()

        # Serverless environments should use small pool sizes
        # to avoid overwhelming the database with connections
        assert settings.db_pool_size <= 20, "Pool size should be ≤20 for serverless"
        assert settings.db_pool_max_overflow <= 10, "Max overflow should be ≤10 for serverless"

        # Total possible connections = pool_size + max_overflow
        total_connections = settings.db_pool_size + settings.db_pool_max_overflow
        assert total_connections <= 30, "Total connections should be ≤30 for serverless"

    def test_pool_recycle_prevents_stale_connections(self):
        """Test that pool_recycle is set to prevent stale connections."""
        settings = Settings()

        # Connections should be recycled within a reasonable time (1-2 hours)
        assert 1800 <= settings.db_pool_recycle <= 7200, \
            "Pool recycle should be 30min-2hours to prevent stale connections"

    def test_pool_pre_ping_enabled_for_reliability(self):
        """Test that pool_pre_ping is enabled for connection reliability."""
        settings = Settings()

        # pre_ping should be enabled to detect broken connections
        assert settings.db_pool_pre_ping is True, \
            "Pool pre-ping should be enabled for connection health checks"


class TestPostgreSQLURLFormat:
    """Test PostgreSQL connection URL format compatibility."""

    def test_asyncpg_url_format(self):
        """Test that PostgreSQL asyncpg URL format is recognized."""
        repo = SQLiteURLRepository(
            db_url="postgresql+asyncpg://user:pass@localhost:5432/dbname"
        )
        assert not repo.db_url.startswith("sqlite")

    def test_pgbouncer_url_format(self):
        """Test that PgBouncer URL format is recognized."""
        repo = SQLiteURLRepository(
            db_url="postgresql+asyncpg://user:pass@pgbouncer-host:6432/dbname"
        )
        assert not repo.db_url.startswith("sqlite")

    def test_sqlite_url_format(self):
        """Test that SQLite URL format is recognized."""
        repo = SQLiteURLRepository(db_url="sqlite+aiosqlite:///urls.db")
        assert repo.db_url.startswith("sqlite")

    def test_memory_sqlite_url_format(self):
        """Test that in-memory SQLite URL format is recognized."""
        repo = SQLiteURLRepository(db_url="sqlite+aiosqlite:///:memory:")
        assert repo.db_url.startswith("sqlite")


class TestPgBouncerCompatibility:
    """Test PgBouncer compatibility settings."""

    def test_pool_settings_compatible_with_pgbouncer(self):
        """
        Test that pool settings are compatible with PgBouncer.

        PgBouncer acts as a connection pooler, so our application pool
        should be relatively small to avoid creating too many connections
        to PgBouncer.
        """
        settings = Settings()

        # When using PgBouncer, application-level pool should be small
        assert settings.db_pool_size <= 20, \
            "Application pool should be small when using PgBouncer"

    def test_pool_pre_ping_works_with_pgbouncer(self):
        """
        Test that pre_ping is enabled (compatible with PgBouncer).

        PgBouncer may close idle connections, so pre_ping helps
        detect and recover from broken connections.
        """
        settings = Settings()

        assert settings.db_pool_pre_ping is True, \
            "Pre-ping should be enabled for PgBouncer compatibility"

    def test_pool_recycle_works_with_pgbouncer(self):
        """
        Test that pool_recycle is set (compatible with PgBouncer).

        PgBouncer has server_idle_timeout, so we should recycle
        connections before they're closed by PgBouncer.
        """
        settings = Settings()

        # Should recycle connections within 1-2 hours
        assert settings.db_pool_recycle > 0, \
            "Pool recycle should be set for PgBouncer compatibility"
        assert settings.db_pool_recycle <= 7200, \
            "Pool recycle should be ≤2 hours to avoid PgBouncer timeouts"
