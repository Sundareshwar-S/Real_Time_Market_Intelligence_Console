"""Shared utility helpers for formatting, conversion, and logging."""

from datetime import datetime, timezone
import logging
from typing import Any

_LOGGING_CONFIGURED = False
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return
    logging.basicConfig(level=level, format=_LOG_FORMAT)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _LOGGING_CONFIGURED = True


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    configure_logging(level)
    return logging.getLogger(name)


def format_timestamp(value: datetime | None = None) -> str:
    target = value or datetime.now(timezone.utc)
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return target.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_float(value: Any, default: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int | None = None) -> int | None:
    converted = safe_float(value)
    if converted is None:
        return default
    return int(converted)
