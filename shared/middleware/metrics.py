"""
Prometheus Metrics Middleware

Tracks HTTP requests, response times, and exposes /metrics endpoint.
Provides helper functions for service-layer metrics (cache, DB, queue, business events).
"""
import time
import logging
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from shared.middleware.metrics_definitions import (
    http_requests_total,
    http_request_duration_seconds,
    cache_operations_total,
    db_operations_total,
    db_operation_duration_seconds,
    queue_operations_total,
    queue_size,
    urls_shortened_total,
    urls_redirected_total,
    batch_processed_total,
    batch_urls_inserted_total
)
from shared.middleware.metrics_enums import (
    CacheOperation,
    CacheResult,
    DBOperation,
    QueueOperation
)

logger = logging.getLogger(__name__)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Middleware to track HTTP request metrics.

    Tracks request count, duration, and status codes per endpoint/method.
    """

    def __init__(self, app: ASGIApp, service_name: str):
        """
        Initialize Prometheus middleware.

        Args:
            app: ASGI application
            service_name: Name of the service (shorten/redirect/batch_processor)
        """
        if not service_name:
            raise ValueError("service_name required")

        super().__init__(app)
        self.service_name = service_name
        logger.info(f"Prometheus metrics initialized: service={service_name}")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Track HTTP request metrics."""
        # Skip metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)

        endpoint = request.url.path
        method = request.method
        start_time = time.time()

        try:
            response = await call_next(request)
            duration = time.time() - start_time

            # Record success metrics
            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status_code=response.status_code,
                service=self.service_name
            ).inc()

            http_request_duration_seconds.labels(
                method=method,
                endpoint=endpoint,
                service=self.service_name
            ).observe(duration)

            logger.debug(
                f"HTTP metric: method={method} | endpoint={endpoint} | "
                f"status={response.status_code} | duration={duration*1000:.2f}ms"
            )

            return response

        except Exception as e:
            duration = time.time() - start_time

            # Record error metrics
            http_requests_total.labels(
                method=method,
                endpoint=endpoint,
                status_code=500,
                service=self.service_name
            ).inc()

            logger.error(
                f"HTTP error: method={method} | endpoint={endpoint} | "
                f"duration={duration*1000:.2f}ms | error={str(e)}",
                exc_info=True
            )
            raise


def metrics_endpoint() -> Response:
    """Expose Prometheus metrics at /metrics endpoint."""
    logger.debug("Metrics endpoint called")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Service-layer metric helpers

def track_cache_operation(
    operation: CacheOperation,
    result: CacheResult,
    service: str
):
    """
    Track cache operation with type-safe enums.

    Args:
        operation: CacheOperation (GET/SET/DELETE)
        result: CacheResult (HIT/MISS/SUCCESS/FAILURE)
        service: Service name (shorten/redirect/batch_processor)
    """
    cache_operations_total.labels(
        operation=operation.value,
        result=result.value,
        service=service
    ).inc()


def track_db_operation(
    operation: DBOperation,
    duration_seconds: float,
    service: str
):
    """
    Track DB operation with timing and type-safe enums.

    Args:
        operation: DBOperation (READ/WRITE/BATCH_WRITE)
        duration_seconds: Operation duration in seconds
        service: Service name (shorten/redirect/batch_processor)
    """
    db_operations_total.labels(operation=operation.value, service=service).inc()
    db_operation_duration_seconds.labels(
        operation=operation.value,
        service=service
    ).observe(duration_seconds)


def track_queue_operation(operation: QueueOperation, service: str) -> None:
    """
    Track queue operation with type-safe enums.

    Args:
        operation: QueueOperation (ENQUEUE/DEQUEUE)
        service: Service name (shorten/redirect/batch_processor)
    """
    queue_operations_total.labels(operation=operation.value, service=service).inc()


def update_queue_size(size: int, service: str) -> None:
    """Update current queue size gauge."""
    queue_size.labels(service=service).set(size)


def track_url_shortened(service: str) -> None:
    """Track URL shortening business event."""
    urls_shortened_total.labels(service=service).inc()


def track_url_redirected(service: str) -> None:
    """Track URL redirect business event."""
    urls_redirected_total.labels(service=service).inc()


def track_batch_processed(urls_count: int, service: str) -> None:
    """Track batch processing business event."""
    batch_processed_total.labels(service=service).inc()
    batch_urls_inserted_total.labels(service=service).inc(urls_count)
