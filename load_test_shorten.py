#!/usr/bin/env python3
"""
Load test for /v1/shorten endpoint
Sends N concurrent POST requests and measures performance
"""

import asyncio
import aiohttp
import time
import json


API_URL = "http://localhost:8001/v1/shorten"


async def send_single_request(session, request_id):
    """
    Send one POST request to /v1/shorten and measure its latency.

    Returns a dict with request_id, status, body, duration_ms
    """
    start_ts = time.time()
    payload = {
        "original_url": f"https://example.com/test-{request_id}-{int(time.time() * 1000)}"
    }

    try:
        async with session.post(
            API_URL,
            json=payload,
            headers={"Content-Type": "application/json"}
        ) as response:
            resp_text = await response.text()
            end_ts = time.time()
            return {
                "request_id": request_id,
                "status": response.status,
                "body": resp_text,
                "duration_ms": int((end_ts - start_ts) * 1000),
            }
    except Exception as e:
        end_ts = time.time()
        return {
            "request_id": request_id,
            "status": "ERROR",
            "body": str(e),
            "duration_ms": int((end_ts - start_ts) * 1000),
        }


async def run_load_test(total_requests):
    if total_requests <= 0:
        raise ValueError("total_requests must be > 0")

    # First, do a warmup request
    print("Running warmup request...")
    async with aiohttp.ClientSession() as session:
        await send_single_request(session, 0)
    print("Warmup complete\n")

    await asyncio.sleep(1)

    # Now run the actual load test
    async with aiohttp.ClientSession() as session:
        tasks = [send_single_request(session, i) for i in range(1, total_requests + 1)]

        print(f"Starting load test with {total_requests} concurrent requests...\n")
        start = time.time()
        results = await asyncio.gather(*tasks)
        end = time.time()

        total_time = end - start
        durations = [
            r.get("duration_ms", 0)
            for r in results
            if isinstance(r.get("duration_ms", None), (int, float))
        ]
        sum_durations_ms = sum(durations)
        avg_latency = (sum(durations) / len(durations)) if durations else 0
        min_latency = min(durations) if durations else 0
        max_latency = max(durations) if durations else 0
        success_count = sum(
            1
            for r in results
            if isinstance(r.get("status"), int) and 200 <= r.get("status") < 300
        )
        error_count = total_requests - success_count
        rps = total_requests / total_time if total_time > 0 else float("inf")

        print("=" * 60)
        print("Load Test Results")
        print("=" * 60)
        print(f"Completed {total_requests} requests in {total_time:.2f}s (wall-clock)")
        print(f"Sum of per-request durations: {sum_durations_ms} ms")
        print(f"Requests/sec: {rps:.2f} rps")
        print(f"Avg latency: {avg_latency:.1f} ms | min: {min_latency} ms | max: {max_latency} ms")
        print(f"Success: {success_count} | Errors: {error_count}")

        if error_count > 0:
            print("\nError breakdown:")
            error_statuses = {}
            for r in results:
                if not (isinstance(r.get("status"), int) and 200 <= r.get("status") < 300):
                    status = str(r.get("status", "UNKNOWN"))
                    error_statuses[status] = error_statuses.get(status, 0) + 1
            for status, count in error_statuses.items():
                print(f"  {status}: {count}")

        print("=" * 60)
        print()

        return results


def main():
    print("URL Shortener Load Test")
    print("-" * 60)
    try:
        total_requests = int(input("Enter number of concurrent requests (default 1000): ") or "1000")
    except ValueError:
        print("Invalid input, using default: 1000")
        total_requests = 1000

    responses = asyncio.run(run_load_test(total_requests))


if __name__ == "__main__":
    main()
