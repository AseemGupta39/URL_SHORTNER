"""
Timing middleware to measure request flow timing.

Provides detailed breakdown of where time is spent:
- Pre-middleware (request arrival to middleware start)
- Middleware stack processing
- Handler execution
- Response processing

Usage:
    # In main.py, add as FIRST middleware (outermost layer)
    from shared.middleware.timing_instrumentation import TimingInstrumentationMiddleware

    app.add_middleware(TimingInstrumentationMiddleware)  # First!
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(PrometheusMiddleware)

    # Optional: In handlers, mark start/end for handler-level timing
    from shared.middleware.timing_instrumentation import mark_handler_start, mark_handler_end

    @router.post("/v1/shorten")
    async def shorten_url(...):
        mark_handler_start()
        # ... handler code ...
        mark_handler_end()
        return result
"""
import time
import logging
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from contextvars import ContextVar

logger = logging.getLogger(__name__)

# Context var to store timing data across async calls
_timing_data = ContextVar('timing_data', default=None)


class TimingInstrumentationMiddleware(BaseHTTPMiddleware):
    """
    Outermost middleware to measure complete request timing breakdown.

    Logs timing data with ⏱️ emoji for easy grepping.
    """

    async def dispatch(self, request: Request, call_next):
        timing = {
            't0_received': time.perf_counter(),
            't1_middleware_start': None,
            't2_middleware_end': None,
            't3_handler_start': None,
            't4_handler_end': None,
            't5_response_sent': None
        }

        # Make timing available to handler via context var
        _timing_data.set(timing)

        timing['t1_middleware_start'] = time.perf_counter()

        try:
            response = await call_next(request)

            timing['t2_middleware_end'] = time.perf_counter()
            timing['t5_response_sent'] = time.perf_counter()

            # Calculate durations (in milliseconds)
            total = (timing['t5_response_sent'] - timing['t0_received']) * 1000
            pre_middleware = (timing['t1_middleware_start'] - timing['t0_received']) * 1000
            middleware_processing = (timing['t2_middleware_end'] - timing['t1_middleware_start']) * 1000
            response_processing = (timing['t5_response_sent'] - timing['t2_middleware_end']) * 1000

            # Handler timing (if marks were set by handler)
            handler_time = None
            if timing['t3_handler_start'] and timing['t4_handler_end']:
                handler_time = (timing['t4_handler_end'] - timing['t3_handler_start']) * 1000

            # Log breakdown (use ⏱️ emoji for easy grep)
            if handler_time:
                logger.info(
                    f"⏱️  REQUEST TIMING | {request.method} {request.url.path} | "
                    f"total={total:.2f}ms | pre_mw={pre_middleware:.2f}ms | "
                    f"mw_stack={middleware_processing:.2f}ms | handler={handler_time:.2f}ms | "
                    f"response={response_processing:.2f}ms"
                )
            else:
                logger.info(
                    f"⏱️  REQUEST TIMING | {request.method} {request.url.path} | "
                    f"total={total:.2f}ms | pre_mw={pre_middleware:.2f}ms | "
                    f"mw_stack={middleware_processing:.2f}ms | response={response_processing:.2f}ms"
                )

            return response

        finally:
            _timing_data.set(None)


def mark_handler_start():
    """
    Mark handler start time.

    Call this at the very beginning of your handler function.
    """
    timing = _timing_data.get()
    if timing:
        timing['t3_handler_start'] = time.perf_counter()


def mark_handler_end():
    """
    Mark handler end time.

    Call this just before returning from your handler function.
    """
    timing = _timing_data.get()
    if timing:
        timing['t4_handler_end'] = time.perf_counter()
