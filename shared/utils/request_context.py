"""
Request context management for tracking request IDs across async operations.

Provides thread-safe context variables that persist across async function calls,
allowing request IDs to be accessible in all layers without passing as parameters.
"""
from contextvars import ContextVar
from typing import Optional
import uuid


# Context variable to store request ID
# ContextVar is like a per-request "backpack" that each request carries
# It's thread-safe and works with async/await
request_id_var: ContextVar[Optional[str]] = ContextVar('request_id', default=None)

# Context variable to store batch ID (for batch processing operations)
# Separate from request_id to maintain end-to-end traceability
batch_id_var: ContextVar[Optional[str]] = ContextVar('batch_id', default=None)


def generate_request_id() -> str:
    """
    Generate a unique request ID using UUID4.

    Returns:
        UUID string in format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

    Example:
        >>> request_id = generate_request_id()
        >>> print(request_id)
        '550e8400-e29b-41d4-a716-446655440000'
    """
    return str(uuid.uuid4())


def get_request_id() -> Optional[str]:
    """
    Get the current request ID from context.

    This can be called from anywhere in your code during request processing.
    Returns None if called outside of a request context.

    Returns:
        Current request ID if set, None otherwise

    Example:
        >>> request_id = get_request_id()
        >>> if request_id:
        ...     logger.info(f"[{request_id}] Processing request")
    """
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    """
    Set the request ID in context.

    This should be called once per request, typically in middleware.

    Args:
        request_id: The request ID to set

    Example:
        >>> # In middleware
        >>> request_id = generate_request_id()
        >>> set_request_id(request_id)
    """
    request_id_var.set(request_id)


def clear_request_id() -> None:
    """
    Clear the request ID from context.

    Useful for cleanup in tests or after request completion.
    Normally not needed as ContextVar cleans up automatically.
    """
    request_id_var.set(None)


def get_batch_id() -> Optional[str]:
    """
    Get the current batch ID from context.

    Used by batch processing workers to track batch operations.
    Returns None if called outside of a batch processing context.

    Returns:
        Current batch ID if set, None otherwise

    Example:
        >>> batch_id = get_batch_id()
        >>> if batch_id:
        ...     logger.info(f"[{batch_id}] Processing batch")
    """
    return batch_id_var.get()


def set_batch_id(batch_id: str) -> None:
    """
    Set the batch ID in context.

    This should be called once per batch operation, typically in batch workers.

    Args:
        batch_id: The batch ID to set (e.g., "batch-abc123")

    Example:
        >>> # In batch worker
        >>> batch_id = f"batch-{uuid.uuid4().hex[:12]}"
        >>> set_batch_id(batch_id)
    """
    batch_id_var.set(batch_id)


def clear_batch_id() -> None:
    """
    Clear the batch ID from context.

    Useful for cleanup after batch completion.
    """
    batch_id_var.set(None)
