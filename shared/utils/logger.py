"""
Logging configuration for URL shortener application.

Provides centralized logging with structured output format.
"""
import logging
import sys
from pathlib import Path
from typing import Optional

# Import after other imports to avoid circular dependency
from shared.utils import request_context


class AppLogger:
    """
    Centralized logging utility for the application.

    Features:
    - Single logger instance for entire application
    - Structured format: LEVEL | TIMESTAMP | FILENAME:LINENO | MESSAGE
    - Color-coded console output for development
    - Optional file logging for production
    """

    _instance: Optional[logging.Logger] = None

    @classmethod
    def setup(
        cls,
        name: str = "url_shortener",
        level: int = logging.INFO,
        log_file: Optional[str] = None,
        enable_console: bool = True
    ) -> logging.Logger:
        """
        Setup and configure the application logger.

        Args:
            name: Logger name (default: "url_shortener")
            level: Logging level (default: INFO)
            log_file: Optional path to log file for production
            enable_console: Enable console output (default: True)

        Returns:
            Configured logger instance
        """
        # If logger already exists, reconfigure it with new settings
        if cls._instance is not None:
            logger = cls._instance
            logger.setLevel(level)
            logger.handlers.clear()  # Clear existing handlers to reconfigure
        else:
            # Create new logger
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.handlers.clear()  # Clear any existing handlers

        # Console handler with colored output
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_formatter = cls._get_console_formatter()
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)

        # File handler for production logging
        if log_file:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(level)
            file_formatter = cls._get_file_formatter()
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)

        # Prevent propagation to root logger
        logger.propagate = False

        cls._instance = logger
        return logger

    @staticmethod
    def _get_console_formatter() -> logging.Formatter:
        """
        Get formatter for console output with colors.

        Format: LEVEL | TIMESTAMP | FILENAME:LINENO | MESSAGE
        """
        COLORS = {
            'DEBUG': '\033[36m',      # Cyan
            'INFO': '\033[32m',       # Green
            'WARNING': '\033[33m',    # Yellow
            'ERROR': '\033[31m',      # Red
            'CRITICAL': '\033[35m',   # Magenta
            'RESET': '\033[0m'        # Reset
        }

        class ColoredFormatter(logging.Formatter):
            def format(self, record):
                levelname = record.levelname
                color = COLORS.get(levelname, '')
                reset = COLORS['RESET'] if color else ''

                # Get request ID from context (if available)
                # Using first 12 chars (48 bits = 281 trillion combinations)
                # This provides collision resistance for billions of requests over months in log files
                request_id = request_context.get_request_id()
                request_id_str = f"[{request_id[:12]}]" if request_id else ""

                # Apply color only to level name and message
                colored_level = f"{color}{levelname:8s}{reset}"
                colored_message = f"{color}{record.getMessage()}{reset}"

                # Format timestamp and location without color
                timestamp = self.formatTime(record, '%Y-%m-%d %H:%M:%S')
                location = f"{record.filename}:{record.lineno}"

                # Combine: colored_level | timestamp | [request_id] | location | colored_message
                if request_id_str:
                    return f"{colored_level} | {timestamp} | {request_id_str} | {location} | {colored_message}"
                else:
                    # No request ID (startup logs, background tasks)
                    return f"{colored_level} | {timestamp} | {location} | {colored_message}"

        return ColoredFormatter()  # Format is handled in format() method

    @staticmethod
    def _get_file_formatter() -> logging.Formatter:
        """
        Get formatter for file output (no colors).

        Format: LEVEL | TIMESTAMP | [REQUEST_ID] | FILENAME:LINENO | MESSAGE
        """
        class FileFormatter(logging.Formatter):
            def format(self, record):
                # Get request ID from context (12 chars for collision resistance)
                request_id = request_context.get_request_id()
                request_id_str = f"[{request_id[:12]}] | " if request_id else ""

                # Format the base message
                formatted = super().format(record)

                # Insert request ID after timestamp
                parts = formatted.split(' | ', 2)
                if len(parts) >= 2 and request_id_str:
                    return f"{parts[0]} | {parts[1]} | {request_id_str}{parts[2]}"
                return formatted

        fmt = '%(levelname)-8s | %(asctime)s | %(filename)s:%(lineno)d | %(message)s'
        datefmt = '%Y-%m-%d %H:%M:%S'

        return FileFormatter(fmt, datefmt)

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """
        Get the configured logger instance.

        Returns:
            Logger instance (creates with defaults if not already setup)
        """
        if cls._instance is None:
            cls.setup()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the logger instance (useful for testing)."""
        if cls._instance:
            for handler in cls._instance.handlers[:]:
                handler.close()
                cls._instance.removeHandler(handler)
        cls._instance = None


# Convenience function for easy access throughout the application
def get_logger() -> logging.Logger:
    """
    Get the application logger instance.

    Returns:
        Configured logger instance

    Example:
        >>> from app.utils.logger import get_logger
        >>> logger = get_logger()
        >>> logger.info("Application started")
        >>> logger.error("Failed to connect to database")
        >>> logger.debug("Processing request with ID: 12345")
    """
    return AppLogger.get_logger()
