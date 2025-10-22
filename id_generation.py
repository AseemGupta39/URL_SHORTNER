from abc import ABC, abstractmethod
import time
import asyncio


class IDGenerator(ABC):
    """Abstract base class for distributed ID generation"""

    @abstractmethod
    async def generate_id(self) -> int:
        """Generate unique numeric ID across workers"""
        pass

    @abstractmethod
    async def generate_short_code(self) -> str:
        """
        Generate unique short code (base62 encoded).

        Convenience method that generates ID and encodes it.
        Primary method for service layer usage.
        """
        pass


class SnowflakeIDGenerator(IDGenerator):
    """
    7-char Snowflake ID generator using 41-bit strategy with SECOND precision:
    - 28 bits: timestamp in SECONDS (8.51 years from epoch)
    - 4 bits: datacenter_id (16 data centers, 0-15)
    - 2 bits: worker_id (4 workers per DC, 0-3)
    - 7 bits: sequence (128 IDs/second/worker, 0-127)

    Total capacity: 8,192 IDs/second across all DCs
    Base62 encoding produces 7-character codes
    """

    # Base62 alphabet
    BASE62_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    # Default epoch: 2024-01-01 00:00:00 UTC

    def __init__(
        self,
        datacenter_id: int,
        worker_id: int,
        epoch_sec: int = 1704067200,
        timestamp_bits: int = 28,
        datacenter_bits: int = 4,
        worker_bits: int = 2,
        sequence_bits: int = 7
    ):
        """
        Initialize Snowflake ID generator

        Args:
            datacenter_id: Data center ID (0-15)
            worker_id: Worker ID (0-3)
            epoch_sec: Custom epoch in seconds (default: 2024-01-01 00:00:00 UTC = 1704067200)
            timestamp_bits: Bits for timestamp (default: 28 for 8.51 years)
            datacenter_bits: Bits for datacenter ID (default: 4)
            worker_bits: Bits for worker ID (default: 2)
            sequence_bits: Bits for sequence (default: 7)

        Raises:
            ValueError: If datacenter_id or worker_id out of range
        """
        # Bit allocation
        self.timestamp_bits = timestamp_bits
        self.datacenter_bits = datacenter_bits
        self.worker_bits = worker_bits
        self.sequence_bits = sequence_bits

        # Bit shifts
        self.timestamp_shift = datacenter_bits + worker_bits + sequence_bits
        self.datacenter_shift = worker_bits + sequence_bits
        self.worker_shift = sequence_bits

        # Max values
        self.max_datacenter_id = (1 << datacenter_bits) - 1
        self.max_worker_id = (1 << worker_bits) - 1
        self.max_sequence = (1 << sequence_bits) - 1
        self.max_timestamp = (1 << timestamp_bits) - 1

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

    def _current_timestamp_sec(self) -> int:
        """Get current timestamp in seconds"""
        return int(time.time())

    def _wait_next_second(self, last_timestamp: int) -> int:
        """Wait until next second"""
        timestamp = self._current_timestamp_sec()
        while timestamp <= last_timestamp:
            timestamp = self._current_timestamp_sec()
        return timestamp

    async def generate_id(self) -> int:
        """
        Generate unique 41-bit ID

        Returns:
            int: Unique ID that encodes to 7 base62 characters

        Raises:
            RuntimeError: If clock moves backwards or timestamp exceeds max
        """
        async with self._lock:
            timestamp = self._current_timestamp_sec()

            # Clock moved backwards
            if timestamp < self.last_timestamp:
                raise RuntimeError(
                    f"Clock moved backwards. Refusing to generate ID. "
                    f"Last: {self.last_timestamp}, Current: {timestamp}"
                )

            # Same second - increment sequence
            if timestamp == self.last_timestamp:
                self.sequence = (self.sequence + 1) & self.max_sequence

                # Sequence exhausted - wait for next second
                if self.sequence == 0:
                    timestamp = self._wait_next_second(self.last_timestamp)
            else:
                # New second - reset sequence
                self.sequence = 0

            self.last_timestamp = timestamp

            # Calculate relative timestamp
            relative_timestamp = timestamp - self.epoch_sec

            # Check timestamp overflow
            if relative_timestamp > self.max_timestamp:
                raise RuntimeError(
                    f"Timestamp overflow. Relative timestamp {relative_timestamp} "
                    f"exceeds max {self.max_timestamp}"
                )

            if relative_timestamp < 0:
                raise RuntimeError(
                    f"Current timestamp {timestamp} is before epoch {self.epoch_sec}"
                )

            # Compose 41-bit ID
            id_value = (
                (relative_timestamp << self.timestamp_shift) |
                (self.datacenter_id << self.datacenter_shift) |
                (self.worker_id << self.worker_shift) |
                self.sequence
            )

            return id_value

    def encode_base62(self, num: int) -> str:
        """
        Encode number to base62 string

        Args:
            num: Number to encode

        Returns:
            str: Base62 encoded string (7 characters for 41-bit IDs)
        """
        if num == 0:
            return self.BASE62_ALPHABET[0].zfill(7)

        result = []
        while num > 0:
            result.append(self.BASE62_ALPHABET[num % 62])
            num //= 62

        # Pad to 7 characters
        code = ''.join(reversed(result))
        return code.zfill(7)

    def decode_base62(self, code: str) -> int:
        """
        Decode base62 string to number

        Args:
            code: Base62 encoded string

        Returns:
            int: Decoded number
        """
        num = 0
        for char in code:
            num = num * 62 + self.BASE62_ALPHABET.index(char)
        return num

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
        Generate 7-character short code

        Returns:
            str: 7-character base62 short code
        """
        id_value = await self.generate_id()
        return self.encode_base62(id_value)
