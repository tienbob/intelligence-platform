"""
Structured logging configuration.

Provides a consistent logger across the application with JSON formatting
for production and human-readable output for development.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from app.core.config import get_settings

settings = get_settings()


class StructuredFormatter(logging.Formatter):
    """Minimal structured formatter that includes extra fields."""

    def format(self, record: logging.LogRecord) -> str:
        # Base message
        record_dict: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge extra fields
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
                "taskName",
            ):
                record_dict[key] = value

        if record.exc_info:
            record_dict["exception"] = self.formatException(record.exc_info)

        if settings.DEBUG:
            # Human-readable for development
            parts = [
                record_dict["timestamp"],
                record_dict["level"],
                record_dict["logger"],
                record_dict["message"],
            ]
            return " | ".join(parts)
        else:
            # Simple JSON-ish output for production
            import json
            return json.dumps(record_dict, default=str)


def setup_logging() -> None:
    """Configure root logging for the application."""
    level = logging.DEBUG if settings.DEBUG else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Quiet noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger with the given name."""
    return logging.getLogger(name)