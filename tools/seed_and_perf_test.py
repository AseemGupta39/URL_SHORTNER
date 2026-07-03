"""
Redirect performance test with large dataset.

Steps:
  1. Truncate urls table + flush Redis
  2. Seed 5M rows using PostgreSQL COPY (fast bulk insert ~2-3 min)
  3. Run 4-stage redirect perf test:
     Stage 1: DB only, no connection pooling
     Stage 2: DB only, with connection pooling
     Stage 3: Redis cache only
     Stage 4: Tiered cache (L1 LFU + L2 Redis)

Short code format: exactly 8 Base62 chars [A-Za-z0-9] — matches SHORT_CODE_PATTERN
Generated deterministically: sequential int → Base62 padded to 8 chars
All guaranteed unique (primary key safe), all pass regex validation.

Run from project root:
  source /home/aseem/Music/new_folder/url_shortener_venv/bin/activate
  python tools/seed_and_perf_test.py

Flags:
  --skip-seed   skip seeding (if already seeded)
  --rows N      number of rows to seed (default 5_000_000)
"""

import asyncio
import subprocess
import sys
import time
import os
import re
import io
import textwrap
import argparse
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
TEST_PORT    = 8099
WRK_DURATION = "20s"
WRK_WARMUP   = "5s"

DB_URL    = "postgresql+asyncpg://urlapp:dev123@127.0.0.1:5432/urls"
PG_DSN    = "postgresql://urlapp:dev123@127.0.0.1:5432/urls"  # psql / psycopg2 style for COPY
REDIS_URL = "redis://localhost:6379"

# Overridden by --db-url flag at runtime
_db_url_override: str | None = None

TARGET_ROWS     = 5_000_000
BASE_URL        = "https://example.com/p/"
# This short code is seeded as row i=1 — guaranteed in DB and Redis
LOOKUP_CODE     = "00000001"

BASE62_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def int_to_base62(n: int, width: int = 8) -> str:
    """Convert integer to Base62 string, left-padded with '0' to `width` chars."""
    if n == 0:
        return "0" * width
    chars = []
    while n:
        chars.append(BASE62_CHARS[n % 62])
        n //= 62
    result = "".join(reversed(chars))
    return result.zfill(width)


# Verify our codes pass the regex before doing anything
_PATTERN = re.compile(r'^[A-Za-z0-9]{8}$')
for _test_n in [0, 1, 1000, 999999, 4999999]:
    _code = int_to_base62(_test_n)
    assert len(_code) == 8, f"Code length wrong: {_code!r}"
    assert _PATTERN.match(_code), f"Code fails regex: {_code!r}"


# ---------------------------------------------------------------------------
# Stage definitions — same structure as redirect_perf_test.py
# ---------------------------------------------------------------------------

APP_TEMPLATE = '''\
import sys
sys.path.insert(0, "{project_root}")

import re
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from shared.data.models import URLModel

SHORT_CODE_PATTERN = re.compile(r'^[A-Za-z0-9]{{8}}$')

{cache_imports}

app = FastAPI()

engine = create_async_engine(
    "{db_url}",
    pool_size={pool_size},
    max_overflow={max_overflow},
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

{cache_init}

@app.on_event("startup")
async def startup():
{startup_body}

@app.get("/{{short_code}}")
async def redirect(short_code: str):
    if not SHORT_CODE_PATTERN.match(short_code):
        raise HTTPException(status_code=400, detail="Invalid short code format.")
{handler_body}
'''

