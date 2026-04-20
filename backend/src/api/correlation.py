from flask import Blueprint, jsonify, request

from ..core.utils import get_logger
from ..database.repository import fetch_correlation_metrics, fetch_freshness_status
from ..schemas.common_schema import build_error_response, build_success_response
from ..schemas.correlation_schema import build_correlation_payload
from .validators import parse_bool, parse_limit_offset, parse_symbol, parse_time_range

correlation_bp = Blueprint("correlation", __name__, url_prefix="/api")
logger = get_logger("backend.api.correlation")


@correlation_bp.get("/correlation")
def get_correlation():
    try:
        limit, offset = parse_limit_offset(
            request.args.get("limit"),
            request.args.get("offset"),
            default_limit=50,
            max_limit=5000,
        )
        symbol = parse_symbol(request.args.get("symbol"))
        shift_only = parse_bool(
            request.args.get("shift_only"),
            default=None,
            field_name="shift_only",
        )
        start_time, end_time = parse_time_range(
            request.args.get("start_time"),
            request.args.get("end_time"),
        )

        records = fetch_correlation_metrics(
            limit=limit + 1,
            offset=offset,
            symbol=symbol,
            shift_only=shift_only,
            start_time=start_time,
            end_time=end_time,
        )
        has_more = len(records) > limit
        records = records[:limit]

        payload = build_correlation_payload(records)
        response = build_success_response(
            data=payload,
            source="processing",
            filters={
                key: value
                for key, value in {
                    "symbol": symbol,
                    "shift_only": shift_only,
                    "start_time": start_time,
                    "end_time": end_time,
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
        logger.exception("Failed to fetch correlation metrics")
        return jsonify(
            build_error_response(
                "repository_error",
                "Failed to fetch correlation metrics.",
                {"reason": str(exc)},
            )
        ), 500
