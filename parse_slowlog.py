#!/usr/bin/env python3
"""
Parses Redis SLOWLOG output file and extracts SET/RPUSH execution times.
Compares Redis server-side timing vs app-side timing to identify
network/connection pool overhead.
"""

import sys
from statistics import mean, median


def percentile(sorted_list, p):
    idx = int(len(sorted_list) * p / 100)
    return sorted_list[min(idx, len(sorted_list) - 1)]


def parse_slowlog(filename):
    set_times = []
    rpush_times = []

    with open(filename, 'r') as f:
        lines = [line.strip() for line in f.readlines()]

    i = 0
    while i < len(lines):
        # Skip empty lines
        if not lines[i]:
            i += 1
            continue

        # Try to parse an entry: id, timestamp, exec_time_us, command, ...
        try:
            entry_id = int(lines[i])
            timestamp = int(lines[i + 1])
            exec_time_us = int(lines[i + 2])
            command = lines[i + 3].strip()

            if command == "SET":
                set_times.append(exec_time_us)
            elif command == "RPUSH":
                rpush_times.append(exec_time_us)

            # Skip to next entry (find next blank line or end)
            i += 4
            while i < len(lines) and lines[i]:
                i += 1
        except (ValueError, IndexError):
            i += 1

    return set_times, rpush_times


def print_stats(name, times_us, app_side_ms):
    if not times_us:
        print(f"  No {name} operations found")
        return

    times_us.sort()
    times_ms = [t / 1000 for t in times_us]

    avg_ms = mean(times_ms)
    med_ms = median(times_ms)
    min_ms = min(times_ms)
    max_ms = max(times_ms)
    p95_ms = percentile(times_ms, 95)
    p99_ms = percentile(times_ms, 99)

    print(f"\n{name} Operations (Redis server-side)")
    print("-" * 50)
    print(f"  Count:      {len(times_us)}")
    print(f"  Average:    {avg_ms:.3f} ms  ({mean(times_us):.0f} µs)")
    print(f"  Median:     {med_ms:.3f} ms  ({median(times_us):.0f} µs)")
    print(f"  Min:        {min_ms:.3f} ms  ({min(times_us)} µs)")
    print(f"  Max:        {max_ms:.3f} ms  ({max(times_us)} µs)")
    print(f"  P95:        {p95_ms:.3f} ms")
    print(f"  P99:        {p99_ms:.3f} ms")
    print()
    print(f"  App-side measured:   {app_side_ms:.2f} ms")
    print(f"  Redis server-side:   {avg_ms:.3f} ms")
    print(f"  Network + Pool wait: {app_side_ms - avg_ms:.2f} ms  ({((app_side_ms - avg_ms) / app_side_ms * 100):.1f}% of total)")


def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else "slowlog_output.txt"

    print("=" * 50)
    print("Redis SLOWLOG Analysis")
    print("=" * 50)
    print(f"Parsing: {filename}")

    set_times, rpush_times = parse_slowlog(filename)

    print(f"Total SET entries:   {len(set_times)}")
    print(f"Total RPUSH entries: {len(rpush_times)}")

    # App-side timings from analyze_timing.py output
    print_stats("SET", set_times, app_side_ms=57.90)
    print_stats("RPUSH", rpush_times, app_side_ms=58.10)

    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()
