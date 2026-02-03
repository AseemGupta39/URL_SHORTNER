#!/usr/bin/env python3
"""
Analyze timing data from Docker logs
"""

import re
import sys
from statistics import mean, median, stdev


def parse_request_timing(log_line):
    """Extract timing data from REQUEST TIMING log lines"""
    pattern = r'total=(\d+\.\d+)ms.*handler=(\d+\.\d+)ms'
    match = re.search(pattern, log_line)
    if match:
        return {
            'total': float(match.group(1)),
            'handler': float(match.group(2))
        }
    return None


def parse_redis_timing(log_line):
    """Extract Redis operation timing from DEBUG logs"""
    # Pattern for Cached: lines
    cached_pattern = r'Cached:.*total=(\d+\.\d+)ms.*serialize=(\d+\.\d+)ms.*redis_set=(\d+\.\d+)ms'
    cached_match = re.search(cached_pattern, log_line)
    if cached_match:
        return {
            'operation': 'SET',
            'total': float(cached_match.group(1)),
            'serialize': float(cached_match.group(2)),
            'redis_op': float(cached_match.group(3))
        }

    # Pattern for Enqueued: lines
    enqueued_pattern = r'Enqueued.*total=(\d+\.\d+)ms.*serialize=(\d+\.\d+)ms.*redis_rpush=(\d+\.\d+)ms'
    enqueued_match = re.search(enqueued_pattern, log_line)
    if enqueued_match:
        return {
            'operation': 'RPUSH',
            'total': float(enqueued_match.group(1)),
            'serialize': float(enqueued_match.group(2)),
            'redis_op': float(enqueued_match.group(3))
        }

    return None


def analyze_logs(filename=None):
    """Analyze timing data from logs"""
    if filename:
        with open(filename, 'r') as f:
            lines = f.readlines()
    else:
        lines = sys.stdin.readlines()

    request_timings = []
    redis_set_timings = []
    redis_rpush_timings = []

    for line in lines:
        # Parse request timing
        if 'REQUEST TIMING | POST /v1/shorten' in line:
            timing = parse_request_timing(line)
            if timing:
                request_timings.append(timing)

        # Parse Redis timing
        redis_timing = parse_redis_timing(line)
        if redis_timing:
            if redis_timing['operation'] == 'SET':
                redis_set_timings.append(redis_timing)
            elif redis_timing['operation'] == 'RPUSH':
                redis_rpush_timings.append(redis_timing)

    print("=" * 70)
    print("TIMING ANALYSIS")
    print("=" * 70)
    print()

    if request_timings:
        totals = [t['total'] for t in request_timings]
        handlers = [t['handler'] for t in request_timings]
        middlewares = [t['total'] - t['handler'] for t in request_timings]

        print(f"REQUEST TIMING ({len(request_timings)} requests)")
        print("-" * 70)
        print(f"Total Time:")
        print(f"  Average:    {mean(totals):.2f} ms")
        print(f"  Median:     {median(totals):.2f} ms")
        print(f"  Min:        {min(totals):.2f} ms")
        print(f"  Max:        {max(totals):.2f} ms")
        if len(totals) > 1:
            print(f"  Std Dev:    {stdev(totals):.2f} ms")
        print()
        print(f"Handler Time:")
        print(f"  Average:    {mean(handlers):.2f} ms")
        print(f"  Percentage: {(mean(handlers)/mean(totals)*100):.1f}%")
        print()
        print(f"Middleware Time:")
        print(f"  Average:    {mean(middlewares):.2f} ms")
        print(f"  Percentage: {(mean(middlewares)/mean(totals)*100):.1f}%")
        print()
    else:
        print("No REQUEST TIMING data found")
        print()

    if redis_set_timings:
        redis_ops = [t['redis_op'] for t in redis_set_timings]
        serializes = [t['serialize'] for t in redis_set_timings]

        print(f"REDIS SET OPERATIONS ({len(redis_set_timings)} operations)")
        print("-" * 70)
        print(f"Redis SET Time:")
        print(f"  Average:    {mean(redis_ops):.2f} ms")
        print(f"  Median:     {median(redis_ops):.2f} ms")
        print(f"  Min:        {min(redis_ops):.2f} ms")
        print(f"  Max:        {max(redis_ops):.2f} ms")
        if len(redis_ops) > 1:
            print(f"  Std Dev:    {stdev(redis_ops):.2f} ms")
        print()
        print(f"Serialization Time:")
        print(f"  Average:    {mean(serializes):.2f} ms")
        print()
    else:
        print("No REDIS SET timing data found (DEBUG logs may not be captured)")
        print()

    if redis_rpush_timings:
        redis_ops = [t['redis_op'] for t in redis_rpush_timings]
        serializes = [t['serialize'] for t in redis_rpush_timings]

        print(f"REDIS RPUSH OPERATIONS ({len(redis_rpush_timings)} operations)")
        print("-" * 70)
        print(f"Redis RPUSH Time:")
        print(f"  Average:    {mean(redis_ops):.2f} ms")
        print(f"  Median:     {median(redis_ops):.2f} ms")
        print(f"  Min:        {min(redis_ops):.2f} ms")
        print(f"  Max:        {max(redis_ops):.2f} ms")
        if len(redis_ops) > 1:
            print(f"  Std Dev:    {stdev(redis_ops):.2f} ms")
        print()
        print(f"Serialization Time:")
        print(f"  Average:    {mean(serializes):.2f} ms")
        print()
    else:
        print("No REDIS RPUSH timing data found (DEBUG logs may not be captured)")
        print()

    print("=" * 70)

    # Summary
    if request_timings and not redis_set_timings:
        print("\nNOTE: Redis operation timings are not in the logs.")
        print("This suggests DEBUG-level logs from redis_cache.py and redis_queue.py")
        print("are not being captured. The middleware overhead shown above includes")
        print("Redis operations, database calls, and other processing.")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_logs(sys.argv[1])
    else:
        analyze_logs()
