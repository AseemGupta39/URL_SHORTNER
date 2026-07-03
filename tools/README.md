# Redirect Performance Benchmark

`seed_and_perf_test.py` measures the redirect hot path against a 5M-row PostgreSQL
table across four cache configurations, so you can reproduce the latency and
throughput numbers yourself.

## What it measures

The redirect path carries ~80% of real short-link traffic (clicks on existing
links). The script runs the same lookup under four stages and reports per-request
latency (serial) and sustained throughput (concurrent):

| Stage | Config | Lookup workload |
|---|---|---|
| 1 | DB only, **no** connection pool | Random codes across all 5M rows |
| 2 | DB only, **with** pool (size=20, overflow=10) | Random codes across all 5M rows |
| 3 | Redis cache only (skip DB on hit) | Fixed code — pure cache-hit path |
| 4 | Tiered: L1 in-process LFU + L2 Redis | Fixed code — pure cache-hit path |

DB stages use **random** codes on purpose — this defeats PostgreSQL
`shared_buffers` and the OS page cache, so you measure real index I/O instead of
a RAM-cached hot row. Cache stages use a fixed code to measure the pure hit path.

## Prerequisites

- **Python 3.10+** with the project's virtualenv activated
- **PostgreSQL** running on `127.0.0.1:5432` with a database reachable at the
  connection string in the script (`DB_URL` / `PG_DSN` near the top of the file —
  edit these to match your local setup)
- **Redis** running on `localhost:6379`
- **wrk** — the HTTP load generator (`sudo apt install wrk` on Debian/Ubuntu)

Verify both services are up before running:

```bash
redis-cli ping            # -> PONG
psql "postgresql://<user>:<pass>@127.0.0.1:5432/<db>" -c "SELECT 1;"
```

## Running it

From the project root, with the virtualenv activated:

```bash
# First time — seeds 5,000,000 rows via PostgreSQL COPY (~20-30s), then benchmarks:
python tools/seed_and_perf_test.py

# Subsequent runs — reuse the already-seeded 5M rows (much faster):
python tools/seed_and_perf_test.py --skip-seed

# Seed a smaller/larger dataset:
python tools/seed_and_perf_test.py --rows 1000000
```

Flags:

- `--skip-seed` — skip seeding; use the data already in the table
- `--rows N` — number of rows to seed (default 5,000,000)

Each stage runs a 20s serial pass (c=1) and a 20s concurrent pass (c=40, t=4),
so a full run takes ~3 minutes.

## Reading the output

The script prints a table like:

```
Stage                                S-RPS    S-avg    S-p99    C-RPS
DB only, no pooling                    943    1.250    3.690      943
DB with connection pooling           1,256    1.110    3.490    1,256
Redis cache only                     8,239    0.179    0.645    8,239
Tiered cache (L1 LFU + L2 Redis)    17,398    0.083    0.255   17,398
```

`S-avg` / `S-p99` are per-request latency in ms (serial). `C-RPS` is sustained
requests/sec under 40 concurrent connections.

## Expected results & reproducibility

On the reference machine (Linux, PostgreSQL 17, local Redis, single uvicorn
worker), across multiple runs the tiered cache vs direct DB comes out to roughly:

- **~14x lower average latency** (~1.3ms → ~0.09ms)
- **~18x higher concurrent throughput** (~950 → ~17,400 RPS)

**Your absolute numbers will differ** based on CPU, RAM, and disk — but the
*ratio* between stages is a property of the architecture (memory lookup vs disk
I/O + network), not the hardware, so it holds within ~15% across machines. The
p99 ratio is noisier (varies 8-14x) because tail latency picks up whatever else
the machine is doing during the 20s window; lead with the avg-latency and RPS
ratios, which reproduce reliably.