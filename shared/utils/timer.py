"""
Simple timer utility for performance measurement.

Used for logging operation durations and breakdowns in production.

Design Principles:
1. Store raw perf_counter values (highest precision), format on display
2. Time is always a delta between two points
3. Return absolute values (time can't be negative)
4. Force explicit parameter names to avoid confusion
5. Clear error messages for missing checkpoints
"""
import time
from typing import Dict


class Timer:
    """
    Lightweight timer for measuring operation performance.

    Creates a new timer instance per operation - safe for async/concurrent use
    since each function call gets its own Timer instance.

    Stores raw perf_counter timestamps, calculates durations on demand.

    Example:
        async def my_function():
            timer = Timer()

            await do_step_1()
            timer.checkpoint('step_1')

            await do_step_2()
            timer.checkpoint('step_2')

            logger.info(
                f"duration_ms={timer.total():.2f} | "
                f"breakdown: step_1={timer.elapsed(end='step_1'):.2f}ms, "
                f"step_2={timer.elapsed(end='step_2', start='step_1'):.2f}ms"
            )
    """

    # Reserved name for timer start
    _START_KEY = 'start'

    def __init__(self):
        """Initialize timer with current timestamp using perf_counter for precision."""
        self._start_time = time.perf_counter()
        self.checkpoints: Dict[str, float] = {}

    def checkpoint(self, name: str) -> float:
        """
        Record a checkpoint with current perf_counter timestamp.

        Args:
            name: Name of the checkpoint

        Returns:
            Raw perf_counter timestamp (use elapsed() for duration in ms)

        Raises:
            ValueError: If name is 'start' (reserved)
        """
        if name == self._START_KEY:
            raise ValueError(f"'{self._START_KEY}' is reserved. Use a different checkpoint name.")

        timestamp = time.perf_counter()
        self.checkpoints[name] = timestamp
        return timestamp

    def elapsed(self, *, end: str, start: str = 'start') -> float:
        """
        Calculate duration between two checkpoints in milliseconds.

        Args:
            end: End checkpoint name (required, keyword-only)
            start: Start checkpoint name (default: 'start' = timer creation)

        Returns:
            Absolute duration in milliseconds (always positive)

        Raises:
            KeyError: If checkpoint name not found (with helpful message)
        """
        # Get start time
        if start == self._START_KEY:
            start_time = self._start_time
        elif start in self.checkpoints:
            start_time = self.checkpoints[start]
        else:
            raise KeyError(
                f"Checkpoint '{start}' not found. "
                f"Available: ['start', {', '.join(repr(k) for k in self.checkpoints.keys())}]"
            )

        # Get end time
        if end in self.checkpoints:
            end_time = self.checkpoints[end]
        else:
            raise KeyError(
                f"Checkpoint '{end}' not found. "
                f"Available: ['start', {', '.join(repr(k) for k in self.checkpoints.keys())}]"
            )

        # Return absolute value (time can't be negative)
        return abs(end_time - start_time) * 1000

    def total(self) -> float:
        """
        Get total elapsed time since timer start.

        Returns:
            Elapsed time in milliseconds
        """
        return (time.perf_counter() - self._start_time) * 1000
