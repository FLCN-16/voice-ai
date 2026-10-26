"""Application-wide structured logging helpers."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import Mapping
from typing import Any


class _ContextFormatter(logging.Formatter):
    """Render log records with JSON-encoded contextual fields."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        context = getattr(record, "log_context", None)
        if not context:
            return message
        return f"{message} {json.dumps(context, default=str, sort_keys=True)}"


class AppLogger:
    """Small context-aware wrapper around Python's standard logger."""

    def __init__(
        self,
        name: str,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._context = dict(context or {})

    def bind(self, **context: Any) -> "AppLogger":
        """Return a logger with additional fields attached to every record."""
        return AppLogger(self._logger.name, {**self._context, **context})

    def debug(self, message: str, **context: Any) -> None:
        """Write a debug-level message."""
        self._write(logging.DEBUG, message, context)

    def info(self, message: str, **context: Any) -> None:
        """Write an info-level message."""
        self._write(logging.INFO, message, context)

    def warning(self, message: str, **context: Any) -> None:
        """Write a warning-level message."""
        self._write(logging.WARNING, message, context)

    def error(self, message: str, **context: Any) -> None:
        """Write an error-level message."""
        self._write(logging.ERROR, message, context)

    def exception(self, message: str, **context: Any) -> None:
        """Write an error-level message with the active exception traceback."""
        self._write(logging.ERROR, message, context, exc_info=True)

    def _write(
        self,
        level: int,
        message: str,
        context: Mapping[str, Any],
        *,
        exc_info: bool = False,
    ) -> None:
        if not self._logger.isEnabledFor(level):
            return
        self._logger.log(
            level,
            message,
            extra={"log_context": {**self._context, **context}},
            exc_info=exc_info,
        )


def get_logger(name: str) -> AppLogger:
    """Return the shared application logger wrapper for ``name``."""
    return AppLogger(name)


def configure_logging() -> None:
    """Configure application logging once using the ``LOG_LEVEL`` setting."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _ContextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