STAGES = [
    {
        "name": "Stage 1: DB only, no pooling",
        "pool_size": 1,
        "max_overflow": 0,
        "cache_imports": "",
        "cache_init": "",
        "startup_body": "    pass",
        "handler_body": textwrap.dedent("""\
            async with async_session() as session:
                result = await session.execute(
                    select(URLModel).where(URLModel.short_code == short_code)
                )
                url_model = result.scalar_one_or_none()
            if url_model is None:
                raise HTTPException(status_code=404)
            return RedirectResponse(url=url_model.original_url, status_code=302)
        """),
    },
    {
        "name": "Stage 2: DB with connection pooling",
        "pool_size": 20,
        "max_overflow": 10,
        "cache_imports": "",
        "cache_init": "",
        "startup_body": "    pass",
        "handler_body": textwrap.dedent("""\
            async with async_session() as session:
                result = await session.execute(
                    select(URLModel).where(URLModel.short_code == short_code)
                )
                url_model = result.scalar_one_or_none()
            if url_model is None:
                raise HTTPException(status_code=404)
            return RedirectResponse(url=url_model.original_url, status_code=302)
        """),
    },
    {
        "name": "Stage 3: Redis cache only",
        "pool_size": 20,
        "max_overflow": 10,
        "cache_imports": "from shared.utils.redis_cache import RedisCache",
        "cache_init": 'cache = RedisCache(redis_url="{redis_url}", ttl_seconds=3600, max_connections=100)',
        "startup_body": "    await cache.connect()",
        "handler_body": textwrap.dedent("""\
            cached = await cache.get_async(short_code)
            if cached:
                return RedirectResponse(url=cached, status_code=302)
            async with async_session() as session:
                result = await session.execute(
                    select(URLModel).where(URLModel.short_code == short_code)
                )
                url_model = result.scalar_one_or_none()
            if url_model is None:
                raise HTTPException(status_code=404)
            await cache.set_async(short_code, url_model.original_url)
            return RedirectResponse(url=url_model.original_url, status_code=302)
        """),
    },
    {
        "name": "Stage 4: Tiered cache (L1 LFU + L2 Redis)",
        "pool_size": 20,
        "max_overflow": 10,
        "cache_imports": textwrap.dedent("""\
            from shared.utils.redis_cache import RedisCache
            from shared.utils.lfu_cache import LFUCache
            from shared.utils.tiered_cache import TieredCache
        """),
        "cache_init": textwrap.dedent("""\
            _redis = RedisCache(redis_url="{redis_url}", ttl_seconds=3600, max_connections=100)
            _lfu   = LFUCache(max_size=1000)
            cache  = TieredCache(l1_cache=_lfu, l2_cache=_redis)
        """),
        "startup_body": "    await _redis.connect()",
        "handler_body": textwrap.dedent("""\
            cached = await cache.get_async(short_code)
            if cached:
                return RedirectResponse(url=cached, status_code=302)
            async with async_session() as session:
                result = await session.execute(
                    select(URLModel).where(URLModel.short_code == short_code)
                )
                url_model = result.scalar_one_or_none()
            if url_model is None:
                raise HTTPException(status_code=404)
            await cache.set_async(short_code, url_model.original_url)
            return RedirectResponse(url=url_model.original_url, status_code=302)
        """),
    },
]

MODES = [
    {"label": "serial     (c=1,  t=1)", "threads": 1, "connections": 1},
    {"label": "concurrent (c=40, t=4)", "threads": 4, "connections": 40},
]

# DB stages use random codes (forces buffer pool misses, real index stress)
# Cache stages use fixed code (measures pure cache hit path — that's the point)
RANDOM_STAGES = {0, 1}   # stage indices that should use random lookup


# ---------------------------------------------------------------------------
# Truncate + seed
# ---------------------------------------------------------------------------

async def truncate_db():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    engine = create_async_engine(DB_URL)  # uses module-level DB_URL (may be overridden by --db-url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE urls RESTART IDENTITY CASCADE"))
    await engine.dispose()
    print("  DB truncated.")


async def flush_redis():
    import redis.asyncio as aioredis
    client = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    await client.flushdb()
    await client.aclose()
    print("  Redis flushed.")


