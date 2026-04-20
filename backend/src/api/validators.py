from __future__ import annotations

from datetime import datetime, timezone
import re


_SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_SOURCE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,48}$")


def parse_limit_offset(
    limit_raw: str | None,
    offset_raw: str | None,
    *,
    default_limit: int = 50,
    max_limit: int = 500,
) -> tuple[int, int]:
    try:
        limit = default_limit if limit_raw in (None, "") else int(limit_raw)
        offset = 0 if offset_raw in (None, "") else int(offset_raw)
    except ValueError as exc:
        raise ValueError("limit and offset must be integers.") from exc
    if limit < 1 or limit > max_limit:
        raise ValueError(f"limit must be between 1 and {max_limit}.")
    if offset < 0:
        raise ValueError("offset must be >= 0.")
    return limit, offset


def parse_symbol(raw: str | None, field_name: str = "symbol") -> str | None:
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip().upper()
    if not _SYMBOL_PATTERN.match(value):
        raise ValueError(f"{field_name} contains invalid characters.")
    return value


def parse_source(raw: str | None) -> str | None:
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip().lower()
    if not _SOURCE_PATTERN.match(value):
        raise ValueError("source contains invalid characters.")
    return value


def parse_optional_string(raw: str | None, field_name: str, max_len: int = 64) -> str | None:
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip()
    if len(value) > max_len:
        raise ValueError(f"{field_name} must be <= {max_len} chars.")
    return value


def parse_bool(raw: str | None, *, default: bool | None = None, field_name: str = "value") -> bool | None:
    if raw is None or raw.strip() == "":
        return default
    candidate = raw.strip().lower()
    if candidate in {"1", "true", "yes", "on"}:
        return True
    if candidate in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{field_name} must be a boolean.")


def parse_iso_datetime(raw: str | None, field_name: str) -> str | None:
    if raw is None or raw.strip() == "":
        return None
    candidate = raw.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time_range(start_raw: str | None, end_raw: str | None) -> tuple[str | None, str | None]:
    start = parse_iso_datetime(start_raw, "start_time")
    end = parse_iso_datetime(end_raw, "end_time")
    if start and end:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if end_dt < start_dt:
            raise ValueError("end_time must be >= start_time.")
    return start, end
