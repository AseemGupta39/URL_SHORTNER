"""
Tests for ClickAnalyticsService — click tracking with fail-open design.
"""
import pytest
from unittest.mock import AsyncMock, patch

from shared.core.services.click_analytics_service import ClickAnalyticsService
from shared.core.schemas import ClickData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_click_repo():
    repo = AsyncMock()
    repo.batch_create = AsyncMock(return_value=1)
    repo.get_clicks_by_short_code = AsyncMock(return_value=[])
    repo.get_click_count_for_short_code = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_queue():
    queue = AsyncMock()
    queue.enqueue = AsyncMock(return_value=None)  # enqueue returns None now
    return queue


@pytest.fixture
def service_with_queue(mock_click_repo, mock_queue):
    return ClickAnalyticsService(click_repo=mock_click_repo, queue=mock_queue)


@pytest.fixture
def service_no_queue(mock_click_repo):
    return ClickAnalyticsService(click_repo=mock_click_repo, queue=None)


# ---------------------------------------------------------------------------
# track_click — queue path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_with_queue_returns_true(_, service_with_queue):
    result = await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    assert result is True


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_enqueues_message(_, service_with_queue, mock_queue):
    await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    mock_queue.enqueue.assert_called_once()


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_queue_message_has_correct_fields(_, service_with_queue, mock_queue):
    await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="TestAgent/1.0",
        referrer="https://google.com",
    )
    queued = mock_queue.enqueue.call_args[0][0]
    assert queued["short_code"] == "abc12345"
    assert queued["original_url"] == "https://example.com"
    assert queued["ip_address"] == "1.2.3.4"
    assert queued["user_agent"] == "TestAgent/1.0"
    assert queued["referrer"] == "https://google.com"
    assert "clicked_at" in queued
    assert "click_id" in queued
    assert len(queued["click_id"]) > 0  # non-empty UUID


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_generates_unique_click_id_per_call(_, service_with_queue, mock_queue):
    """Two successive track_click calls must produce different click_ids."""
    await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    first_call = mock_queue.enqueue.call_args_list[0][0][0]
    second_call = mock_queue.enqueue.call_args_list[1][0][0]
    assert first_call["click_id"] != second_call["click_id"]


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_with_queue_does_not_call_repo(_, service_with_queue, mock_click_repo):
    await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    mock_click_repo.batch_create.assert_not_called()


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_with_no_referrer(_, service_with_queue, mock_queue):
    await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
        referrer=None,
    )
    queued = mock_queue.enqueue.call_args[0][0]
    assert queued["referrer"] is None


# ---------------------------------------------------------------------------
# track_click — no queue (sync fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_track_click_no_queue_writes_to_repo(service_no_queue, mock_click_repo):
    result = await service_no_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    assert result is True
    mock_click_repo.batch_create.assert_called_once()


@pytest.mark.asyncio
async def test_track_click_no_queue_batch_create_receives_click_data(service_no_queue, mock_click_repo):
    await service_no_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="10.0.0.1",
        user_agent="curl/7.0",
        referrer="https://referrer.com",
    )
    call_args = mock_click_repo.batch_create.call_args[0][0]
    assert len(call_args) == 1
    click = call_args[0]
    assert isinstance(click, ClickData)
    assert click.short_code == "abc12345"
    assert click.ip_address == "10.0.0.1"
    assert click.referrer == "https://referrer.com"
    assert len(click.click_id) > 0  # sync fallback must also set click_id


# ---------------------------------------------------------------------------
# track_click — queue failure → sync fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_queue_exception_falls_back_to_repo(_, service_with_queue, mock_queue, mock_click_repo):
    mock_queue.enqueue = AsyncMock(side_effect=Exception("Redis down"))

    result = await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )

    assert result is True
    mock_click_repo.batch_create.assert_called_once()


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_queue_failure_still_returns_true(_, service_with_queue, mock_queue):
    mock_queue.enqueue = AsyncMock(side_effect=Exception("Redis down"))

    result = await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )

    assert result is True


