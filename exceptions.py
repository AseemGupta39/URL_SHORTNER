"""
Custom exceptions for URL shortener application.

Exception hierarchy maps to HTTP status codes:
- ShortCodeNotFoundException → 404 Not Found
- ShortCodeAlreadyExistsException → 409 Conflict
- InvalidURLException → 422 Unprocessable Entity
- URLShortenerException → 500 Internal Server Error
"""


class URLShortenerException(Exception):
    """Base exception for all URL shortener errors."""
    pass


class ShortCodeNotFoundException(URLShortenerException):
    """Raised when a short code is not found in the database."""

    def __init__(self, short_code: str):
        self.short_code = short_code
        super().__init__(f"Short code '{short_code}' not found")


class ShortCodeAlreadyExistsException(URLShortenerException):
    """Raised when attempting to create a short code that already exists."""

    def __init__(self, short_code: str):
        self.short_code = short_code
        super().__init__(f"Short code '{short_code}' already exists")


class InvalidURLException(URLShortenerException):
    """Raised when a URL fails validation."""

    def __init__(self, url: str, reason: str = "Invalid URL format"):
        self.url = url
        self.reason = reason
        super().__init__(f"{reason}: {url}")
