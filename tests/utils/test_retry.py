"""
Tests for the retry_with_backoff async wrapper.
asyncio.sleep is mocked to keep tests fast — no real waiting.
"""
import pytest
from unittest.mock import AsyncMock, patch

from shared.utils.retry import retry_with_backoff


# ---------------------------------------------------------------------------
# Success paths
# ---------------------------------------------------------------------------

class TestRetrySuccess:

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_succeeds_on_first_attempt_no_sleep(self, mock_sleep):
        op = AsyncMock(return_value="ok")

        result = await retry_with_backoff(op, max_retries=3)

        assert result == "ok"
        assert op.call_count == 1
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_succeeds_on_second_attempt_one_sleep(self, mock_sleep):
        op = AsyncMock(side_effect=[Exception("boom"), "ok"])

        result = await retry_with_backoff(op, max_retries=3, backoff_base_seconds=1.0)

        assert result == "ok"
        assert op.call_count == 2
        assert mock_sleep.call_count == 1
        assert mock_sleep.call_args_list[0].args[0] == 1.0  # 1.0 * 2**0

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_succeeds_on_third_attempt_two_sleeps(self, mock_sleep):
        op = AsyncMock(side_effect=[Exception("boom1"), Exception("boom2"), "ok"])

        result = await retry_with_backoff(op, max_retries=3, backoff_base_seconds=1.0)

        assert result == "ok"
        assert op.call_count == 3
        assert mock_sleep.call_count == 2
        assert mock_sleep.call_args_list[0].args[0] == 1.0  # 1.0 * 2**0
        assert mock_sleep.call_args_list[1].args[0] == 2.0  # 1.0 * 2**1


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

class TestRetryFailure:

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_exhausts_retries_raises_last_exception(self, mock_sleep):
        op = AsyncMock(side_effect=Exception("permanent failure"))

        with pytest.raises(Exception, match="permanent failure"):
            await retry_with_backoff(op, max_retries=3, backoff_base_seconds=1.0)

        assert op.call_count == 3  # all attempts used
        assert mock_sleep.call_count == 2  # no sleep after final failure

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_no_sleep_after_final_failure(self, mock_sleep):
        """The last failing attempt must not sleep before raising."""
        op = AsyncMock(side_effect=Exception("boom"))

        with pytest.raises(Exception):
            await retry_with_backoff(op, max_retries=2, backoff_base_seconds=1.0)

        assert op.call_count == 2
        assert mock_sleep.call_count == 1  # only 1 sleep between 2 attempts

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_max_retries_one_means_no_retry(self, mock_sleep):
        """max_retries=1 means one attempt total, no retries."""
        op = AsyncMock(side_effect=Exception("boom"))

        with pytest.raises(Exception):
            await retry_with_backoff(op, max_retries=1)

        assert op.call_count == 1
        mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Backoff timing
# ---------------------------------------------------------------------------

class TestRetryBackoffTiming:

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_default_backoff_is_one_two_four(self, mock_sleep):
        op = AsyncMock(side_effect=[Exception(), Exception(), Exception(), "ok"])

        await retry_with_backoff(op, max_retries=4, backoff_base_seconds=1.0)

        waits = [c.args[0] for c in mock_sleep.call_args_list]
        assert waits == [1.0, 2.0, 4.0]

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_custom_backoff_base_scales_correctly(self, mock_sleep):
        op = AsyncMock(side_effect=[Exception(), Exception(), "ok"])

        await retry_with_backoff(op, max_retries=3, backoff_base_seconds=0.5)

        waits = [c.args[0] for c in mock_sleep.call_args_list]
        assert waits == [0.5, 1.0]  # 0.5 * 2^0, 0.5 * 2^1


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TestRetryLogging:

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("shared.utils.retry.logger")
    async def test_logs_warning_on_each_retry(self, mock_logger, mock_sleep):
        op = AsyncMock(side_effect=[Exception("boom1"), Exception("boom2"), "ok"])

        await retry_with_backoff(op, max_retries=3, operation_name="my_op")

        assert mock_logger.warning.call_count == 2  # 2 retries, 2 warnings

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("shared.utils.retry.logger")
    async def test_log_includes_operation_name(self, mock_logger, mock_sleep):
        op = AsyncMock(side_effect=[Exception("boom"), "ok"])

        await retry_with_backoff(op, max_retries=2, operation_name="batch_create_urls")

        extra = mock_logger.warning.call_args.kwargs["extra"]
        assert extra["operation"] == "batch_create_urls"

    @pytest.mark.asyncio
    @patch("shared.utils.retry.asyncio.sleep", new_callable=AsyncMock)
    @patch("shared.utils.retry.logger")
    async def test_log_includes_attempt_and_wait_and_error(self, mock_logger, mock_sleep):
        op = AsyncMock(side_effect=[Exception("db down"), "ok"])

        await retry_with_backoff(op, max_retries=2, backoff_base_seconds=1.0)

        extra = mock_logger.warning.call_args.kwargs["extra"]
        assert extra["attempt"] == 1
        assert extra["wait_seconds"] == 1.0
        assert "db down" in extra["error"]