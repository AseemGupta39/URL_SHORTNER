"""
Tests for canonical log lines emitted by batch workers.

Every invocation of process_batch_from_queue / process_click_batch_from_queue
must emit exactly one INFO-level "canonical" log record carrying:
    batch_id, outcome, processed, failed_parse, queue_size_before,
    db_time_ms, duration_ms, worker

Covered outcomes: empty (size=0), empty (peek returns []),
all_parse_failed, success, failed (DB raises).
"""

import logging
import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from services.batch_processor.batch_worker import process_batch_from_queue
from services.batch_processor.click_worker import process_click_batch_from_queue


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_canonical_record(caplog) -> logging.LogRecord:
    """Return the single canonical log record from caplog (asserts exactly one)."""
    records = [r for r in caplog.records if r.message == "canonical"]
    assert len(records) == 1, f"expected exactly 1 canonical log, got {len(records)}"
    return records[0]


def make_url_item(short_code: str, url: str = "https://example.com") -> dict:
    return {
        "short_code": short_code,
        "original_url": url,
        "created_at": datetime.now().isoformat(),
        "request_id": "test-req-id",
    }


def make_click_item(short_code: str = "abc123") -> dict:
    return {
        "click_id": str(uuid.uuid4()),
        "short_code": short_code,
        "original_url": "https://example.com",
        "clicked_at": datetime.now().isoformat(),
        "ip_address": "127.0.0.1",
        "user_agent": "test-agent",
        "referrer": None,
        "request_id": "test-req-id",
    }


@pytest.fixture
def url_repo():
    repo = AsyncMock()
    repo.batch_create = AsyncMock(return_value=0)
    repo.get_pool_status = lambda: {"size": 10, "checked_out": 0}
    return repo


@pytest.fixture
def click_repo():
    repo = AsyncMock()
    repo.batch_create = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def queue():
    q = AsyncMock()
    q.size = AsyncMock(return_value=0)
    q.peek = AsyncMock(return_value=[])
    q.remove_first = AsyncMock(return_value=None)
    q.enqueue = AsyncMock(return_value=None)
    return q


@pytest.fixture
def dlq():
    q = AsyncMock()
    q.enqueue = AsyncMock(return_value=None)
    return q


# ---------------------------------------------------------------------------
# process_batch_from_queue — URL batch worker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_canonical_log_on_empty_queue(caplog, url_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=0)

    await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "empty"
    assert rec.processed == 0
    assert rec.failed_parse == 0
    assert rec.queue_size_before == 0
    assert rec.db_time_ms == 0.0
    assert rec.worker == "url_batch"
    # NOTE: batch_id is injected by the global LogRecord factory from the
    # contextvar (see shared/utils/logging_config.py). Factory is not installed
    # in isolated test runs, so we don't assert its presence here. In
    # production, every record carries batch_id automatically.
    assert isinstance(rec.duration_ms, float)


@pytest.mark.asyncio
async def test_batch_canonical_log_on_peek_empty(caplog, url_repo, queue, dlq):
    """Queue reports non-zero size but peek returns nothing (race / consumer)."""
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=5)
    queue.peek = AsyncMock(return_value=[])

    await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "empty"
    assert rec.processed == 0
    assert rec.queue_size_before == 5
    assert rec.worker == "url_batch"


@pytest.mark.asyncio
async def test_batch_canonical_log_on_all_parse_failed(caplog, url_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=2)
    queue.peek = AsyncMock(return_value=[{"garbage": "data"}, {"also": "bad"}])

    await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "all_parse_failed"
    assert rec.processed == 0
    assert rec.failed_parse == 2
    assert rec.queue_size_before == 2
    assert rec.worker == "url_batch"
    # Both failed items must land in DLQ
    assert dlq.enqueue.call_count == 2
    # DB never touched
    url_repo.batch_create.assert_not_called()


