from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request

from ..core.utils import get_logger
from ..database.repository import fetch_freshness_status, fetch_market_series
from ..schemas.common_schema import build_error_response, build_success_response
from .validators import parse_iso_datetime, parse_symbol

series_bp = Blueprint("series", __name__, url_prefix="/api/series")
logger = get_logger("backend.api.series")


def _resolve_context(value: str | None) -> str:
    context = (value or "all").strip().lower()
    if context not in {"all", "crypto", "stock"}:
        raise ValueError("context must be one of: all, crypto, stock.")
    return context


def _resolve_max_points(value: str | None) -> int:
    if value is None or value.strip() == "":
        return 180
    try:
        max_points = int(value)
    except ValueError as exc:
        raise ValueError("max_points must be an integer.") from exc
    if max_points < 1 or max_points > 1500:
        raise ValueError("max_points must be between 1 and 1500.")
    return max_points


def _resolve_bucket(
    value: str | None,
    start_time: datetime,
    end_time: datetime,
) -> str:
    if value:
        bucket = value.strip().lower()
        if bucket in {"1h", "4h", "1d", "1w", "1m"}:
            return bucket
        raise ValueError("bucket must be one of: 1h, 4h, 1d, 1w, 1m.")

    span_days = (end_time - start_time).total_seconds() / 86400
    if span_days <= 60:
        return "1h"
    if span_days <= 400:
        return "1d"
    if span_days <= 800:
        return "1w"
    return "1m"


@series_bp.get("/market")
def get_market_series():
    try:
        context = _resolve_context(request.args.get("context"))
        symbol = parse_symbol(request.args.get("symbol"), "symbol")
        selected_symbol = symbol if context in {"crypto", "stock"} else None
        start_raw = parse_iso_datetime(request.args.get("start_time"), "start_time")
        end_raw = parse_iso_datetime(request.args.get("end_time"), "end_time")
        end_time = (
            datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
            if end_raw
            else datetime.now(timezone.utc)
        )
        start_time = (
            datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            if start_raw
            else end_time - timedelta(days=30)
        )

        if end_time < start_time:
            raise ValueError("end_time must be >= start_time.")

        max_points = _resolve_max_points(request.args.get("max_points"))
        bucket = _resolve_bucket(request.args.get("bucket"), start_time, end_time)

        points = fetch_market_series(
            context=context,
            symbol=selected_symbol,
            start_time=start_time,
            end_time=end_time,
            bucket=bucket,
            max_points=max_points,
        )
        updated_at = points[-1]["timestamp"] if points else None

        response = build_success_response(
            data={"points": points, "bucket": bucket, "updated_at": updated_at},
            source="database",
            filters={
                "context": context,
                **({"symbol": selected_symbol} if selected_symbol else {}),
                "start_time": start_time.isoformat().replace("+00:00", "Z"),
                "end_time": end_time.isoformat().replace("+00:00", "Z"),
                "bucket": bucket,
                "max_points": max_points,
            },
            freshness=fetch_freshness_status(),
            no_data=len(points) == 0,
        )
        return jsonify(response), 200
    except ValueError as exc:
        return jsonify(build_error_response("invalid_input", str(exc))), 400
    except Exception as exc:
        logger.exception("Failed to fetch market series")
        return jsonify(
            build_error_response(
                "repository_error",
                "Failed to fetch market series.",
                {"reason": str(exc)},
            )
        ), 500
