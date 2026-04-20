from flask import Blueprint, jsonify, request

from ..core.utils import get_logger
from ..database.repository import fetch_forecast_outputs, fetch_freshness_status
from ..schemas.common_schema import build_error_response, build_success_response
from ..schemas.forecast_schema import build_forecast_payload
from .validators import parse_limit_offset, parse_optional_string, parse_symbol, parse_time_range

forecast_bp = Blueprint("forecast", __name__, url_prefix="/api")
logger = get_logger("backend.api.forecast")


@forecast_bp.get("/forecast")
def get_forecast():
    try:
        limit, offset = parse_limit_offset(
            request.args.get("limit"),
            request.args.get("offset"),
            default_limit=50,
            max_limit=5000,
        )
        symbol = parse_symbol(request.args.get("symbol"))
        model = parse_optional_string(request.args.get("model"), "model")
        start_time, end_time = parse_time_range(
            request.args.get("start_time"),
            request.args.get("end_time"),
        )
        records = fetch_forecast_outputs(
            limit=limit + 1,
            offset=offset,
            symbol=symbol,
            model=model,
            start_time=start_time,
            end_time=end_time,
        )
        range_fallback_used = False
        if not records and (start_time is not None or end_time is not None):
            records = fetch_forecast_outputs(
                limit=limit + 1,
                offset=offset,
                symbol=symbol,
                model=model,
            )
            range_fallback_used = bool(records)
        has_more = len(records) > limit
        records = records[:limit]
        payload = build_forecast_payload(records)
        response = build_success_response(
            data=payload,
            source="processing",
            filters={
                key: value
                for key, value in {
                    "symbol": symbol,
                    "model": model,
                    "start_time": start_time,
                    "end_time": end_time,
                    "range_fallback_used": range_fallback_used if range_fallback_used else None,
                }.items()
                if value is not None
            },
            pagination={"limit": limit, "offset": offset, "has_more": has_more},
            freshness=fetch_freshness_status(),
            no_data=len(records) == 0,
        )
        return jsonify(response), 200
    except ValueError as exc:
        return jsonify(build_error_response("invalid_input", str(exc))), 400
    except Exception as exc:
        logger.exception("Failed to fetch forecast data")
        return jsonify(build_error_response("repository_error", "Failed to fetch forecast data.", {"reason": str(exc)})), 500