def seed_via_copy(n_rows: int):
    """
    Seed n_rows into urls table using PostgreSQL COPY from stdin.
    Each short code is int_to_base62(i) — exactly 8 [A-Za-z0-9] chars.
    original_url is BASE_URL + short_code (always valid VARCHAR).
    created_at is a fixed naive UTC timestamp (no timezone — matches DateTime column).
    """
    import psycopg2

    print(f"  Connecting to PostgreSQL for COPY...")
    conn = psycopg2.connect(PG_DSN)
    conn.autocommit = True
    cur = conn.cursor()

    created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    batch_size = 100_000
    total_written = 0
    start = time.time()

    print(f"  Seeding {n_rows:,} rows in batches of {batch_size:,}...")

    for batch_start in range(0, n_rows, batch_size):
        batch_end = min(batch_start + batch_size, n_rows)
        buf = io.StringIO()
        for i in range(batch_start, batch_end):
            code = int_to_base62(i)
            url  = BASE_URL + code
            buf.write(f"{code}\t{url}\t{created_at}\n")
        buf.seek(0)
        cur.copy_from(buf, "urls", columns=("short_code", "original_url", "created_at"))
        total_written = batch_end
        elapsed = time.time() - start
        rate = total_written / elapsed
        print(f"  {total_written:>9,} / {n_rows:,} rows  ({rate:,.0f} rows/sec)  {elapsed:.1f}s", end="\r")

    print(f"\n  Done. {total_written:,} rows in {time.time()-start:.1f}s")
    cur.close()
    conn.close()


async def warm_redis_lookup_code():
    """Warm the LOOKUP_CODE into Redis so Stage 3/4 get a cache hit immediately."""
    import redis.asyncio as aioredis
    client = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    await client.set(LOOKUP_CODE, BASE_URL + LOOKUP_CODE, ex=7200)
    await client.aclose()
    print(f"  Redis warmed: {LOOKUP_CODE}")


# ---------------------------------------------------------------------------
# Bench app builder
# ---------------------------------------------------------------------------

def build_app(stage: dict) -> str:
    cache_init = stage["cache_init"].replace("{redis_url}", REDIS_URL)
    handler_lines = "\n".join("    " + line for line in stage["handler_body"].splitlines())
    return APP_TEMPLATE.format(
        project_root=str(PROJECT_ROOT),
        db_url=DB_URL,
        redis_url=REDIS_URL,
        pool_size=stage["pool_size"],
        max_overflow=stage["max_overflow"],
        cache_imports=stage["cache_imports"],
        cache_init=cache_init,
        startup_body=stage["startup_body"],
        handler_body=handler_lines,
    )


# ---------------------------------------------------------------------------
# wrk helpers
# ---------------------------------------------------------------------------

LUA_SCRIPT = "/tmp/random_codes.lua"


def write_lua_script(n_rows: int):
    """Write wrk Lua script that picks a random short code from the seeded range."""
    script = f"""\
math.randomseed(os.time())
local base62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
local function int_to_base62(n)
    local result = {{}}
    for i = 1, 8 do result[i] = "0" end
    local pos = 8
    while n > 0 do
        result[pos] = base62:sub((n % 62) + 1, (n % 62) + 1)
        n = math.floor(n / 62)
        pos = pos - 1
    end
    return table.concat(result)
end
request = function()
    local i = math.random(0, {n_rows - 1})
    return wrk.format("GET", "/" .. int_to_base62(i))
end
"""
    with open(LUA_SCRIPT, "w") as f:
        f.write(script)


def run_wrk(duration: str, threads: int, connections: int, random: bool = False) -> dict:
    url = f"http://127.0.0.1:{TEST_PORT}/{LOOKUP_CODE}"
    if random:
        cmd = ["wrk", "-t", str(threads), "-c", str(connections), "-d", duration,
               "--latency", "-s", LUA_SCRIPT, url]
    else:
        cmd = ["wrk", "-t", str(threads), "-c", str(connections), "-d", duration,
               "--latency", url]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return parse_wrk(result.stdout + result.stderr)


def parse_wrk(output: str) -> dict:
    rps = lat_avg = lat_p99 = None

    m = re.search(r"Requests/sec:\s+([\d.]+)", output)
    if m:
        rps = float(m.group(1))

    # "  Latency   0.67ms  123.00us   5.00ms   83.00%"
    m = re.search(r"Latency\s+([\d.]+)(ms|us|s)\s+([\d.]+)(ms|us|s)\s+([\d.]+)(ms|us|s)", output)
    if m:
        lat_avg = to_ms(float(m.group(1)), m.group(2))

    # p99 from --latency flag: "     99%   1.23ms"
    m = re.search(r"^\s+99%\s+([\d.]+)(ms|us|s)", output, re.MULTILINE)
    if m:
        lat_p99 = to_ms(float(m.group(1)), m.group(2))

    return {"rps": rps, "lat_avg": lat_avg, "lat_p99": lat_p99, "raw": output}


