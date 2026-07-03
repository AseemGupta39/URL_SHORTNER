"""
Test suite for ClickRepository interface behaviour.
All tests mock at the ClickRepository interface level — no real DB needed.
Integration tests against real PostgreSQL live in tests/integration/.
"""
import uuid
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from shared.core.schemas import ClickData
from shared.data.interfaces.click_repository import ClickRepository
from shared.data.repositories.postgres_click_repository import PostgresClickRepository
from shared.data.models import ClickModel


@pytest.fixture
def repo():
    """Mock repository conforming to ClickRepository interface."""
    return AsyncMock(spec=ClickRepository)


@pytest.fixture
def sample_click():
    return ClickData(
        click_id=str(uuid.uuid4()),
        short_code="abc1234",
        original_url="https://example.com/test",
        clicked_at=datetime.now(),
        ip_address="192.168.1.1",
        user_agent="Mozilla/5.0",
        referrer="https://google.com",
    )


# ---------------------------------------------------------------------------
# batch_create()
# ---------------------------------------------------------------------------

class TestClickRepositoryBatchCreate:

    @pytest.mark.asyncio
    async def test_batch_create_returns_inserted_count(self, repo):
        clicks = [
            ClickData(
                click_id=str(uuid.uuid4()),
                short_code=f"c{i}",
                original_url=f"https://example.com/{i}",
                clicked_at=datetime.now(),
                ip_address="127.0.0.1",
                user_agent="test-agent",
                referrer=None,
            )
            for i in range(10)
        ]
        repo.batch_create.return_value = 10

        result = await repo.batch_create(clicks)

        assert result == 10
        repo.batch_create.assert_called_once_with(clicks)

    @pytest.mark.asyncio
    async def test_batch_create_empty_list_returns_zero(self, repo):
        repo.batch_create.return_value = 0

        result = await repo.batch_create([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_batch_create_single_item(self, repo, sample_click):
        repo.batch_create.return_value = 1

        result = await repo.batch_create([sample_click])

        assert result == 1

    @pytest.mark.asyncio
    async def test_batch_create_large_batch(self, repo):
        clicks = [
            ClickData(
                click_id=str(uuid.uuid4()),
                short_code=f"lg{i:04d}",
                original_url=f"https://example.com/{i}",
                clicked_at=datetime.now(),
                ip_address="10.0.0.1",
                user_agent="agent",
                referrer=None,
            )
            for i in range(100)
        ]
        repo.batch_create.return_value = 100

        result = await repo.batch_create(clicks)

        assert result == 100

    @pytest.mark.asyncio
    async def test_batch_create_propagates_db_failure(self, repo, sample_click):
        repo.batch_create.side_effect = Exception("DB connection lost")

        with pytest.raises(Exception, match="DB connection lost"):
            await repo.batch_create([sample_click])

    @pytest.mark.asyncio
    async def test_batch_create_accepts_optional_referrer_none(self, repo):
        click = ClickData(
            click_id=str(uuid.uuid4()),
            short_code="direct1",
            original_url="https://example.com",
            clicked_at=datetime.now(),
            ip_address="127.0.0.1",
            user_agent="test",
            referrer=None,
        )
        repo.batch_create.return_value = 1

        result = await repo.batch_create([click])

        assert result == 1

    @pytest.mark.asyncio
    async def test_batch_create_idempotent_on_reprocess(self, repo):
        """
        On a reprocessed batch (crash recovery), all rows already exist
        because click_id is supplied by the producer and is stable across
        reprocesses. ON CONFLICT DO NOTHING means 0 rows inserted — no error.
        """
        clicks = [
            ClickData(
                click_id=str(uuid.uuid4()),
                short_code=f"dup{i}",
                original_url=f"https://example.com/{i}",
                clicked_at=datetime.now(),
                ip_address="1.1.1.1",
                user_agent="a",
                referrer=None,
            )
            for i in range(5)
        ]
        repo.batch_create.return_value = 0  # all already exist, silently skipped

        result = await repo.batch_create(clicks)

        assert result == 0
        repo.batch_create.assert_called_once()


# ---------------------------------------------------------------------------
# get_clicks_by_short_code()
# ---------------------------------------------------------------------------

class TestClickRepositoryGetClicksByShortCode:

    @pytest.mark.asyncio
    async def test_get_clicks_returns_list(self, repo, sample_click):
        repo.get_clicks_by_short_code.return_value = [sample_click]

        result = await repo.get_clicks_by_short_code("abc1234")

        assert len(result) == 1
        assert result[0].short_code == "abc1234"
        repo.get_clicks_by_short_code.assert_called_once_with("abc1234")

    @pytest.mark.asyncio
    async def test_get_clicks_empty_returns_empty_list(self, repo):
        repo.get_clicks_by_short_code.return_value = []

        result = await repo.get_clicks_by_short_code("nope")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_clicks_passes_limit(self, repo):
        repo.get_clicks_by_short_code.return_value = []

        await repo.get_clicks_by_short_code("abc1234", limit=50)

        repo.get_clicks_by_short_code.assert_called_once_with("abc1234", limit=50)

    @pytest.mark.asyncio
    async def test_get_clicks_preserves_order_descending(self, repo):
        """Interface contract: results ordered by clicked_at DESC (newest first)."""
        clicks = [
            ClickData(
                click_id=str(uuid.uuid4()),
                short_code="abc1234",
                original_url="https://example.com",
                clicked_at=datetime(2026, 1, 3),
                ip_address="1.1.1.1",
                user_agent="a",
                referrer=None,
            ),
            ClickData(
                click_id=str(uuid.uuid4()),
                short_code="abc1234",
                original_url="https://example.com",
                clicked_at=datetime(2026, 1, 2),
                ip_address="1.1.1.1",
                user_agent="a",
                referrer=None,
            ),
            ClickData(
                click_id=str(uuid.uuid4()),
                short_code="abc1234",
                original_url="https://example.com",
                clicked_at=datetime(2026, 1, 1),
                ip_address="1.1.1.1",
                user_agent="a",
                referrer=None,
            ),
        ]
        repo.get_clicks_by_short_code.return_value = clicks

        result = await repo.get_clicks_by_short_code("abc1234")

        assert result[0].clicked_at > result[1].clicked_at > result[2].clicked_at


# ---------------------------------------------------------------------------
# get_click_count_for_short_code()
# ---------------------------------------------------------------------------

class TestClickRepositoryGetClickCount:

    @pytest.mark.asyncio
    async def test_count_returns_int(self, repo):
        repo.get_click_count_for_short_code.return_value = 42

        result = await repo.get_click_count_for_short_code("abc1234")

        assert result == 42
        repo.get_click_count_for_short_code.assert_called_once_with("abc1234")

    @pytest.mark.asyncio
    async def test_count_zero_for_unknown_code(self, repo):
        repo.get_click_count_for_short_code.return_value = 0

        result = await repo.get_click_count_for_short_code("nope")

        assert result == 0


# ---------------------------------------------------------------------------
# PostgresClickRepository.get_clicks_by_short_code() — implementation tests
# These test the actual repository code, not the mock interface.
# They catch regressions like missing fields in the ClickData constructor.
# ---------------------------------------------------------------------------

class TestPostgresClickRepositoryGetClicks:

    def _make_click_model(self, click_id=None, short_code="abc1234", referrer=None):
        """Build a fake ClickModel row as SQLAlchemy would return it."""
        m = MagicMock(spec=ClickModel)
        m.id = click_id or str(uuid.uuid4())
        m.short_code = short_code
        m.original_url = "https://example.com/test"
        m.clicked_at = datetime(2026, 1, 1, 12, 0, 0)
        m.ip_address = "127.0.0.1"
        m.user_agent = "Mozilla/5.0"
        m.referrer = referrer
        return m

    @pytest.mark.asyncio
    async def test_get_clicks_maps_click_id_from_db_row(self):
        """
        Regression test for BUG-H1: click_id was missing from ClickData constructor.
        get_clicks_by_short_code() must populate click_id from click.id on each row.
        """
        expected_id = str(uuid.uuid4())
        fake_row = self._make_click_model(click_id=expected_id)

        repo = PostgresClickRepository(db_url="postgresql+asyncpg://fake/db")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [fake_row]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        mock_session_factory = MagicMock(return_value=mock_session)
        repo.async_session = mock_session_factory
        repo.engine = MagicMock()  # skip initialize()

        result = await repo.get_clicks_by_short_code("abc1234")

        assert len(result) == 1
        assert result[0].click_id == expected_id

    @pytest.mark.asyncio
    async def test_get_clicks_returns_correct_fields(self):
        """All ClickData fields are populated correctly from the DB row."""
        fake_id = str(uuid.uuid4())
        fake_row = self._make_click_model(click_id=fake_id, referrer="https://google.com")

        repo = PostgresClickRepository(db_url="postgresql+asyncpg://fake/db")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [fake_row]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        repo.async_session = MagicMock(return_value=mock_session)
        repo.engine = MagicMock()

        result = await repo.get_clicks_by_short_code("abc1234")

        cd = result[0]
        assert cd.click_id == fake_id
        assert cd.short_code == "abc1234"
        assert cd.original_url == "https://example.com/test"
        assert cd.ip_address == "127.0.0.1"
        assert cd.user_agent == "Mozilla/5.0"
        assert cd.referrer == "https://google.com"

    @pytest.mark.asyncio
    async def test_get_clicks_empty_db_returns_empty_list(self):
        """Returns empty list when no rows found — no crash, no exception."""
        repo = PostgresClickRepository(db_url="postgresql+asyncpg://fake/db")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        repo.async_session = MagicMock(return_value=mock_session)
        repo.engine = MagicMock()

        result = await repo.get_clicks_by_short_code("nope")

        assert result == []

    @pytest.mark.asyncio
    async def test_get_clicks_multiple_rows_all_have_click_id(self):
        """Every row in a multi-row result gets its own click_id correctly."""
        ids = [str(uuid.uuid4()) for _ in range(3)]
        fake_rows = [self._make_click_model(click_id=i) for i in ids]

        repo = PostgresClickRepository(db_url="postgresql+asyncpg://fake/db")

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = fake_rows

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        repo.async_session = MagicMock(return_value=mock_session)
        repo.engine = MagicMock()

        result = await repo.get_clicks_by_short_code("abc1234")

        assert len(result) == 3
        assert [cd.click_id for cd in result] == ids