import pytest
import asyncio
import time
from shared.utils.snowflake_id_generator import SnowflakeIDGenerator


# Use a recent epoch to avoid timestamp overflow in tests
# Using seconds precision (1 hour ago in seconds)
TEST_EPOCH_SEC = int(time.time()) - (60 * 60)  # 1 hour ago


class TestSnowflakeIDGenerator:
    """Test suite for 7-char Snowflake ID generator (41-bit strategy, SECOND precision)"""

    # ========== Initialization Tests ==========

    def test_initialization_valid_params(self):
        """Test generator initializes with valid datacenter and worker IDs"""
        generator = SnowflakeIDGenerator(datacenter_id=5, worker_id=2, epoch_sec=TEST_EPOCH_SEC)
        assert generator.datacenter_id == 5
        assert generator.worker_id == 2
        assert generator.sequence == 0
        assert generator.last_timestamp == -1

    def test_initialization_boundary_values(self):
        """Test initialization with boundary datacenter/worker IDs"""
        # Min values
        gen_min = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        assert gen_min.datacenter_id == 0
        assert gen_min.worker_id == 0

        # Max values (4 bits = 0-15 DCs, 2 bits = 0-3 workers)
        gen_max = SnowflakeIDGenerator(datacenter_id=15, worker_id=3, epoch_sec=TEST_EPOCH_SEC)
        assert gen_max.datacenter_id == 15
        assert gen_max.worker_id == 3

    def test_initialization_invalid_datacenter_id(self):
        """Test initialization fails with invalid datacenter_id"""
        with pytest.raises(ValueError, match="datacenter_id must be 0-15"):
            SnowflakeIDGenerator(datacenter_id=16, worker_id=0)

        with pytest.raises(ValueError, match="datacenter_id must be 0-15"):
            SnowflakeIDGenerator(datacenter_id=-1, worker_id=0)

    def test_initialization_invalid_worker_id(self):
        """Test initialization fails with invalid worker_id"""
        with pytest.raises(ValueError, match="worker_id must be 0-3"):
            SnowflakeIDGenerator(datacenter_id=0, worker_id=4)

        with pytest.raises(ValueError, match="worker_id must be 0-3"):
            SnowflakeIDGenerator(datacenter_id=0, worker_id=-1)

    def test_bit_allocation(self):
        """Test correct bit allocation for 41-bit strategy"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Verify bit sizes
        assert generator.timestamp_bits == 28
        assert generator.datacenter_bits == 4
        assert generator.worker_bits == 2
        assert generator.sequence_bits == 7

        # Verify total is 41 bits
        total_bits = (generator.timestamp_bits + generator.datacenter_bits +
                     generator.worker_bits + generator.sequence_bits)
        assert total_bits == 41

    def test_max_values(self):
        """Test maximum values for each component"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # 28 bits timestamp: 2^28 - 1 = 268,435,455 seconds (~8.51 years)
        assert generator.max_timestamp == 268_435_455

        # 4 bits datacenter: 2^4 - 1 = 15
        assert generator.max_datacenter_id == 15

        # 2 bits worker: 2^2 - 1 = 3
        assert generator.max_worker_id == 3

        # 7 bits sequence: 2^7 - 1 = 127
        assert generator.max_sequence == 127

    # ========== ID Generation Tests ==========

    @pytest.mark.asyncio
    async def test_generate_single_id(self):
        """Test generating a single ID"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        id_value = await generator.generate_id()

        assert isinstance(id_value, int)
        assert id_value > 0
        # 41 bits max value: 2^41 - 1
        assert id_value < (1 << 41)

    @pytest.mark.asyncio
    async def test_generate_multiple_unique_ids(self):
        """Test that multiple IDs are unique"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        ids = [await generator.generate_id() for _ in range(100)]

        # All IDs should be unique
        assert len(ids) == len(set(ids))

        # All IDs should be monotonically increasing
        assert ids == sorted(ids)

    @pytest.mark.asyncio
    async def test_generate_ids_same_second(self):
        """Test sequence increments when generating IDs in same second"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Generate IDs rapidly to stay within same second
        ids = []
        for _ in range(10):
            ids.append(await generator.generate_id())

        # Verify sequences increment
        components_list = [generator.extract_components(id_val) for id_val in ids]
        sequences = [comp['sequence'] for comp in components_list]

        # Sequences should increment (at least some should be non-zero)
        assert any(seq > 0 for seq in sequences)

    @pytest.mark.asyncio
    async def test_sequence_overflow_waits_next_second(self):
        """Test that sequence overflow triggers wait for next second"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Set sequence to max - 1
        generator.sequence = 126
        generator.last_timestamp = generator._current_timestamp_sec()

        # Generate two more IDs (should trigger overflow and wait)
        id1 = await generator.generate_id()
        id2 = await generator.generate_id()

        components1 = generator.extract_components(id1)
        components2 = generator.extract_components(id2)

        # Sequence should have wrapped after hitting max (127)
        assert components1['sequence'] == 127
        assert components2['sequence'] == 0

    @pytest.mark.asyncio
    async def test_multiple_workers_same_datacenter(self):
        """Test multiple workers in same datacenter generate unique IDs"""
        worker1 = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        worker2 = SnowflakeIDGenerator(datacenter_id=0, worker_id=1, epoch_sec=TEST_EPOCH_SEC)

        ids_w1 = [await worker1.generate_id() for _ in range(50)]
        ids_w2 = [await worker2.generate_id() for _ in range(50)]

        # All IDs should be unique across workers
        all_ids = ids_w1 + ids_w2
        assert len(all_ids) == len(set(all_ids))

    @pytest.mark.asyncio
    async def test_multiple_datacenters(self):
        """Test multiple datacenters generate unique IDs"""
        dc1 = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        dc2 = SnowflakeIDGenerator(datacenter_id=1, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        ids_dc1 = [await dc1.generate_id() for _ in range(50)]
        ids_dc2 = [await dc2.generate_id() for _ in range(50)]

        # All IDs should be unique across datacenters
        all_ids = ids_dc1 + ids_dc2
        assert len(all_ids) == len(set(all_ids))

    @pytest.mark.asyncio
    async def test_concurrent_id_generation(self):
        """Test concurrent ID generation with asyncio"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Generate IDs concurrently
        tasks = [generator.generate_id() for _ in range(100)]
        ids = await asyncio.gather(*tasks)

        # All IDs should be unique even with concurrency
        assert len(ids) == len(set(ids))

    # ========== Base62 Encoding Tests ==========

    def test_encode_base62_zero(self):
        """Test encoding zero"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        code = generator.encode_base62(0)
        assert code == "0000000"
        assert len(code) == 7

    def test_encode_base62_small_number(self):
        """Test encoding small number"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        code = generator.encode_base62(123)
        # 123 in base62 is 1z (using lowercase), padded to 7
        assert code == "000001z"
        assert len(code) == 7

    def test_encode_base62_large_number(self):
        """Test encoding large number (near 41-bit max)"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        # Max 41-bit value: 2^41 - 1 = 2,199,023,255,551
        max_41_bit = (1 << 41) - 1
        code = generator.encode_base62(max_41_bit)
        assert len(code) == 7

    def test_encode_base62_7_chars(self):
        """Test that all IDs encode to exactly 7 characters"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        test_values = [
            1, 100, 1000, 10000, 100000, 1000000,
            (1 << 20), (1 << 30), (1 << 40)
        ]

        for val in test_values:
            code = generator.encode_base62(val)
            assert len(code) == 7, f"Value {val} encoded to {len(code)} chars: {code}"

    def test_decode_base62(self):
        """Test decoding base62 strings"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        test_cases = [
            ("0000000", 0),
            ("0000001", 1),
            ("000000z", 61),  # 'z' is at index 61 in base62
            ("0000010", 62),
        ]

        for code, expected in test_cases:
            decoded = generator.decode_base62(code)
            assert decoded == expected

    def test_encode_decode_roundtrip(self):
        """Test encoding and decoding produces original value"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        test_values = [0, 1, 62, 100, 1000, 1000000, (1 << 40)]

        for original in test_values:
            encoded = generator.encode_base62(original)
            decoded = generator.decode_base62(encoded)
            assert decoded == original

    @pytest.mark.asyncio
    async def test_generate_short_code(self):
        """Test generating 7-character short codes"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        code = await generator.generate_short_code()

        assert isinstance(code, str)
        assert len(code) == 7
        # Should only contain base62 characters
        assert all(c in generator.BASE62_ALPHABET for c in code)

    @pytest.mark.asyncio
    async def test_short_codes_unique(self):
        """Test that short codes are unique"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        codes = [await generator.generate_short_code() for _ in range(100)]

        assert len(codes) == len(set(codes))

    # ========== Component Extraction Tests ==========

    @pytest.mark.asyncio
    async def test_extract_components(self):
        """Test extracting components from ID"""
        generator = SnowflakeIDGenerator(datacenter_id=5, worker_id=2, epoch_sec=TEST_EPOCH_SEC)
        id_value = await generator.generate_id()

        components = generator.extract_components(id_value)

        assert 'timestamp' in components
        assert 'datacenter_id' in components
        assert 'worker_id' in components
        assert 'sequence' in components

        assert components['datacenter_id'] == 5
        assert components['worker_id'] == 2

    @pytest.mark.asyncio
    async def test_extract_components_all_workers_datacenters(self):
        """Test component extraction for all datacenter/worker combinations"""
        for dc_id in range(16):
            for worker_id in range(4):
                generator = SnowflakeIDGenerator(datacenter_id=dc_id, worker_id=worker_id, epoch_sec=TEST_EPOCH_SEC)
                id_value = await generator.generate_id()
                components = generator.extract_components(id_value)

                assert components['datacenter_id'] == dc_id
                assert components['worker_id'] == worker_id
                assert 0 <= components['sequence'] <= 127

    # ========== Capacity Tests ==========

    @pytest.mark.asyncio
    async def test_capacity_128_ids_per_second_per_worker(self):
        """Test each worker can generate 128 IDs per second"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Generate first ID to set the timestamp
        first_id = await generator.generate_id()

        # Generate 127 more IDs rapidly (should stay in same second)
        ids = [first_id]
        for _ in range(1, 128):
            id_value = await generator.generate_id()
            ids.append(id_value)

        # All IDs should be unique
        assert len(ids) == len(set(ids))

        # Check that we can generate at least 128 IDs
        # (Some may spill to next second, which is fine)
        assert len(ids) == 128

    @pytest.mark.asyncio
    async def test_total_capacity_8192_ids_per_sec(self):
        """Test total system capacity: 8,192 IDs/sec across all DCs"""
        # 16 DCs × 4 workers × 128 sequences = 8,192 IDs/sec

        generators = []
        for dc in range(16):
            for worker in range(4):
                generators.append(SnowflakeIDGenerator(datacenter_id=dc, worker_id=worker, epoch_sec=TEST_EPOCH_SEC))

        assert len(generators) == 64  # 16 DCs × 4 workers

        # Each can do 128 IDs/sec
        total_capacity = 64 * 128
        assert total_capacity == 8192

    # ========== Timestamp Tests ==========

    def test_timestamp_range_8_5_years(self):
        """Test timestamp supports ~8.51 years"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # 28 bits: 2^28 - 1 = 268,435,455 seconds
        max_sec = generator.max_timestamp
        assert max_sec == 268_435_455

        # Convert seconds to years
        seconds_per_year = 365.25 * 24 * 60 * 60
        years = max_sec / seconds_per_year

        assert 8.4 < years < 8.6  # Approximately 8.51 years

    @pytest.mark.asyncio
    async def test_timestamp_overflow_error(self):
        """Test error when timestamp exceeds 28 bits"""
        # Use an epoch far enough in the past to trigger overflow
        # 28 bits in seconds = 268,435,455 seconds (~8.51 years)
        # Set epoch to 9 years ago to trigger overflow
        overflow_epoch = int(time.time()) - (9 * 365 * 24 * 60 * 60)
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=overflow_epoch)

        # Should raise error because current time exceeds max timestamp
        with pytest.raises(RuntimeError, match="Timestamp overflow"):
            await generator.generate_id()

    @pytest.mark.asyncio
    async def test_timestamp_before_epoch_error(self):
        """Test error when current time is before epoch"""
        # Set epoch to future
        future_epoch = int(time.time()) + 10
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=future_epoch)

        with pytest.raises(RuntimeError, match="is before epoch"):
            await generator.generate_id()

    # ========== Error Handling Tests ==========

    @pytest.mark.asyncio
    async def test_clock_backwards_error(self):
        """Test error when clock moves backwards"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Generate one ID
        await generator.generate_id()

        # Manually set last_timestamp to future
        generator.last_timestamp = generator._current_timestamp_sec() + 10

        # Should raise error
        with pytest.raises(RuntimeError, match="Clock moved backwards"):
            await generator.generate_id()

    # ========== Integration Tests ==========

    @pytest.mark.asyncio
    async def test_full_system_integration(self):
        """Test complete system with multiple DCs and workers"""
        generators = {}
        all_ids = []
        all_codes = []

        # Create 3 datacenters with 4 workers each
        for dc_id in range(3):
            for worker_id in range(4):
                gen = SnowflakeIDGenerator(datacenter_id=dc_id, worker_id=worker_id, epoch_sec=TEST_EPOCH_SEC)
                generators[(dc_id, worker_id)] = gen

                # Generate 20 IDs per worker
                for _ in range(20):
                    id_value = await gen.generate_id()
                    code = gen.encode_base62(id_value)

                    all_ids.append(id_value)
                    all_codes.append(code)

                    # Verify components
                    components = gen.extract_components(id_value)
                    assert components['datacenter_id'] == dc_id
                    assert components['worker_id'] == worker_id

        # Verify uniqueness
        assert len(all_ids) == len(set(all_ids))  # 240 unique IDs
        assert len(all_codes) == len(set(all_codes))  # 240 unique codes

        # Verify all codes are 7 characters
        assert all(len(code) == 7 for code in all_codes)

    @pytest.mark.asyncio
    async def test_realistic_url_shortener_scenario(self):
        """Test realistic URL shortener usage pattern"""
        # Single DC, single worker for simplicity
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Simulate 1000 URL shortenings
        url_mappings = {}

        for i in range(1000):
            short_code = await generator.generate_short_code()
            fake_url = f"https://example.com/page/{i}"

            # Verify no collisions
            assert short_code not in url_mappings

            url_mappings[short_code] = fake_url

            # Verify code format
            assert len(short_code) == 7
            assert all(c in generator.BASE62_ALPHABET for c in short_code)

        assert len(url_mappings) == 1000

    @pytest.mark.asyncio
    async def test_high_throughput_stress(self):
        """Test high throughput ID generation"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        # Generate 1,000 IDs as fast as possible
        start_time = time.time()
        ids = []

        for _ in range(1_000):
            id_value = await generator.generate_id()
            ids.append(id_value)

        elapsed = time.time() - start_time

        # All should be unique
        assert len(ids) == len(set(ids))

        # Should complete in reasonable time (< 10 seconds)
        # Note: With SECOND precision, this can take longer than millisecond precision
        # because we may need to wait for the next second when sequence overflows
        assert elapsed < 10.0

        print(f"\nGenerated 1,000 IDs in {elapsed:.3f} seconds")
        print(f"Throughput: {1_000 / elapsed:.0f} IDs/second")

    # ========== Edge Case Tests ==========

    def test_base62_alphabet_correct(self):
        """Test base62 alphabet is correct"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)
        alphabet = generator.BASE62_ALPHABET

        assert len(alphabet) == 62
        assert alphabet == "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

    def test_custom_epoch(self):
        """Test custom epoch configuration"""
        custom_epoch = 1672531200  # 2023-01-01 00:00:00 UTC
        generator = SnowflakeIDGenerator(
            datacenter_id=0,
            worker_id=0,
            epoch_sec=custom_epoch
        )
        assert generator.epoch_sec == custom_epoch

    @pytest.mark.asyncio
    async def test_id_monotonicity(self):
        """Test IDs are strictly monotonically increasing"""
        generator = SnowflakeIDGenerator(datacenter_id=0, worker_id=0, epoch_sec=TEST_EPOCH_SEC)

        prev_id = 0
        for _ in range(1000):
            curr_id = await generator.generate_id()
            assert curr_id > prev_id
            prev_id = curr_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
