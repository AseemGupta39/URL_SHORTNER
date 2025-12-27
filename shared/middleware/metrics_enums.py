"""
Prometheus Metrics Enums

Type-safe enums for metric labels to prevent typos and provide IDE autocomplete.
"""
from enum import Enum


class CacheOperation(str, Enum):
    """Cache operation types."""
    GET = "get"
    SET = "set"
    DELETE = "delete"


class CacheResult(str, Enum):
    """Cache operation results."""
    HIT = "hit"
    MISS = "miss"
    SUCCESS = "success"
    FAILURE = "failure"


class DBOperation(str, Enum):
    """Database operation types."""
    READ = "read"
    WRITE = "write"
    BATCH_WRITE = "batch_write"


class QueueOperation(str, Enum):
    """Queue operation types."""
    ENQUEUE = "enqueue"
    DEQUEUE = "dequeue"
