"""
Per-service logging configuration module.

Provides setup_logging() function to configure logging for each microservice
with colored console output, clean file logs, log rotation, and date-based directory organization.
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional

try:
    import colorlog
    HAS_COLORLOG = True
except ImportError:
    HAS_COLORLOG = False

try:
    from pythonjsonlogger import jsonlogger
    HAS_JSON_LOGGER = True
except ImportError:
    HAS_JSON_LOGGER = False


# Store original LogRecord factory
_original_log_record_factory = logging.getLogRecordFactory()

_SERVICE_NAME: str = ""


def _context_aware_log_record(*args, **kwargs) -> logging.LogRecord:
    """
    Custom LogRecord factory that automatically adds context variables to log records.

    This makes context data (like request_id, batch_id, service, etc.) available in
    every log message without needing to pass them manually or use filters.

    Extensible: Just add more context getters here as needed.
    """
    record = _original_log_record_factory(*args, **kwargs)

    # Add request ID + batch ID from contextvars; service name from module global.
    try:
        from shared.utils.request_context import get_request_id, get_batch_id

        request_id = get_request_id()
        record.request_id = request_id if request_id else "-"

        batch_id = get_batch_id()
        record.batch_id = batch_id if batch_id else "-"
    except (ImportError, Exception):
        record.request_id = "-"
        record.batch_id = "-"

    record.service = _SERVICE_NAME if _SERVICE_NAME else "-"

    # Future: Add more context variables here as needed
    # record.user_id = get_user_id() or "-"
    # record.session_id = get_session_id() or "-"

    return record


def setup_logging(
    service_name: str,
    log_level: str = "INFO",
    base_log_dir: str = "logs",
    log_filename: Optional[str] = None,
    max_bytes: int = 2_000_000,  # 2MB
    backup_count: int = 5,
    json_format: bool = False,
    enable_console: bool = True,
    enable_file: bool = True,
) -> None:
    """
    Setup logging configuration for a microservice.

    Args:
        service_name: Name of the service (e.g., 'shorten', 'redirect', 'batch_processor')
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        base_log_dir: Base directory for logs (default: 'logs')
        log_filename: Custom log filename (default: {service_name}.log)
        max_bytes: Maximum size per log file before rotation (default: 2MB)
        backup_count: Number of backup files to keep (default: 5)
        json_format: If True, use JSON format instead of colored text (default: False)
        enable_console: Enable console logging (default: True)
        enable_file: Enable file logging (default: True)

    Directory Structure:
        logs/{service_name}/YYYY/MM/DD/{service_name}.log

    Example:
        >>> setup_logging(service_name="shorten", log_level="INFO")
        >>> logger = logging.getLogger(__name__)
        >>> logger.info("Service started")
    """
    # Install custom LogRecord factory to add context variables
    global _SERVICE_NAME
    _SERVICE_NAME = service_name
    logging.setLogRecordFactory(_context_aware_log_record)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Clear existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Create log format
    if json_format:
        log_format = _get_json_format()
    else:
        # Standard format: timestamp [level] [request_id] [batch_id] [module:line:function] message
        log_format = "%(asctime)s [%(levelname)s] [%(request_id)s] [%(batch_id)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"

    # Console handler with colors
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        if HAS_COLORLOG and not json_format:
            # Colored console formatter (includes request_id and batch_id from context)
            console_formatter = colorlog.ColoredFormatter(
                fmt="%(log_color)s%(asctime)s [%(levelname)s] [%(request_id)s] [%(batch_id)s] [%(name)s:%(funcName)s:%(lineno)d]%(reset)s %(message)s",
                datefmt=date_format,
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "red,bg_white",
                },
            )
            console_handler.setFormatter(console_formatter)
        else:
            # Fallback to standard formatter if colorlog not available
            console_formatter = logging.Formatter(log_format, datefmt=date_format)
            console_handler.setFormatter(console_formatter)

        root_logger.addHandler(console_handler)

    # File handler with rotation and date-based directories
    if enable_file:
        if not HAS_JSON_LOGGER:
            raise RuntimeError(
                "python-json-logger is required for file logging. "
                "Install it with: pip install python-json-logger"
            )

        # Create date-based directory structure: logs/{service}/YYYY/MM/DD/
        now = datetime.utcnow()
        log_dir = os.path.join(
            base_log_dir,
            service_name,
            str(now.year),
            f"{now.month:02d}",
            f"{now.day:02d}",
        )
        os.makedirs(log_dir, exist_ok=True)

        # Create log file path — JSONL extension makes the format obvious
        if log_filename is None:
            log_filename = f"{service_name}.jsonl"
        log_file_path = os.path.join(log_dir, log_filename)

        # Rotating file handler
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(getattr(logging, log_level.upper(), logging.INFO))

        # File logs as JSONL — one JSON object per line. Every key passed via
        # extra={} (outcome, processed, db_time_ms, short_code, etc.) is
        # preserved. Ready to ship to Datadog / Loki / Elasticsearch or query
        # with `jq`. Console stays human-readable (colored text) above.
        file_formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(service)s %(request_id)s %(batch_id)s "
            "%(name)s %(funcName)s %(lineno)d %(message)s",
            datefmt=date_format,
            rename_fields={
                "asctime": "timestamp",
                "levelname": "level",
                "funcName": "function",
                "lineno": "line",
                "name": "logger",
            },
        )
        file_handler.setFormatter(file_formatter)

        root_logger.addHandler(file_handler)

    # Silence noisy third-party loggers
    _configure_third_party_loggers()

    # Log initialization message
    logger = logging.getLogger(__name__)
    logger.info(
        f"Logging configured for service '{service_name}' at level {log_level.upper()}"
    )
    if enable_file:
        logger.info("Log file configured", extra={"log_file_path": str(log_file_path)})


def _get_json_format() -> str:
    """
    Get JSON log format string.

    Note: This is a placeholder. For production JSON logging,
    consider using python-json-logger library.
    """
    # For now, return standard format
    # TODO: Implement proper JSON formatter with python-json-logger
    return "%(asctime)s [%(levelname)s] [%(name)s:%(funcName)s:%(lineno)d] %(message)s"


def _configure_third_party_loggers() -> None:
    """Configure log levels for noisy third-party libraries."""
    # Silence uvicorn access logs (keep only errors)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # Reduce SQLAlchemy verbosity
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    # Reduce urllib3 verbosity (used by requests, boto3, etc.)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Reduce httpx verbosity (used by httpx, FastAPI TestClient)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # Reduce aiosqlite verbosity (async SQLite driver)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
