"""
Comprehensive test suite for SQLiteURLRepository.
"""
import pytest
import pytest_asyncio
import os
from datetime import datetime
from shared.core.schemas import URLData
from shared.data.repositories import SQLiteURLRepository


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database path for testing."""
    db_path = tmp_path / "test_urls.db"
    yield str(db_path)
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest_asyncio.fixture
async def repository(temp_db_path):
    """Create a fresh repository instance for each test."""
    db_url = f"sqlite+aiosqlite:///{temp_db_path}"
    repo = SQLiteURLRepository(db_url=db_url)
    await repo.initialize()
    yield repo
    await repo.close()


class TestSQLiteURLRepositoryInitialization:
    """Test repository initialization and database setup."""

    @pytest.mark.asyncio
    async def test_initialize_creates_database(self, temp_db_path):
        """Test that initialize creates the database file and can be used."""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        repo = SQLiteURLRepository(db_url=db_url)
        await repo.initialize()

        # Verify database file exists
        assert os.path.exists(temp_db_path)

        # Verify we can perform basic operations
        url_data = URLData(
            short_code="test123",
            original_url="https://example.com",
            created_at=datetime.now()
        )
        result = await repo.create(url_data)
        assert result.short_code == "test123"

        await repo.close()


class TestSQLiteURLRepositoryCreate:
    """Test URL creation operations."""

    @pytest.mark.asyncio
    async def test_create_url_success(self, repository):
        """Test creating a new URL mapping."""
        url_data = URLData(
            short_code="abc1234",
            original_url="https://example.com/test",
            created_at=datetime.now()
        )

        result = await repository.create(url_data)

        assert result.short_code == "abc1234"
        assert result.original_url == "https://example.com/test"
        assert isinstance(result.created_at, datetime)

    @pytest.mark.asyncio
    async def test_create_multiple_different_urls(self, repository):
        """Test creating multiple different URL mappings with different domains."""
        url_data = URLData(
            short_code="multi1",
            original_url="https://different.com/path",
            created_at=datetime.now()
        )

        result = await repository.create(url_data)

        assert result.short_code == "multi1"
        assert result.original_url == "https://different.com/path"

    @pytest.mark.asyncio
    async def test_create_duplicate_short_code_raises_error(self, repository):
        """Test that creating a duplicate short code raises an error."""
        url_data1 = URLData(
            short_code="dup1234",
            original_url="https://example.com/first",
            created_at=datetime.now()
        )
        url_data2 = URLData(
            short_code="dup1234",
            original_url="https://example.com/second",
            created_at=datetime.now()
        )

        await repository.create(url_data1)

        with pytest.raises(Exception):  # aiosqlite.IntegrityError or similar
            await repository.create(url_data2)

    @pytest.mark.asyncio
    async def test_create_multiple_urls(self, repository):
        """Test creating multiple different URL mappings."""
        urls = [
            URLData(
                short_code=f"url{i}",
                original_url=f"https://example.com/test{i}",
                created_at=datetime.now()
            )
            for i in range(10)
        ]

        for url_data in urls:
            result = await repository.create(url_data)
            assert result.short_code == url_data.short_code


class TestSQLiteURLRepositoryGetByShortCode:
    """Test URL retrieval operations."""

    @pytest.mark.asyncio
    async def test_get_existing_url(self, repository):
        """Test retrieving an existing URL by short code."""
        url_data = URLData(
            short_code="get1234",
            original_url="https://example.com/get",
            created_at=datetime.now()
        )
        await repository.create(url_data)

        result = await repository.get_by_short_code("get1234")

        assert result is not None
        assert result.short_code == "get1234"
        assert result.original_url == "https://example.com/get"

    @pytest.mark.asyncio
    async def test_get_nonexistent_url_returns_none(self, repository):
        """Test that retrieving a nonexistent short code returns None."""
        result = await repository.get_by_short_code("notfound")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_url_with_query_params(self, repository):
        """Test retrieving a URL with query parameters."""
        url_data = URLData(
            short_code="query1",
            original_url="https://example.com/path?foo=bar&baz=qux",
            created_at=datetime.now()
        )
        await repository.create(url_data)

        result = await repository.get_by_short_code("query1")

        assert result is not None
        assert "foo=bar" in result.original_url

    @pytest.mark.asyncio
    async def test_get_preserves_created_at(self, repository):
        """Test that retrieved URL preserves created_at timestamp."""
        created_time = datetime.now()
        url_data = URLData(
            short_code="time123",
            original_url="https://example.com/time",
            created_at=created_time
        )
        await repository.create(url_data)

        result = await repository.get_by_short_code("time123")

        assert result is not None
        assert isinstance(result.created_at, datetime)
        # Allow for small time differences due to storage/retrieval
        time_diff = abs((result.created_at - created_time).total_seconds())
        assert time_diff < 1.0


class TestSQLiteURLRepositoryExists:
    """Test short code existence checks."""

    @pytest.mark.asyncio
    async def test_exists_returns_true_for_existing_code(self, repository):
        """Test that exists returns True for an existing short code."""
        url_data = URLData(
            short_code="exists1",
            original_url="https://example.com/exists",
            created_at=datetime.now()
        )
        await repository.create(url_data)

        result = await repository.exists("exists1")

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_nonexistent_code(self, repository):
        """Test that exists returns False for a nonexistent short code."""
        result = await repository.exists("notexists")

        assert result is False

    @pytest.mark.asyncio
    async def test_exists_after_multiple_inserts(self, repository):
        """Test exists check after inserting multiple URLs."""
        codes = ["code1", "code2", "code3"]

        for code in codes:
            url_data = URLData(
                short_code=code,
                original_url=f"https://example.com/{code}",
                created_at=datetime.now()
            )
            await repository.create(url_data)

        for code in codes:
            assert await repository.exists(code) is True

        assert await repository.exists("code4") is False


class TestSQLiteURLRepositoryEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_create_with_very_long_url(self, repository):
        """Test creating a URL with very long original URL."""
        long_url = "https://example.com/" + "a" * 2000
        url_data = URLData(
            short_code="long123",
            original_url=long_url,
            created_at=datetime.now()
        )

        result = await repository.create(url_data)
        retrieved = await repository.get_by_short_code("long123")

        assert retrieved is not None
        assert retrieved.original_url == long_url

    @pytest.mark.asyncio
    async def test_create_with_8_char_code(self, repository):
        """Test creating a URL with 8-character code (max length)."""
        url_data = URLData(
            short_code="abcdefgh",
            original_url="https://example.com/eight",
            created_at=datetime.now()
        )

        result = await repository.create(url_data)
        assert result.short_code == "abcdefgh"

    @pytest.mark.asyncio
    async def test_create_with_special_chars_in_url(self, repository):
        """Test creating a URL with special characters."""
        special_url = "https://example.com/path?query=value&foo=bar#section"
        url_data = URLData(
            short_code="spec123",
            original_url=special_url,
            created_at=datetime.now()
        )

        result = await repository.create(url_data)
        retrieved = await repository.get_by_short_code("spec123")

        assert retrieved is not None
        assert retrieved.original_url == special_url

    @pytest.mark.asyncio
    async def test_concurrent_creates(self, repository):
        """Test creating multiple URLs concurrently."""
        import asyncio

        async def create_url(i):
            url_data = URLData(
                short_code=f"conc{i:03d}",
                original_url=f"https://example.com/concurrent{i}",
                created_at=datetime.now()
            )
            return await repository.create(url_data)

        # Create 50 URLs concurrently
        results = await asyncio.gather(*[create_url(i) for i in range(50)])

        assert len(results) == 50
        assert all(r.short_code == f"conc{i:03d}" for i, r in enumerate(results))


class TestSQLiteURLRepositoryIntegration:
    """Integration tests for complete workflows."""

    @pytest.mark.asyncio
    async def test_create_and_retrieve_workflow(self, repository):
        """Test complete workflow of creating and retrieving a URL."""
        # Create
        url_data = URLData(
            short_code="work123",
            original_url="https://example.com/workflow",
            created_at=datetime.now()
        )
        created = await repository.create(url_data)

        # Check exists
        exists = await repository.exists("work123")
        assert exists is True

        # Retrieve
        retrieved = await repository.get_by_short_code("work123")
        assert retrieved is not None
        assert retrieved.short_code == created.short_code
        assert retrieved.original_url == created.original_url

    @pytest.mark.asyncio
    async def test_bulk_operations(self, repository):
        """Test bulk create and retrieve operations."""
        # Bulk create
        codes = []
        for i in range(100):
            code = f"bulk{i:03d}"
            codes.append(code)
            url_data = URLData(
                short_code=code,
                original_url=f"https://example.com/bulk{i}",
                created_at=datetime.now()
            )
            await repository.create(url_data)

        # Bulk retrieve
        for code in codes:
            result = await repository.get_by_short_code(code)
            assert result is not None
            assert result.short_code == code

    @pytest.mark.asyncio
    async def test_database_persistence(self, temp_db_path):
        """Test that data persists across repository instances."""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"

        # Create and insert data
        repo1 = SQLiteURLRepository(db_url=db_url)
        await repo1.initialize()

        url_data = URLData(
            short_code="persist",
            original_url="https://example.com/persist",
            created_at=datetime.now()
        )
        await repo1.create(url_data)
        await repo1.close()

        # Create new instance and verify data exists
        repo2 = SQLiteURLRepository(db_url=db_url)
        await repo2.initialize()

        result = await repo2.get_by_short_code("persist")
        assert result is not None
        assert result.short_code == "persist"

        await repo2.close()
