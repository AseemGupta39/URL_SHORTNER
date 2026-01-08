"""
Simple timer utility for performance measurement.

Used for logging operation durations and breakdowns in production.
"""
import time
from typing import Dict


class Timer:
    """
    Lightweight timer for measuring operation performance.

    Creates a new timer instance per operation - safe for async/concurrent use
    since each function call gets its own Timer instance.

    Example:
        async def my_function():
            timer = Timer()

            await do_step_1()
            timer.checkpoint('step_1')

            await do_step_2()
            timer.checkpoint('step_2')

            logger.info(
                f"duration_ms={timer.total():.2f} | "
                f"breakdown: step_1={timer.checkpoints['step_1']:.2f}ms, "
                f"step_2={timer.checkpoints['step_2']:.2f}ms"
            )
    """

    def __init__(self):
        """Initialize timer with current timestamp."""
        self.start = time.time()
        self.checkpoints: Dict[str, float] = {}

    def checkpoint(self, name: str) -> float:
        """
        Record a checkpoint with elapsed time since timer start.

        Args:
            name: Name of the checkpoint

        Returns:
            Elapsed time in milliseconds since timer start
        """
        elapsed_ms = (time.time() - self.start) * 1000
        self.checkpoints[name] = elapsed_ms
        return elapsed_ms

    def total(self) -> float:
        """
        Get total elapsed time since timer start.

        Returns:
            Elapsed time in milliseconds
        """
        return (time.time() - self.start) * 1000
