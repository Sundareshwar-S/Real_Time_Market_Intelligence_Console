from flask import Blueprint, jsonify, request

from ..core.utils import get_logger
from ..database.repository import fetch_freshness_status, fetch_latest_market_data, fetch_market_data
from ..schemas.common_schema import build_error_response, build_success_response
from ..schemas.data_schema import build_data_payload, build_latest_payload
from ..services.ingestion.crypto_service import fetch_global_crypto_market_cap_usd
from .validators import parse_limit_offset, parse_source, parse_symbol, parse_time_range

data_bp = Blueprint("data", __name__, url_prefix="/api")
logger = get_logger("backend.api.data")


@data_bp.get("/data")
def get_data():
    try:
        limit, offset = parse_limit_offset(
            request.args.get("limit"),
            request.args.get("offset"),
            default_limit=50,
            max_limit=500,
        )
        symbol = parse_symbol(request.args.get("symbol"))
        source = parse_source(request.args.get("source"))
        start_time, end_time = parse_time_range(
            request.args.get("start_time"),
            request.args.get("end_time"),
        )
        filters = {
            "symbol": symbol,
            "source": source,
            "start_time": start_time,
            "end_time": end_time,
        }
        records = fetch_market_data(
            limit=limit + 1,
            offset=offset,
            symbol=symbol,
            source=source,
            start_time=start_time,
            end_time=end_time,
        )
        has_more = len(records) > limit
        records = records[:limit]
        include_global_crypto_market_cap = source is None or source.lower() in {"crypto", "freecryptoapi"}
        global_crypto_market_cap = None
        global_crypto_market_cap_source = None
        if include_global_crypto_market_cap:
            global_cap_response = fetch_global_crypto_market_cap_usd()
            global_crypto_market_cap = global_cap_response.get("market_cap_usd")
            global_crypto_market_cap_source = global_cap_response.get("source")
        payload = build_data_payload(
            records,
            global_crypto_market_cap=global_crypto_market_cap,
            global_crypto_market_cap_source=global_crypto_market_cap_source,
        )
        response = build_success_response(
            data=payload,
            source="database",
            filters={key: value for key, value in filters.items() if value is not None},
            pagination={"limit": limit, "offset": offset, "has_more": has_more},
            freshness=fetch_freshness_status(source=source),
            no_data=len(records) == 0,
        )
        return jsonify(response), 200
    except ValueError as exc:
        return jsonify(build_error_response("invalid_input", str(exc))), 400
    except Exception as exc:
        logger.exception("Failed to fetch market data")
        return jsonify(build_error_response("repository_error", "Failed to fetch market data.", {"reason": str(exc)})), 500


@data_bp.get("/latest")
def get_latest():
    try:
        symbol = parse_symbol(request.args.get("symbol"))
        source = parse_source(request.args.get("source"))
        start_time, end_time = parse_time_range(
            request.args.get("start_time"),
            request.args.get("end_time"),
        )
        latest = fetch_latest_market_data(
            symbol=symbol,
            source=source,
            start_time=start_time,
            end_time=end_time,
        )
        payload = build_latest_payload(latest)
        response = build_success_response(
            data=payload,
            source="database",
            filters={
                key: value
                for key, value in {
                    "symbol": symbol,
                    "source": source,
                    "start_time": start_time,
                    "end_time": end_time,
                }.items()
                if value is not None
            },
            freshness=fetch_freshness_status(source=source),
            no_data=latest is None,
        )
        return jsonify(response), 200
    except ValueError as exc:
        return jsonify(build_error_response("invalid_input", str(exc))), 400
    except Exception as exc:
        logger.exception("Failed to fetch latest market data")
        return jsonify(
            build_error_response(
                "repository_error",
                "Failed to fetch latest market data.",
                {"reason": str(exc)},
            )
        ), 500
