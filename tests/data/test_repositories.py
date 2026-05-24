"""
Test suite for URLRepository interface behaviour.
All tests mock at the URLRepository interface level — no real DB needed.
Integration tests against real PostgreSQL live in tests/integration/.
"""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, call

from shared.core.schemas import URLData
from shared.data.interfaces.url_repository import URLRepository


@pytest.fixture
def repo():
    """Mock repository conforming to URLRepository interface."""
    return AsyncMock(spec=URLRepository)


@pytest.fixture
def sample_url():
    return URLData(
        short_code="abc1234",
        original_url="https://example.com/test",
        created_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# create()
# ---------------------------------------------------------------------------

class TestURLRepositoryCreate:

    @pytest.mark.asyncio
    async def test_create_returns_url_data(self, repo, sample_url):
        repo.create.return_value = sample_url

        result = await repo.create(sample_url)

        assert result.short_code == sample_url.short_code
        assert result.original_url == sample_url.original_url
        repo.create.assert_called_once_with(sample_url)

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, repo, sample_url):
        repo.create.side_effect = Exception("IntegrityError: duplicate short_code")

        with pytest.raises(Exception, match="duplicate"):
            await repo.create(sample_url)

    @pytest.mark.asyncio
    async def test_create_multiple_different_codes(self, repo):
        urls = [
            URLData(short_code=f"code{i}", original_url=f"https://example.com/{i}", created_at=datetime.now())
            for i in range(5)
        ]
        repo.create.side_effect = urls

        for url in urls:
            result = await repo.create(url)
            assert result.short_code == url.short_code


# ---------------------------------------------------------------------------
# batch_create()
# ---------------------------------------------------------------------------

class TestURLRepositoryBatchCreate:

    @pytest.mark.asyncio
    async def test_batch_create_returns_inserted_count(self, repo):
        url_list = [
            URLData(short_code=f"b{i}", original_url=f"https://example.com/{i}", created_at=datetime.now())
            for i in range(10)
        ]
        repo.batch_create.return_value = 10

        result = await repo.batch_create(url_list)

        assert result == 10
        repo.batch_create.assert_called_once_with(url_list)

    @pytest.mark.asyncio
    async def test_batch_create_empty_list_returns_zero(self, repo):
        repo.batch_create.return_value = 0

        result = await repo.batch_create([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_create_idempotent_on_reprocess(self, repo):
        """
        On a reprocessed batch (crash recovery), all rows already exist.
        ON CONFLICT DO NOTHING means 0 rows inserted — no error raised.
        """
        url_list = [
            URLData(short_code=f"dup{i}", original_url=f"https://example.com/{i}", created_at=datetime.now())
            for i in range(5)
        ]
        repo.batch_create.return_value = 0  # all already exist, silently skipped

        result = await repo.batch_create(url_list)

        assert result == 0
        repo.batch_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_create_partial_duplicates(self, repo):
        """3 new rows, 2 already exist — only 3 inserted."""
        url_list = [
            URLData(short_code=f"p{i}", original_url=f"https://example.com/{i}", created_at=datetime.now())
            for i in range(5)
        ]
        repo.batch_create.return_value = 3

        result = await repo.batch_create(url_list)

        assert result == 3

    @pytest.mark.asyncio
    async def test_batch_create_single_item(self, repo):
        url = URLData(short_code="single1", original_url="https://example.com", created_at=datetime.now())
        repo.batch_create.return_value = 1

        result = await repo.batch_create([url])

        assert result == 1

    @pytest.mark.asyncio
    async def test_batch_create_large_batch(self, repo):
        url_list = [
            URLData(short_code=f"lg{i:04d}", original_url=f"https://example.com/{i}", created_at=datetime.now())
            for i in range(100)
        ]
        repo.batch_create.return_value = 100

        result = await repo.batch_create(url_list)

        assert result == 100


# ---------------------------------------------------------------------------
# get_by_short_code()
# ---------------------------------------------------------------------------

class TestURLRepositoryGetByShortCode:

    @pytest.mark.asyncio
    async def test_get_existing_returns_url_data(self, repo, sample_url):
        repo.get_by_short_code.return_value = sample_url

        result = await repo.get_by_short_code("abc1234")

        assert result is not None
        assert result.short_code == "abc1234"
        repo.get_by_short_code.assert_called_once_with("abc1234")

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, repo):
        repo.get_by_short_code.return_value = None

        result = await repo.get_by_short_code("notfound")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_preserves_all_fields(self, repo):
        created_at = datetime(2025, 1, 1, 12, 0, 0)
        url = URLData(short_code="fld1234", original_url="https://example.com/path?q=1", created_at=created_at)
        repo.get_by_short_code.return_value = url

        result = await repo.get_by_short_code("fld1234")

        assert result.original_url == "https://example.com/path?q=1"
        assert result.created_at == created_at


# ---------------------------------------------------------------------------
# exists()
# ---------------------------------------------------------------------------

class TestURLRepositoryExists:

    @pytest.mark.asyncio
    async def test_exists_true_for_known_code(self, repo):
        repo.exists.return_value = True

        result = await repo.exists("abc1234")

        assert result is True

    @pytest.mark.asyncio
    async def test_exists_false_for_unknown_code(self, repo):
        repo.exists.return_value = False

        result = await repo.exists("nope0000")

        assert result is False

    @pytest.mark.asyncio
    async def test_exists_called_with_correct_code(self, repo):
        repo.exists.return_value = True

        await repo.exists("xyz9999")

        repo.exists.assert_called_once_with("xyz9999")


# ---------------------------------------------------------------------------
# Workflow tests
# ---------------------------------------------------------------------------

class TestURLRepositoryWorkflow:

    @pytest.mark.asyncio
    async def test_create_then_get(self, repo, sample_url):
        repo.create.return_value = sample_url
        repo.get_by_short_code.return_value = sample_url

        created = await repo.create(sample_url)
        retrieved = await repo.get_by_short_code(created.short_code)

        assert retrieved.short_code == created.short_code
        assert retrieved.original_url == created.original_url

    @pytest.mark.asyncio
    async def test_create_then_exists(self, repo, sample_url):
        repo.create.return_value = sample_url
        repo.exists.return_value = True

        await repo.create(sample_url)
        exists = await repo.exists(sample_url.short_code)

        assert exists is True

    @pytest.mark.asyncio
    async def test_batch_create_then_get_each(self, repo):
        urls = [
            URLData(short_code=f"wf{i}", original_url=f"https://example.com/{i}", created_at=datetime.now())
            for i in range(3)
        ]
        repo.batch_create.return_value = 3
        repo.get_by_short_code.side_effect = urls

        inserted = await repo.batch_create(urls)
        assert inserted == 3

        for url in urls:
            result = await repo.get_by_short_code(url.short_code)
            assert result.short_code == url.short_code
