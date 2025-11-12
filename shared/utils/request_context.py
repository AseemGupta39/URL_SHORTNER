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
