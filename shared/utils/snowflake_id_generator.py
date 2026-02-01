import time
import asyncio
import logging

from shared.utils.interfaces.id_generator import IDGenerator
from shared.utils.timer import Timer
from shared.utils.base_encoder import BaseEncoder

logger = logging.getLogger(__name__)


class SnowflakeIDGenerator(IDGenerator):
    """
    8-char Snowflake ID generator using adjusted bit allocation with SECOND precision:
    - 31 bits: timestamp in SECONDS (~50 years from epoch)
    - 4 bits: datacenter_id (16 data centers, 0-15)
    - 2 bits: worker_id (4 workers per DC, 0-3)
    - 10 bits: sequence (1024 IDs/second/worker, 0-1023)

    Total capacity: 16 DCs × 4 workers × 1024 = 65,536 IDs/second
    Base62 encoding produces 8-character codes
    """

    # Default epoch: 2024-01-01 00:00:00 UTC

    def __init__(
        self,
        datacenter_id: int,
        worker_id: int,
        epoch_sec: int = 1704067200,
        timestamp_bits: int = 31,
        datacenter_bits: int = 4,
        worker_bits: int = 2,
        sequence_bits: int = 10
    ):
        """
        Initialize Snowflake ID generator

        Args:
            datacenter_id: Data center ID (0-15)
            worker_id: Worker ID (0-3)
            epoch_sec: Custom epoch in seconds (default: 2024-01-01 00:00:00 UTC = 1704067200)
            timestamp_bits: Bits for timestamp (default: 31 for around 50 years)
            datacenter_bits: Bits for datacenter ID (default: 4)
            worker_bits: Bits for worker ID (default: 2)
            sequence_bits: Bits for sequence (default: 10)

        Raises:
            ValueError: If datacenter_id or worker_id out of range
        """
        # Bit allocation
        self.timestamp_bits = timestamp_bits
        self.datacenter_bits = datacenter_bits
        self.worker_bits = worker_bits
        self.sequence_bits = sequence_bits

        # Bit shifts (use instance values to avoid mismatch)
        self.timestamp_shift = self.datacenter_bits + self.worker_bits + self.sequence_bits
        self.datacenter_shift = self.worker_bits + self.sequence_bits
        self.worker_shift = self.sequence_bits

        # Max values (derived from instance bit sizes)
        self.max_datacenter_id = (1 << self.datacenter_bits) - 1
        self.max_worker_id = (1 << self.worker_bits) - 1
        self.max_sequence = (1 << self.sequence_bits) - 1
        self.max_timestamp = (1 << self.timestamp_bits) - 1

        if datacenter_id < 0 or datacenter_id > self.max_datacenter_id:
            raise ValueError(f"datacenter_id must be 0-{self.max_datacenter_id}")

        if worker_id < 0 or worker_id > self.max_worker_id:
            raise ValueError(f"worker_id must be 0-{self.max_worker_id}")

        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self.epoch_sec = epoch_sec

        self.sequence = 0
        self.last_timestamp = -1
        self._lock = asyncio.Lock()

        # Initialize Base62 encoder with 8-character padding
        self._encoder = BaseEncoder(base=62, padding=8)

        # Log initialization details
        logger.info(
            f"SnowflakeIDGenerator initialized: DC={datacenter_id}, W={worker_id}, "
            f"epoch={epoch_sec}, bits=[ts:{timestamp_bits}, dc:{datacenter_bits}, "
            f"w:{worker_bits}, seq:{sequence_bits}]"
        )
        logger.info(
            f"Max values: DC={self.max_datacenter_id}, W={self.max_worker_id}, "
            f"seq={self.max_sequence}, timestamp={self.max_timestamp}"
        )

    def _current_timestamp_sec(self) -> int:
        """Get current timestamp in seconds"""
        return int(time.time())

    async def _wait_next_second(self, last_timestamp: int) -> int:
        """
        Wait until next second (async, non-blocking).

        Uses asyncio.sleep() to prevent blocking the event loop during wait.
        """
        timestamp = self._current_timestamp_sec()
        while timestamp <= last_timestamp:
            await asyncio.sleep(0.010)  # Sleep 10ms - sweet spot for CPU efficiency while avoiding busy-wait
            timestamp = self._current_timestamp_sec()
        return timestamp

    async def generate_id(self) -> int:
        """
        Generate unique ID (bits determined by configured bit fields)

        Returns:
            int: Unique integer ID that encodes to an 8-character base62 string

        Raises:
            RuntimeError: If clock moves backwards or timestamp exceeds max
        """
        timer = Timer()

        async with self._lock:
            timer.checkpoint('lock_acquired')

            timestamp = self._current_timestamp_sec()

            # Clock moved backwards
            if timestamp < self.last_timestamp:
                logger.error(
                    f"Clock moved backwards! Last={self.last_timestamp}, Current={timestamp}, "
                    f"Diff={self.last_timestamp - timestamp}s"
                )
                raise RuntimeError(
                    f"Clock moved backwards. Refusing to generate ID. "
                    f"Last: {self.last_timestamp}, Current: {timestamp}"
                )

            # Same second - increment sequence
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.max_sequence

                # Sequence exhausted - wait for next second
                if self.sequence == 0:
                    logger.warning(
                        f"Sequence exhausted ({self.max_sequence + 1} IDs/sec), waiting for next second"
                    )
                    timestamp = await self._wait_next_second(self.last_timestamp)
            else:
                # New second - reset sequence
                self.sequence = 0

            self.last_timestamp = timestamp

            # Calculate relative timestamp
            relative_timestamp = timestamp - self.epoch_sec

            # Check timestamp overflow
            if relative_timestamp > self.max_timestamp:
                logger.error(
                    f"Timestamp overflow! Relative={relative_timestamp}, Max={self.max_timestamp}"
                )
                raise RuntimeError(
                    f"Timestamp overflow. Relative timestamp {relative_timestamp} "
                    f"exceeds max {self.max_timestamp}"
                )

            if relative_timestamp < 0:
                logger.error(
                    f"Timestamp before epoch! Current={timestamp}, Epoch={self.epoch_sec}"
                )
                raise RuntimeError(
                    f"Current timestamp {timestamp} is before epoch {self.epoch_sec}"
                )

            # Compose integer ID from components (timestamp/datacenter/worker/sequence)
            id_value = (
                (relative_timestamp << self.timestamp_shift) |
                (self.datacenter_id << self.datacenter_shift) |
                (self.worker_id << self.worker_shift) |
                self.sequence
            )

            timer.checkpoint('work_done')

        # Timing logged outside lock
        timer.checkpoint('lock_released')

        wait_time = timer.elapsed(end='lock_acquired')
        work_time = timer.elapsed(end='work_done', start='lock_acquired')
        release_time = timer.elapsed(end='lock_released', start='work_done')

        # Log timing for slow requests (>50ms wait = likely contention)
        if wait_time > 50:
            logger.warning(
                f"ID Gen SLOW: wait={wait_time:.2f}ms, work={work_time:.2f}ms, "
                f"release={release_time:.2f}ms, seq={self.sequence}"
            )
        else:
            logger.debug(
                f"Generated ID: {id_value} [ts={relative_timestamp}, dc={self.datacenter_id}, "
                f"w={self.worker_id}, seq={self.sequence}] | "
                f"wait={wait_time:.2f}ms, work={work_time:.2f}ms"
            )

        return id_value

    def encode_base62(self, num: int) -> str:
        """
        Encode number to base62 string

        Args:
            num: Number to encode

        Returns:
            str: Base62 encoded string (8 characters for 47-bit IDs)
        """
        return self._encoder.encode(num)

    def decode_base62(self, code: str) -> int:
        """
        Decode base62 string to number

        Args:
            code: Base62 encoded string

        Returns:
            int: Decoded number
        """
        return self._encoder.decode(code)

    def extract_components(self, id_value: int) -> dict:
        """
        Extract components from ID

        Args:
            id_value: Generated ID

        Returns:
            dict: Components (timestamp, datacenter_id, worker_id, sequence)
        """
        timestamp = (id_value >> self.timestamp_shift) & self.max_timestamp
        datacenter_id = (id_value >> self.datacenter_shift) & self.max_datacenter_id
        worker_id = (id_value >> self.worker_shift) & self.max_worker_id
        sequence = id_value & self.max_sequence

        return {
            'timestamp': timestamp,
            'datacenter_id': datacenter_id,
            'worker_id': worker_id,
            'sequence': sequence
        }

    async def generate_short_code(self) -> str:
        """
        Generate 8-character short code

        Returns:
            str: 8-character base62 short code
        """
        id_value = await self.generate_id()
        short_code = self.encode_base62(id_value)
        logger.debug(f"Generated short code: {short_code} (ID={id_value})")
        return short_code
