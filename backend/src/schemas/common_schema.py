from __future__ import annotations

from ..core.utils import format_timestamp


def build_success_response(
    *,
    data: dict,
    source: str,
    filters: dict | None = None,
    pagination: dict | None = None,
    freshness: list[dict] | None = None,
    no_data: bool = False,
) -> dict:
    meta: dict = {
        "timestamp": format_timestamp(),
        "source": source,
        "no_data": no_data,
    }
    if filters is not None:
        meta["filters"] = filters
    if pagination is not None:
        meta["pagination"] = pagination
    if freshness is not None:
        meta["freshness"] = freshness
    return {
        "status": "success",
        "data": data,
        "meta": meta,
    }


def build_error_response(code: str, message: str, details: dict | None = None) -> dict:
    payload = {
        "status": "error",
        "error": {
            "code": code,
            "message": message,
        },
        "meta": {"timestamp": format_timestamp()},
    }
    if details:
        payload["error"]["details"] = details
    return payload
