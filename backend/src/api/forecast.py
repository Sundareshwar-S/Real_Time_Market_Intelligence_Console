from copy import deepcopy
from dataclasses import asdict
from threading import Lock
from time import perf_counter

from flask import Blueprint, jsonify, request

from ..core.config import get_settings
from ..core.utils import get_logger
from ..database.repository import (
    fetch_forecast_outputs,
    fetch_freshness_status,
    fetch_market_data_for_forecast_training,
)
from ..schemas.common_schema import build_error_response, build_success_response
from ..schemas.forecast_schema import build_forecast_payload
from ..services.processing.cleaner import CleanerConfig, clean_and_engineer
from ..services.processing.forecast import (
    ForecastConfig,
    summarize_forecast_diagnostics,
)
from ..services.processing.model_registry import get_forecast_model, get_model_metadata
from .validators import parse_limit_offset, parse_optional_string, parse_symbol, parse_time_range

forecast_bp = Blueprint("forecast", __name__, url_prefix="/api")
logger = get_logger("backend.api.forecast")

_DEFAULT_FORECAST_MAPE_THRESHOLD = 12.0
_DIAGNOSTICS_CACHE_TTL_SECONDS = 45.0
_DIAGNOSTICS_CACHE_LOCK = Lock()
_DIAGNOSTICS_CACHE: dict[tuple[str | None, int, float], dict] = {}


def _diagnostics_cache_key(symbol: str | None, holdout_steps: int, mape_threshold: float) -> tuple[str | None, int, float]:
    return (symbol, holdout_steps, round(mape_threshold, 4))


def _get_cached_diagnostics(symbol: str | None, holdout_steps: int, mape_threshold: float) -> dict | None:
    cache_key = _diagnostics_cache_key(symbol, holdout_steps, mape_threshold)
    now = perf_counter()
    with _DIAGNOSTICS_CACHE_LOCK:
        item = _DIAGNOSTICS_CACHE.get(cache_key)
        if not item:
            return None
        age = now - float(item.get("cached_at", 0.0))
        if age > _DIAGNOSTICS_CACHE_TTL_SECONDS:
            _DIAGNOSTICS_CACHE.pop(cache_key, None)
            return None
        return deepcopy(item.get("payload"))


def _cache_diagnostics_payload(
    symbol: str | None,
    holdout_steps: int,
    mape_threshold: float,
    payload: dict,
) -> None:
    cache_key = _diagnostics_cache_key(symbol, holdout_steps, mape_threshold)
    with _DIAGNOSTICS_CACHE_LOCK:
        _DIAGNOSTICS_CACHE[cache_key] = {
            "cached_at": perf_counter(),
            "payload": deepcopy(payload),
        }


def _resolve_holdout_steps(value: str | None) -> int:
    if value is None or value.strip() == "":
        return 30
    try:
        holdout_steps = int(value)
    except ValueError as exc:
        raise ValueError("holdout_steps must be an integer.") from exc
    if holdout_steps < 7 or holdout_steps > 180:
        raise ValueError("holdout_steps must be between 7 and 180.")
    return holdout_steps


def _resolve_mape_threshold(value: str | None) -> float:
    if value is None or value.strip() == "":
        return _DEFAULT_FORECAST_MAPE_THRESHOLD
    try:
        threshold = float(value)
    except ValueError as exc:
        raise ValueError("mape_threshold must be a number.") from exc
    if threshold <= 0 or threshold > 100:
        raise ValueError("mape_threshold must be > 0 and <= 100.")
    return threshold