@pytest.mark.asyncio
async def test_batch_canonical_log_on_success(caplog, url_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    items = [make_url_item(f"code{i}") for i in range(3)]
    queue.size = AsyncMock(side_effect=[3, 0])  # before peek, after remove
    queue.peek = AsyncMock(return_value=items)
    url_repo.batch_create = AsyncMock(return_value=3)

    result = await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "success"
    assert rec.processed == 3
    assert rec.failed_parse == 0
    assert rec.queue_size_before == 3
    assert rec.db_time_ms >= 0.0
    assert rec.worker == "url_batch"
    queue.remove_first.assert_awaited_once_with(3)
    assert result["processed"] == 3


@pytest.mark.asyncio
async def test_batch_canonical_log_on_db_failure(caplog, url_repo, queue, dlq):
    """DB error: function re-raises, but canonical log still fires from finally."""
    caplog.set_level(logging.INFO)
    items = [make_url_item("code1"), make_url_item("code2")]
    queue.size = AsyncMock(return_value=2)
    queue.peek = AsyncMock(return_value=items)
    url_repo.batch_create = AsyncMock(side_effect=RuntimeError("db down"))

    with pytest.raises(RuntimeError, match="db down"):
        await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "failed"
    assert rec.processed == 0
    assert rec.failed_parse == 0
    assert rec.queue_size_before == 2
    assert rec.db_time_ms >= 0.0
    assert rec.worker == "url_batch"
    # Queue must NOT be consumed on DB failure (at-least-once delivery)
    queue.remove_first.assert_not_called()


@pytest.mark.asyncio
async def test_batch_canonical_log_partial_parse_then_success(
    caplog, url_repo, queue, dlq
):
    """One good item, one bad item → success with failed_parse=1."""
    caplog.set_level(logging.INFO)
    items = [make_url_item("good"), {"corrupt": True}]
    queue.size = AsyncMock(side_effect=[2, 0])
    queue.peek = AsyncMock(return_value=items)
    url_repo.batch_create = AsyncMock(return_value=1)

    await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "success"
    assert rec.processed == 1
    assert rec.failed_parse == 1
    assert dlq.enqueue.call_count == 1
    # remove_first must remove ALL peeked items, even unparseable ones
    queue.remove_first.assert_awaited_once_with(2)


# ---------------------------------------------------------------------------
# process_click_batch_from_queue — click analytics worker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_click_canonical_log_on_empty_queue(caplog, click_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=0)

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "empty"
    assert rec.processed == 0
    assert rec.queue_size_before == 0
    assert rec.worker == "click_batch"


@pytest.mark.asyncio
async def test_click_canonical_log_on_peek_empty(caplog, click_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=4)
    queue.peek = AsyncMock(return_value=[])

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "empty"
    assert rec.queue_size_before == 4
    assert rec.worker == "click_batch"


@pytest.mark.asyncio
async def test_click_canonical_log_on_all_parse_failed(
    caplog, click_repo, queue, dlq
):
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(side_effect=[2, 2])  # before peek, after parse-fail
    queue.peek = AsyncMock(return_value=[{"bad": 1}, {"worse": 2}])

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "all_parse_failed"
    assert rec.processed == 0
    assert rec.failed_parse == 2
    assert rec.queue_size_before == 2
    assert rec.worker == "click_batch"
    assert dlq.enqueue.call_count == 2
    click_repo.batch_create.assert_not_called()


@pytest.mark.asyncio
async def test_click_canonical_log_on_success(caplog, click_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    items = [make_click_item(f"c{i}") for i in range(3)]
    queue.size = AsyncMock(side_effect=[3, 0])
    queue.peek = AsyncMock(return_value=items)
    click_repo.batch_create = AsyncMock(return_value=3)

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "success"
    assert rec.processed == 3
    assert rec.failed_parse == 0
    assert rec.queue_size_before == 3
    assert rec.db_time_ms >= 0.0
    assert rec.worker == "click_batch"
    queue.remove_first.assert_awaited_once_with(3)


@pytest.mark.asyncio
async def test_click_canonical_log_on_db_failure(caplog, click_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    items = [make_click_item("c1"), make_click_item("c2")]
    queue.size = AsyncMock(return_value=2)
    queue.peek = AsyncMock(return_value=items)
    click_repo.batch_create = AsyncMock(side_effect=RuntimeError("click db down"))

    with pytest.raises(RuntimeError, match="click db down"):
        await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "failed"
    assert rec.processed == 0
    assert rec.failed_parse == 0
    assert rec.queue_size_before == 2
    assert rec.db_time_ms >= 0.0
    assert rec.worker == "click_batch"
    queue.remove_first.assert_not_called()


# ---------------------------------------------------------------------------
# Cross-cutting: canonical record is the LAST log line (so finally fired last)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_canonical_log_is_emitted_last(caplog, url_repo, queue, dlq):
    """Canonical record must be the final INFO record — proves finally ran last."""
    caplog.set_level(logging.INFO)
    items = [make_url_item("code1")]
    queue.size = AsyncMock(side_effect=[1, 0])
    queue.peek = AsyncMock(return_value=items)
    url_repo.batch_create = AsyncMock(return_value=1)

    await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info_records[-1].message == "canonical"


# ---------------------------------------------------------------------------
# High-collision-risk edge cases — these stress the finally block under
# various failure modes, including paths where the worker raises before
# `outcome` is set to a meaningful value.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_canonical_log_when_queue_size_raises(caplog, url_repo, queue, dlq):
    """
    URL worker has NO outer except. If queue.size() raises BEFORE any
    outcome is set, the canonical log fires with outcome='unknown' and
    the exception propagates.
    """
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(side_effect=RuntimeError("redis down"))

    with pytest.raises(RuntimeError, match="redis down"):
        await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "unknown"
    assert rec.processed == 0
    assert rec.queue_size_before == 0
    assert rec.worker == "url_batch"


@pytest.mark.asyncio
async def test_batch_canonical_log_when_peek_raises(caplog, url_repo, queue, dlq):
    """queue.peek() raises after a successful size() call — outcome='unknown'."""
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=5)
    queue.peek = AsyncMock(side_effect=RuntimeError("peek failed"))

    with pytest.raises(RuntimeError, match="peek failed"):
        await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "unknown"
    assert rec.queue_size_before == 5
    queue.remove_first.assert_not_called()


@pytest.mark.asyncio
async def test_batch_canonical_log_when_remove_first_raises_after_db_success(
    caplog, url_repo, queue, dlq
):
    """
    LATENT BUG locked in: DB write succeeds, then queue.remove_first raises.
    Canonical reports outcome='failed' and processed=0 even though the rows
    ARE in the DB. The data isn't lost — but the canonical log is misleading
    and downstream alerting will treat it as a failure.
    """
    caplog.set_level(logging.INFO)
    items = [make_url_item("code1"), make_url_item("code2")]
    queue.size = AsyncMock(return_value=2)
    queue.peek = AsyncMock(return_value=items)
    queue.remove_first = AsyncMock(side_effect=RuntimeError("redis dequeue down"))
    url_repo.batch_create = AsyncMock(return_value=2)

    with pytest.raises(RuntimeError, match="redis dequeue down"):
        await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "failed"
    assert rec.processed == 0  # misleading — DB actually got the 2 rows
    assert rec.db_time_ms >= 0.0
    # DB DID get called — proves the misleading reporting
    url_repo.batch_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_canonical_log_when_dlq_enqueue_fails(
    caplog, url_repo, queue, dlq
):
    """
    Parse fails → worker tries to push to DLQ → DLQ enqueue ALSO fails.
    Per current code, DLQ failure is swallowed (logger.critical only).
    Batch continues; canonical reflects whatever final outcome was reached.
    Here: every item bad → all_parse_failed.
    """
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=1)
    queue.peek = AsyncMock(return_value=[{"corrupt": True}])
    dlq.enqueue = AsyncMock(side_effect=RuntimeError("dlq down"))

    # Must NOT raise — DLQ failure is intentionally swallowed
    await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "all_parse_failed"
    assert rec.processed == 0
    assert rec.failed_parse == 1
    # Confirm DLQ was attempted (the swallow point)
    dlq.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_batch_canonical_log_when_batch_create_returns_zero(
    caplog, url_repo, queue, dlq
):
    """
    Idempotent insert (INSERT ON CONFLICT DO NOTHING) returns 0 when every
    row already exists. No exception raised. outcome='success', processed=0.
    """
    caplog.set_level(logging.INFO)
    items = [make_url_item(f"code{i}") for i in range(3)]
    queue.size = AsyncMock(side_effect=[3, 0])
    queue.peek = AsyncMock(return_value=items)
    url_repo.batch_create = AsyncMock(return_value=0)

    await process_batch_from_queue(url_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "success"
    assert rec.processed == 0
    assert rec.failed_parse == 0
    # remove_first still called — we DID successfully process these items
    queue.remove_first.assert_awaited_once_with(3)


# ---------------------------------------------------------------------------
# Click worker — same edge cases, plus the parity tests it lacked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_click_canonical_log_partial_parse_then_success(
    caplog, click_repo, queue, dlq
):
    """One good item, one bad item → success with failed_parse=1."""
    caplog.set_level(logging.INFO)
    items = [make_click_item("good"), {"corrupt": True}]
    queue.size = AsyncMock(side_effect=[2, 0])
    queue.peek = AsyncMock(return_value=items)
    click_repo.batch_create = AsyncMock(return_value=1)

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "success"
    assert rec.processed == 1
    assert rec.failed_parse == 1
    assert rec.worker == "click_batch"
    assert dlq.enqueue.call_count == 1
    queue.remove_first.assert_awaited_once_with(2)


@pytest.mark.asyncio
async def test_click_canonical_log_is_emitted_last(caplog, click_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    items = [make_click_item("c1")]
    queue.size = AsyncMock(side_effect=[1, 0])
    queue.peek = AsyncMock(return_value=items)
    click_repo.batch_create = AsyncMock(return_value=1)

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert info_records[-1].message == "canonical"


@pytest.mark.asyncio
async def test_click_canonical_log_when_queue_size_raises(
    caplog, click_repo, queue, dlq
):
    """
    Click worker DOES have an outer except — it sets outcome='failed' before
    the finally runs. This is the asymmetry vs URL worker (which leaves it
    at 'unknown').
    """
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(side_effect=RuntimeError("redis down"))

    with pytest.raises(RuntimeError, match="redis down"):
        await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "failed"  # NOT 'unknown' like URL worker
    assert rec.worker == "click_batch"


@pytest.mark.asyncio
async def test_click_canonical_log_when_peek_raises(caplog, click_repo, queue, dlq):
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(return_value=5)
    queue.peek = AsyncMock(side_effect=RuntimeError("peek failed"))

    with pytest.raises(RuntimeError, match="peek failed"):
        await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "failed"
    assert rec.queue_size_before == 5
    queue.remove_first.assert_not_called()


@pytest.mark.asyncio
async def test_click_canonical_log_when_remove_first_raises_after_db_success(
    caplog, click_repo, queue, dlq
):
    """LATENT BUG: same as URL worker — DB succeeded, outcome reported as failed."""
    caplog.set_level(logging.INFO)
    items = [make_click_item("c1"), make_click_item("c2")]
    queue.size = AsyncMock(return_value=2)
    queue.peek = AsyncMock(return_value=items)
    queue.remove_first = AsyncMock(side_effect=RuntimeError("redis dequeue down"))
    click_repo.batch_create = AsyncMock(return_value=2)

    with pytest.raises(RuntimeError, match="redis dequeue down"):
        await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "failed"
    assert rec.processed == 0  # misleading
    click_repo.batch_create.assert_awaited_once()


@pytest.mark.asyncio
async def test_click_canonical_log_when_dlq_enqueue_fails(
    caplog, click_repo, queue, dlq
):
    """Click parse fails → DLQ also fails → outcome=all_parse_failed, no raise."""
    caplog.set_level(logging.INFO)
    queue.size = AsyncMock(side_effect=[1, 1])
    queue.peek = AsyncMock(return_value=[{"corrupt": True}])
    dlq.enqueue = AsyncMock(side_effect=RuntimeError("dlq down"))

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "all_parse_failed"
    assert rec.failed_parse == 1
    dlq.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_click_canonical_log_when_batch_create_returns_zero(
    caplog, click_repo, queue, dlq
):
    """Click idempotent insert returns 0 → outcome=success, processed=0."""
    caplog.set_level(logging.INFO)
    items = [make_click_item(f"c{i}") for i in range(3)]
    queue.size = AsyncMock(side_effect=[3, 0])
    queue.peek = AsyncMock(return_value=items)
    click_repo.batch_create = AsyncMock(return_value=0)

    await process_click_batch_from_queue(click_repo, queue, dlq, batch_size=10)

    rec = get_canonical_record(caplog)
    assert rec.outcome == "success"
    assert rec.processed == 0
    queue.remove_first.assert_awaited_once_with(3)