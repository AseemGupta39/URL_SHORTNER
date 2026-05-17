"""
ID Pre-Generation Buffer.

Eliminates the asyncio.Lock bottleneck from SnowflakeIDGenerator by
pre-generating short codes into an asyncio.Queue. The hot path calls
await buffer.get() (~0ms) instead of awaiting generate_short_code()
which holds a lock.

Persist/reload: unused IDs are written to a per-worker file on shutdown
and reloaded on startup. This is Lambda/cold-start safe — on restart
the buffer is immediately available from the persisted file rather than
regenerating from scratch under load.

Per-worker file path prevents race conditions when multiple workers
share the same filesystem (e.g. 4 uvicorn workers on the same machine).
"""
import asyncio
import logging

from shared.utils.interfaces.id_generator import IDGenerator

logger = logging.getLogger(__name__)


class IDBuffer:
    """
    Pre-generates short codes into an asyncio.Queue.

    Hot path:   await buffer.get()  → ~0ms, no lock
    Background: refills queue when level drops below threshold
    Shutdown:   persists unused IDs to a per-worker disk file
    Startup:    reloads persisted IDs before generating fresh ones

    Expected input:
        - generator (IDGenerator): source of short codes
        - size (int): max IDs to keep pre-generated (default 1000)
        - refill_threshold (int): refill when level drops below this (default 200)
        - persist_path (str): file path for unused ID persistence on shutdown

    Expected output:
        - IDBuffer instance (call await start() before use)
    """

    def __init__(
        self,
        generator: IDGenerator,
        size: int = 2000,
        refill_threshold: int = 700,
        persist_path: str = "/tmp/id_buffer.txt",
    ) -> None:
        """
        Initialize IDBuffer. Call await start() to begin pre-generation.

        Expected input:
            - generator (IDGenerator): ID generator instance
            - size (int): queue capacity
            - refill_threshold (int): trigger refill below this level
            - persist_path (str): per-worker file path (must be unique per worker)

        Expected output:
            - None
        """
        # Guard: size must be positive
        if size < 1:
            raise ValueError(f"IDBuffer: size must be >= 1, got {size}")

        # Guard: threshold must be less than size to avoid infinite refill loop
        if refill_threshold >= size:
            raise ValueError(
                f"IDBuffer: refill_threshold ({refill_threshold}) must be < size ({size})"
            )

        self._generator: IDGenerator = generator
        self._size: int = size
        self._refill_threshold: int = refill_threshold
        self._persist_path: str = persist_path
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=size)
        self._refill_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """
        Load persisted IDs, fill remainder to capacity, start background refiller.
        Must be called once during service startup before serving requests.
        """
        loaded = await self._load_persisted()

        # Fill remaining capacity with fresh IDs
        remaining = self._size - self._queue.qsize()
        if remaining > 0:
            await self._fill(remaining)

        self._refill_task = asyncio.create_task(
            self._refill_loop(), name="id_buffer_refill"
        )
        logger.info("IDBuffer started", extra={"loaded": loaded, "level": self._queue.qsize(), "capacity": self._size, "persist_path": self._persist_path})

    async def stop(self) -> None:
        """
        Cancel background refill task and persist unused IDs to disk.
        Must be called during service shutdown.
        """
        if self._refill_task:
            self._refill_task.cancel()
            try:
                await self._refill_task
            except asyncio.CancelledError:
                pass  # expected — task was cancelled intentionally

        await self._persist()

    async def get(self) -> str:
        """
        Get a pre-generated short code from the buffer.
        Near-instant (~0ms), no lock held.

        Expected output:
            - str: 8-character base62 short code
        """
        return await self._queue.get()

    async def _fill(self, count: int) -> None:
        """
        Generate up to `count` short codes and add them to the queue.

        Expected input:
            - count (int): number of IDs to generate

        Expected output:
            - None (modifies internal queue)
        """
        generated = 0
        for _ in range(count):
            if self._queue.full():
                break
            try:
                code = await self._generator.generate_short_code()
                await self._queue.put(code)
                generated += 1
            except RuntimeError as e:
                # RuntimeError from generator = clock moved backwards or timestamp overflow
                logger.error("IDBuffer generator raised RuntimeError during fill, stopping", extra={"error": str(e)})
                break
            except Exception as e:
                logger.error("IDBuffer unexpected error during fill", extra={"generated": generated, "error": str(e)}, exc_info=True)
                break

        logger.debug("IDBuffer filled", extra={"generated": generated, "level": self._queue.qsize()})

    async def _refill_loop(self) -> None:
        """
        Background task that watches buffer level and refills when below threshold.
        Runs until cancelled by stop().

        Expected input:
            - None (runs indefinitely until cancelled)

        Expected output:
            - None
        """
        while True:
            try:
                if self._queue.qsize() < self._refill_threshold:
                    needed = self._size - self._queue.qsize()
                    logger.debug("IDBuffer level below threshold, refilling", extra={"level": self._queue.qsize(), "threshold": self._refill_threshold, "needed": needed})
                    await self._fill(needed)
                await asyncio.sleep(0.05)  # check every 50ms
            except asyncio.CancelledError:
                break  # stop() called — exit cleanly
            except Exception as e:
                logger.error("IDBuffer refill loop unexpected error", extra={"error": str(e)}, exc_info=True)
                await asyncio.sleep(0.1)  # back off before retrying

    async def _persist(self) -> None:
        """
        Drain queue and write all unused IDs to the persist file.
        Called during shutdown so they can be reloaded on restart.

        Expected input:
            - None

        Expected output:
            - None (writes to persist_path)
        """
        ids: list[str] = []
        while not self._queue.empty():
            ids.append(self._queue.get_nowait())

        try:
            with open(self._persist_path, "w") as f:
                f.write("\n".join(ids))
            logger.info("IDBuffer persisted unused IDs", extra={"count": len(ids), "persist_path": self._persist_path})
        except OSError as e:
            logger.error("IDBuffer failed to persist IDs", extra={"count": len(ids), "persist_path": self._persist_path, "error": str(e)})

    async def _load_persisted(self) -> int:
        """
        Load previously persisted IDs from disk into the queue.
        Clears the file after loading to avoid reuse across restarts.

        Expected input:
            - None

        Expected output:
            - int: number of IDs loaded (0 if file missing or empty)
        """
        try:
            with open(self._persist_path, "r") as f:
                ids = [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            # Normal on first start — no persisted IDs yet
            return 0
        except OSError as e:
            logger.error("IDBuffer failed to read persisted IDs", extra={"persist_path": self._persist_path, "error": str(e)})
            return 0

        loaded = 0
        for code in ids:
            if self._queue.full():
                break
            await self._queue.put(code)
            loaded += 1

        # Clear file after loading — avoids reusing stale IDs on next restart
        try:
            open(self._persist_path, "w").close()
        except OSError as e:
            logger.warning("IDBuffer could not clear persist file", extra={"persist_path": self._persist_path, "error": str(e)})

        logger.info("IDBuffer loaded persisted IDs", extra={"loaded": loaded, "persist_path": self._persist_path})
        return loaded
