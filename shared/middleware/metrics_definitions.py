"""
Prometheus Metrics Definitions

Defines all Prometheus metrics (counters, histograms, gauges) used across services.
"""
from prometheus_client import Counter, Histogram, Gauge

# HTTP Request Metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code", "service"]
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint", "service"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

# Cache Metrics
cache_operations_total = Counter(
    "cache_operations_total",
    "Total cache operations",
    ["operation", "result", "service"]  # operation: get/set/delete, result: hit/miss/success/failure
)

# Database Metrics
db_operations_total = Counter(
    "db_operations_total",
    "Total database operations",
    ["operation", "service"]  # operation: read/write/batch_write
)

db_operation_duration_seconds = Histogram(
    "db_operation_duration_seconds",
    "Database operation latency in seconds",
    ["operation", "service"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0)
)

# Queue Metrics
queue_operations_total = Counter(
    "queue_operations_total",
    "Total queue operations",
    ["operation", "service"]  # operation: enqueue/dequeue
)

queue_size = Gauge(
    "queue_size",
    "Current queue size",
    ["service"]
)

# Business Metrics
urls_shortened_total = Counter(
    "urls_shortened_total",
    "Total URLs shortened",
    ["service"]
)

urls_redirected_total = Counter(
    "urls_redirected_total",
    "Total URL redirects",
    ["service"]
)

batch_processed_total = Counter(
    "batch_processed_total",
    "Total batches processed",
    ["service"]
)

batch_urls_inserted_total = Counter(
    "batch_urls_inserted_total",
    "Total URLs inserted via batch processing",
    ["service"]
)
