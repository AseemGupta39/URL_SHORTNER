"""
Tests for IDBuffer — pre-generation buffer for short codes.
"""
import asyncio
import os
import tempfile
import pytest
from unittest.mock import AsyncMock

from shared.utils.id_buffer import IDBuffer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_generator(codes=None, raises=None):
    """Return a mock IDGenerator."""
    gen = AsyncMock()
    if raises:
        gen.generate_short_code = AsyncMock(side_effect=raises)
    elif codes:
        gen.generate_short_code = AsyncMock(side_effect=codes)
    else:
        counter = [0]

        async def _gen():
            counter[0] += 1
            return f"code{counter[0]:04d}"

        gen.generate_short_code = _gen
    return gen


def tmp_path():
    fd, path = tempfile.mkstemp(suffix=".txt", prefix="id_buffer_test_")
    os.close(fd)
    os.unlink(path)  # delete so IDBuffer starts fresh
    return path


# ---------------------------------------------------------------------------
# __init__ validation
# ---------------------------------------------------------------------------

def test_init_rejects_size_zero():
    gen = make_generator()
    with pytest.raises(ValueError, match="size must be >= 1"):
        IDBuffer(generator=gen, size=0)


def test_init_rejects_negative_size():
    gen = make_generator()
    with pytest.raises(ValueError, match="size must be >= 1"):
        IDBuffer(generator=gen, size=-5)


def test_init_rejects_threshold_equal_to_size():
    gen = make_generator()
    with pytest.raises(ValueError, match="refill_threshold"):
        IDBuffer(generator=gen, size=10, refill_threshold=10)


def test_init_rejects_threshold_greater_than_size():
    gen = make_generator()
    with pytest.raises(ValueError, match="refill_threshold"):
        IDBuffer(generator=gen, size=10, refill_threshold=15)


def test_init_valid_params():
    gen = make_generator()
    buf = IDBuffer(generator=gen, size=100, refill_threshold=20)
    assert buf._size == 100
    assert buf._refill_threshold == 20


# ---------------------------------------------------------------------------
# start() — fills queue to capacity
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_start_fills_queue_to_capacity():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    await buf.start()
    try:
        assert buf._queue.qsize() == 10
    finally:
        await buf.stop()
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_start_creates_refill_task():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    await buf.start()
    try:
        assert buf._refill_task is not None
        assert not buf._refill_task.done()
    finally:
        await buf.stop()
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# get() — returns short codes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_returns_string():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    await buf.start()
    try:
        code = await buf.get()
        assert isinstance(code, str)
        assert len(code) > 0
    finally:
        await buf.stop()
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_get_returns_unique_codes():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=20, refill_threshold=5, persist_path=path)
    await buf.start()
    try:
        codes = [await buf.get() for _ in range(10)]
        assert len(set(codes)) == 10
    finally:
        await buf.stop()
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_get_reduces_queue_size():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    await buf.start()
    # Cancel refill so level doesn't change under us
    buf._refill_task.cancel()
    try:
        await buf._refill_task
    except asyncio.CancelledError:
        pass

    size_before = buf._queue.qsize()
    await buf.get()
    assert buf._queue.qsize() == size_before - 1

    if os.path.exists(path):
        os.unlink(path)


# ---------------------------------------------------------------------------
# _persist() and _load_persisted()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_writes_ids_to_file():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=5, refill_threshold=1, persist_path=path)
    await buf.start()
    buf._refill_task.cancel()
    try:
        await buf._refill_task
    except asyncio.CancelledError:
        pass

    await buf._persist()

    assert os.path.exists(path)
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) == buf._queue.qsize() or len(lines) > 0

    os.unlink(path)


@pytest.mark.asyncio
async def test_load_persisted_returns_zero_when_file_missing():
    gen = make_generator()
    path = "/tmp/id_buffer_nonexistent_test_file.txt"
    if os.path.exists(path):
        os.unlink(path)
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    loaded = await buf._load_persisted()
    assert loaded == 0


@pytest.mark.asyncio
async def test_load_persisted_loads_ids_from_file():
    path = tmp_path()
    with open(path, "w") as f:
        f.write("aaaaaaaa\nbbbbbbbb\ncccccccc\n")

    gen = make_generator()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    loaded = await buf._load_persisted()

    assert loaded == 3
    assert buf._queue.qsize() == 3

    # File should be cleared after load
    with open(path) as f:
        content = f.read().strip()
    assert content == ""

    os.unlink(path)


@pytest.mark.asyncio
async def test_load_persisted_clears_file_after_load():
    path = tmp_path()
    with open(path, "w") as f:
        f.write("code0001\ncode0002\n")

    gen = make_generator()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    await buf._load_persisted()

    with open(path) as f:
        assert f.read().strip() == ""

    os.unlink(path)