# ---------------------------------------------------------------------------
# track_click — fail-open: both queue and repo fail
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_both_fail_returns_false(_, service_with_queue, mock_queue, mock_click_repo):
    mock_queue.enqueue = AsyncMock(side_effect=Exception("Redis down"))
    mock_click_repo.batch_create = AsyncMock(side_effect=Exception("DB down"))

    result = await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )

    assert result is False


@pytest.mark.asyncio
async def test_track_click_repo_failure_returns_false(service_no_queue, mock_click_repo):
    mock_click_repo.batch_create = AsyncMock(side_effect=Exception("DB down"))

    result = await service_no_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )

    assert result is False


@pytest.mark.asyncio
@patch("shared.utils.request_context.get_request_id", return_value="req-test")
async def test_track_click_never_raises(_, service_with_queue, mock_queue, mock_click_repo):
    """Fail-open: track_click must never raise, always return bool."""
    mock_queue.enqueue = AsyncMock(side_effect=RuntimeError("critical failure"))
    mock_click_repo.batch_create = AsyncMock(side_effect=RuntimeError("critical failure"))

    # Should not raise
    result = await service_with_queue.track_click(
        short_code="abc12345",
        original_url="https://example.com",
        ip_address="1.2.3.4",
        user_agent="Mozilla/5.0",
    )
    assert result is False


# ---------------------------------------------------------------------------
# get_clicks_for_short_code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_clicks_returns_list(service_with_queue, mock_click_repo):
    mock_click_repo.get_clicks_by_short_code = AsyncMock(return_value=[])
    result = await service_with_queue.get_clicks_for_short_code("abc12345")
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_clicks_calls_repo_with_short_code(service_with_queue, mock_click_repo):
    mock_click_repo.get_clicks_by_short_code = AsyncMock(return_value=[])
    await service_with_queue.get_clicks_for_short_code("abc12345")
    mock_click_repo.get_clicks_by_short_code.assert_called_once_with("abc12345", 100)


@pytest.mark.asyncio
async def test_get_clicks_respects_limit(service_with_queue, mock_click_repo):
    mock_click_repo.get_clicks_by_short_code = AsyncMock(return_value=[])
    await service_with_queue.get_clicks_for_short_code("abc12345", limit=10)
    mock_click_repo.get_clicks_by_short_code.assert_called_once_with("abc12345", 10)


@pytest.mark.asyncio
async def test_get_clicks_raises_on_db_error(service_with_queue, mock_click_repo):
    mock_click_repo.get_clicks_by_short_code = AsyncMock(side_effect=Exception("DB error"))
    with pytest.raises(Exception, match="DB error"):
        await service_with_queue.get_clicks_for_short_code("abc12345")


# ---------------------------------------------------------------------------
# get_click_count
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_click_count_returns_int(service_with_queue, mock_click_repo):
    mock_click_repo.get_click_count_for_short_code = AsyncMock(return_value=42)
    result = await service_with_queue.get_click_count("abc12345")
    assert result == 42


@pytest.mark.asyncio
async def test_get_click_count_calls_repo(service_with_queue, mock_click_repo):
    mock_click_repo.get_click_count_for_short_code = AsyncMock(return_value=5)
    await service_with_queue.get_click_count("abc12345")
    mock_click_repo.get_click_count_for_short_code.assert_called_once_with("abc12345")


@pytest.mark.asyncio
async def test_get_click_count_raises_on_db_error(service_with_queue, mock_click_repo):
    mock_click_repo.get_click_count_for_short_code = AsyncMock(side_effect=Exception("DB error"))
    with pytest.raises(Exception, match="DB error"):
        await service_with_queue.get_click_count("abc12345")


@pytest.mark.asyncio
async def test_get_click_count_returns_zero(service_with_queue, mock_click_repo):
    mock_click_repo.get_click_count_for_short_code = AsyncMock(return_value=0)
    result = await service_with_queue.get_click_count("newcode1")
    assert result == 0