def _build_forecast_diagnostics_payload(
    *,
    symbol: str | None,
    holdout_steps: int,
    mape_threshold: float,
) -> dict:
    settings = get_settings()
    raw_rows = fetch_market_data_for_forecast_training(
        window_minutes=settings.forecast_training_window_minutes,
        limit_per_source=30000,
        symbol=symbol,
    )
    cleaned_rows = clean_and_engineer(
        raw_rows,
        CleanerConfig(interval="1d", rolling_window=7, spike_threshold_pct=25.0),
    )
    filtered_rows = [row for row in cleaned_rows if abs(float(row.get("z_score") or 0.0)) < 3.0]
    forecast_cfg = ForecastConfig(
        interval_minutes=1440,
        horizon_steps=365,
        min_training_points=90,
        z_filter_threshold=3.0,
    )
    diagnostics = summarize_forecast_diagnostics(
        filtered_rows,
        forecast_cfg,
        holdout_steps=holdout_steps,
    )
    symbols = diagnostics.get("symbols", {}) if isinstance(diagnostics, dict) else {}
    if symbol and symbol not in symbols:
        symbols = {symbol: {"status": "missing", "reason": "symbol_not_available"}}
        diagnostics["symbols"] = symbols

    low_accuracy_symbols: list[str] = []
    degenerate_symbols: list[str] = []
    model_registry: dict[str, dict] = {}
    for symbol_key, metrics in symbols.items():
        if isinstance(metrics, dict):
            if metrics.get("status") == "ok":
                mape = metrics.get("mape")
                if isinstance(mape, (float, int)) and float(mape) > mape_threshold:
                    low_accuracy_symbols.append(symbol_key)
                if bool(metrics.get("degenerate_path")):
                    degenerate_symbols.append(symbol_key)

        metadata = get_model_metadata("forecast", symbol_key) or {}
        persisted = get_forecast_model(symbol_key)
        persisted_kind = persisted.get("kind") if isinstance(persisted, dict) else type(persisted).__name__ if persisted is not None else None
        model_registry[symbol_key] = {
            "artifact": metadata.get("artifact"),
            "trained_at": metadata.get("trained_at"),
            "training_points": metadata.get("training_points"),
            "model_type": metadata.get("model_type"),
            "persisted_kind": persisted_kind,
        }

    return {
        "thresholds": {
            "mape_pct": mape_threshold,
            "holdout_steps": holdout_steps,
            "forecast_config": asdict(forecast_cfg),
        },
        "summary": {
            "raw_dataset_records": len(raw_rows),
            "cleaned_dataset_records": len(cleaned_rows),
            "filtered_dataset_records": len(filtered_rows),
            "evaluated_symbols": sum(1 for item in symbols.values() if isinstance(item, dict) and item.get("status") == "ok"),
            "low_accuracy_symbols": sorted(low_accuracy_symbols),
            "degenerate_symbols": sorted(degenerate_symbols),
        },
        "diagnostics": diagnostics,
        "model_registry": model_registry,
    }


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


@forecast_bp.get("/forecast/diagnostics")
def get_forecast_diagnostics():
    try:
        symbol = parse_symbol(request.args.get("symbol"))
        holdout_steps = _resolve_holdout_steps(request.args.get("holdout_steps"))
        mape_threshold = _resolve_mape_threshold(request.args.get("mape_threshold"))
        payload = _get_cached_diagnostics(symbol, holdout_steps, mape_threshold)
        if payload is None:
            payload = _build_forecast_diagnostics_payload(
                symbol=symbol,
                holdout_steps=holdout_steps,
                mape_threshold=mape_threshold,
            )
            _cache_diagnostics_payload(symbol, holdout_steps, mape_threshold, payload)
        response = build_success_response(
            data=payload,
            source="processing",
            filters={
                key: value
                for key, value in {
                    "symbol": symbol,
                    "holdout_steps": holdout_steps,
                    "mape_threshold": mape_threshold,
                }.items()
                if value is not None
            },
            freshness=fetch_freshness_status(),
            no_data=payload["summary"]["filtered_dataset_records"] == 0,
        )
        return jsonify(response), 200
    except ValueError as exc:
        return jsonify(build_error_response("invalid_input", str(exc))), 400
    except Exception as exc:
        logger.exception("Failed to compute forecast diagnostics")
        return jsonify(
            build_error_response(
                "operation_failed",
                "Failed to compute forecast diagnostics.",
                {"reason": str(exc)},
            )
        ), 500