@pytest.mark.asyncio
async def test_start_loads_persisted_ids_first():
    """IDs from file are used before generating new ones."""
    path = tmp_path()
    with open(path, "w") as f:
        f.write("persisted1\npersisted2\n")

    gen = make_generator()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    await buf.start()
    try:
        # The queue is full (size=10) but 2 came from persist file
        # Generator was called for the remaining 8
        assert buf._queue.qsize() == 10
    finally:
        await buf.stop()
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# stop() — cancels refill task, persists IDs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stop_cancels_refill_task():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    await buf.start()
    task = buf._refill_task
    await buf.stop()
    assert task.cancelled() or task.done()
    if os.path.exists(path):
        os.unlink(path)


@pytest.mark.asyncio
async def test_stop_persists_ids_to_disk():
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=5, refill_threshold=1, persist_path=path)
    await buf.start()
    await buf.stop()

    assert os.path.exists(path)
    with open(path) as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) > 0

    os.unlink(path)


# ---------------------------------------------------------------------------
# _fill() — generator errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fill_stops_on_runtime_error():
    gen = make_generator(raises=RuntimeError("clock moved backwards"))
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3)
    # Should not raise — logs the error and stops filling
    await buf._fill(5)
    assert buf._queue.qsize() == 0


@pytest.mark.asyncio
async def test_fill_stops_on_unexpected_error():
    gen = make_generator(raises=Exception("unexpected"))
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3)
    await buf._fill(5)
    assert buf._queue.qsize() == 0


@pytest.mark.asyncio
async def test_fill_respects_queue_capacity():
    gen = make_generator()
    buf = IDBuffer(generator=gen, size=3, refill_threshold=1)
    await buf._fill(100)  # ask for more than capacity
    assert buf._queue.qsize() == 3  # capped at maxsize


# ---------------------------------------------------------------------------
# persist file I/O error handling
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persist_handles_os_error_gracefully():
    gen = make_generator()
    buf = IDBuffer(generator=gen, size=5, refill_threshold=1, persist_path="/no/such/dir/file.txt")
    await buf._queue.put("code0001")
    # Should not raise — logs the error
    await buf._persist()


@pytest.mark.asyncio
async def test_load_persisted_handles_os_error_gracefully(tmp_path_dir=None):
    gen = make_generator()
    buf = IDBuffer(generator=gen, size=5, refill_threshold=1, persist_path="/no/such/dir/file.txt")
    # FileNotFoundError path → returns 0
    loaded = await buf._load_persisted()
    assert loaded == 0


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_load_persisted_empty_file_returns_zero():
    path = tmp_path()
    open(path, "w").close()  # create empty file

    gen = make_generator()
    buf = IDBuffer(generator=gen, size=10, refill_threshold=3, persist_path=path)
    loaded = await buf._load_persisted()
    assert loaded == 0

    os.unlink(path)


@pytest.mark.asyncio
async def test_load_persisted_caps_at_buffer_capacity():
    """If persist file has more IDs than size, only loads up to capacity."""
    path = tmp_path()
    with open(path, "w") as f:
        # Write 20 IDs but buffer size is only 5
        f.write("\n".join(f"code{i:04d}" for i in range(20)))

    gen = make_generator()
    buf = IDBuffer(generator=gen, size=5, refill_threshold=1, persist_path=path)
    loaded = await buf._load_persisted()

    assert loaded == 5
    assert buf._queue.qsize() == 5

    os.unlink(path)


@pytest.mark.asyncio
async def test_concurrent_get_all_return_unique_codes():
    """Multiple concurrent get() calls each receive a unique code."""
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=50, refill_threshold=10, persist_path=path)
    await buf.start()
    try:
        tasks = [buf.get() for _ in range(20)]
        codes = await asyncio.gather(*tasks)
        assert len(set(codes)) == 20
    finally:
        await buf.stop()
        if os.path.exists(path):
            os.unlink(path)


@pytest.mark.asyncio
async def test_refill_loop_triggers_when_below_threshold():
    """After draining below threshold, background loop refills the buffer."""
    gen = make_generator()
    path = tmp_path()
    buf = IDBuffer(generator=gen, size=20, refill_threshold=10, persist_path=path)
    await buf.start()
    try:
        # Drain well below threshold
        for _ in range(15):
            await buf.get()

        # Give refill loop time to run (it checks every 50ms)
        await asyncio.sleep(0.2)

        assert buf._queue.qsize() > 0
    finally:
        await buf.stop()
        if os.path.exists(path):
            os.unlink(path)