def to_ms(v: float, unit: str) -> float:
    if unit == "us": return round(v / 1000, 4)
    if unit == "s":  return round(v * 1000, 2)
    return round(v, 4)


def start_server(app_code: str) -> subprocess.Popen:
    with open("/tmp/bench_app.py", "w") as f:
        f.write(app_code)
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "bench_app:app",
         "--host", "127.0.0.1", "--port", str(TEST_PORT),
         "--workers", "1", "--log-level", "critical", "--http", "httptools"],
        cwd="/tmp", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def wait_for_server(timeout=30) -> bool:
    import urllib.request, urllib.error
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{TEST_PORT}/xxxxxxxx", timeout=1)
            return True  # 2xx — server up
        except urllib.error.HTTPError:
            return True  # 4xx/5xx — server up, route 404'd, fine
        except Exception:
            # ConnectionRefused / timeout etc — server not yet up, keep polling
            time.sleep(0.2)
    return False


def kill_server(proc: subprocess.Popen):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    time.sleep(0.5)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def print_results(results: list, n_rows: int):
    sl = MODES[0]["label"]
    cl = MODES[1]["label"]

    print("\n" + "=" * 84)
    print(f"REDIRECT PERF — {n_rows/1_000_000:.0f}M ROWS IN DB")
    print("=" * 84)
    print(f"{'Stage':<34} {'S-RPS':>7} {'S-avg':>8} {'S-p99':>8} {'C-RPS':>8} {'C-avg':>8} {'C-p99':>8}")
    print("-" * 84)

    for r in results:
        name = r["name"].split(":")[1].strip()[:33]
        s = r["modes"].get(sl, {})
        c = r["modes"].get(cl, {})
        def fmt_rps(x): return f"{x:,.0f}" if x else "N/A"
        def fmt_ms(x):  return f"{x:.3f}" if x else "N/A"
        print(f"{name:<34} {fmt_rps(s.get('rps')):>7} {fmt_ms(s.get('lat_avg')):>8} "
              f"{fmt_ms(s.get('lat_p99')):>8} {fmt_rps(c.get('rps')):>8} "
              f"{fmt_ms(c.get('lat_avg')):>8} {fmt_ms(c.get('lat_p99')):>8}")

    print("=" * 84)
    print("S = serial c=1 (per-request latency)  |  C = concurrent c=40 (throughput)")
    print(f"Lookup code: {LOOKUP_CODE}  |  1 uvicorn worker, httptools, --log-level critical")

    # Resume bullet
    if len(results) == 4:
        def g(si, mode, key): return results[si]["modes"].get(mode, {}).get(key)
        l1 = g(0, sl, "lat_avg"); l2 = g(1, sl, "lat_avg")
        l3 = g(2, sl, "lat_avg"); l4 = g(3, sl, "lat_avg")
        r1 = g(0, cl, "rps");     r4 = g(3, cl, "rps")

        if all(v is not None for v in [l1, l2, l3, l4, r1, r4]):
            print("\n" + "=" * 84)
            print("RESUME BULLET")
            print("=" * 84)
            print(textwrap.dedent(f"""
            Optimized redirect hot path against {n_rows/1_000_000:.0f}M-row PostgreSQL table across
            4 stages — DB no-pool ({l1:.2f}ms) → DB pooled ({l2:.2f}ms) →
            Redis cache ({l3:.3f}ms, {l1/l3:.0f}x faster than DB) →
            L1 in-memory LFU ({l4:.4f}ms, {l1/l4:.0f}x faster than DB, {l3/l4:.0f}x faster than Redis);
            concurrent throughput improved from {int(r1):,} → {int(r4):,} RPS
            (+{int(r4-r1):,} RPS).
            """))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(skip_seed: bool, n_rows: int):
    sys.path.insert(0, str(PROJECT_ROOT))

    # Check dependencies
    if subprocess.run(["which", "wrk"], capture_output=True).returncode != 0:
        print("ERROR: wrk not found. Install: sudo apt install wrk")
        sys.exit(1)
    try:
        import psycopg2
    except ImportError:
        print("ERROR: psycopg2 not found. Install: pip install psycopg2-binary")
        sys.exit(1)

    if not skip_seed:
        print("\n[Step 1] Truncating DB and Redis...")
        await truncate_db()
        await flush_redis()

        print(f"\n[Step 2] Seeding {n_rows:,} rows via PostgreSQL COPY...")
        seed_via_copy(n_rows)

        print("\n[Step 3] Warming Redis with lookup code...")
        await warm_redis_lookup_code()

        # Verify seeded data passes regex and exists in DB
        print("\n[Step 4] Verifying seeded data...")
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
        from sqlalchemy import text, select
        from shared.data.models import URLModel
        engine = create_async_engine(DB_URL)
        sf = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with sf() as session:
            count = await session.execute(text("SELECT COUNT(*) FROM urls"))
            total = count.scalar()
            row = await session.execute(
                select(URLModel).where(URLModel.short_code == LOOKUP_CODE)
            )
            found = row.scalar_one_or_none()
        await engine.dispose()

        assert found is not None, f"LOOKUP_CODE {LOOKUP_CODE} not found in DB!"
        assert _PATTERN.match(LOOKUP_CODE), f"LOOKUP_CODE fails regex: {LOOKUP_CODE}"
        print(f"  Total rows in DB: {total:,}")
        print(f"  Lookup code '{LOOKUP_CODE}' found: {found.original_url}")
        print(f"  Regex check: PASS")
    else:
        print("\n[Skipping seed — using existing data]")

    print("\n[Step 5] Writing Lua script for random lookups...")
    write_lua_script(n_rows)
    print(f"  Written: {LUA_SCRIPT}")
    print("  DB stages (1,2): random codes across full {n_rows:,} range — forces buffer pool misses")
    print("  Cache stages (3,4): fixed code — measures pure cache hit path")

    print("\n[Step 6] Running 4-stage perf test...")
    results = []

    for i, stage in enumerate(STAGES):
        use_random = i in RANDOM_STAGES
        mode_note = "random lookups" if use_random else "fixed code (cache hit)"
        print(f"\n  [Stage {i+1}/4] {stage['name']}  [{mode_note}]")
        proc = start_server(build_app(stage))

        if not wait_for_server(timeout=30):
            print("  ERROR: server did not start")
            try:
                _, err = proc.communicate(timeout=2)
                if err:
                    print("  --- captured uvicorn stderr ---")
                    print(err.decode(errors="replace"))
                    print("  --- end stderr ---")
            except Exception:
                pass
            kill_server(proc)
            results.append({"name": stage["name"], "modes": {}})
            continue

        stage_result = {"name": stage["name"], "modes": {}}

        for mode in MODES:
            t, c, label = mode["threads"], mode["connections"], mode["label"]
            run_wrk(WRK_WARMUP, t, c, random=use_random)  # warmup
            print(f"    [{label}] running {WRK_DURATION}...", end=" ", flush=True)
            r = run_wrk(WRK_DURATION, t, c, random=use_random)
            stage_result["modes"][label] = r
            rps = f"{r['rps']:,.0f}" if r['rps'] else "N/A"
            avg = f"{r['lat_avg']:.3f}ms" if r['lat_avg'] else "N/A"
            p99 = f"{r['lat_p99']:.3f}ms" if r['lat_p99'] else "N/A"
            print(f"RPS={rps}  avg={avg}  p99={p99}")
            if not r['rps']:
                print("    [raw output]:", r.get("raw", "none")[:300])

        results.append(stage_result)
        kill_server(proc)

    print_results(results, n_rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-seed", action="store_true", help="Skip truncate+seed, use existing data")
    parser.add_argument("--rows", type=int, default=TARGET_ROWS, help="Rows to seed (default 5_000_000)")
    parser.add_argument("--db-url", type=str, default=None, help="Override DB URL (e.g. postgresql+asyncpg://urlapp:dev123@127.0.0.1:5433/urls)")
    args = parser.parse_args()

    if args.db_url:
        _db_url_override = args.db_url
        DB_URL = args.db_url
        # Derive psycopg2-style DSN from asyncpg URL
        PG_DSN = args.db_url.replace("postgresql+asyncpg://", "postgresql://")

    asyncio.run(main(skip_seed=args.skip_seed, n_rows=args.rows))