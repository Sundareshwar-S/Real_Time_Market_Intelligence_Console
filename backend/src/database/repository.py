from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any

from pymongo import ASCENDING, DESCENDING, UpdateOne

from .db import collection_map, get_collection

_ACTIVE_MARKET_SOURCES = {"crypto", "stock"}
_WEATHER_SOURCE_ALIASES = {"weather", "openweather"}
_MAX_MARKET_READ_LIMIT = 1000
_MAX_MARKET_READ_WINDOW = 3000
_MAX_MARKET_SERIES_SCAN_WINDOW = 200000

_MARKET_PROJECTION = {
    "_id": 1,
    "symbol": 1,
    "name": 1,
    "source": 1,
    "price": 1,
    "change_24h": 1,
    "volume_24h": 1,
    "market_cap": 1,
    "captured_at": 1,
    "created_at": 1,
}
_MARKET_SERIES_PROJECTION = {
    "_id": 0,
    "symbol": 1,
    "source": 1,
    "price": 1,
    "captured_at": 1,
}
_FORECAST_PROJECTION = {
    "_id": 1,
    "model": 1,
    "target_symbol": 1,
    "horizon": 1,
    "source": 1,
    "predicted_value": 1,
    "confidence": 1,
    "generated_at": 1,
    "created_at": 1,
}
_ALERT_PROJECTION = {
    "_id": 1,
    "severity": 1,
    "alert_type": 1,
    "source": 1,
    "message": 1,
    "is_active": 1,
    "triggered_at": 1,
    "created_at": 1,
}
_PROCESSED_PROJECTION = {
    "_id": 1,
    "symbol": 1,
    "source": 1,
    "timestamp": 1,
    "value": 1,
    "pct_change": 1,
    "rolling_mean": 1,
    "rolling_std": 1,
    "z_score": 1,
    "created_at": 1,
}
_ANOMALY_PROJECTION = {
    "_id": 1,
    "symbol": 1,
    "source": 1,
    "timestamp": 1,
    "value": 1,
    "anomaly_type": 1,
    "anomaly_score": 1,
    "severity": 1,
    "method": 1,
    "is_anomaly": 1,
    "created_at": 1,
}
_FORECAST_OUTPUT_PROJECTION = {
    "_id": 1,
    "symbol": 1,
    "target_symbol": 1,
    "source": 1,
    "model": 1,
    "horizon_step": 1,
    "horizon": 1,
    "interval": 1,
    "predicted_value": 1,
    "lower_bound": 1,
    "upper_bound": 1,
    "confidence": 1,
    "unit": 1,
    "generated_at": 1,
    "created_at": 1,
}
_CORRELATION_PROJECTION = {
    "_id": 1,
    "symbol_a": 1,
    "symbol_b": 1,
    "source": 1,
    "window_minutes": 1,
    "pearson": 1,
    "spearman": 1,
    "rolling_corr": 1,
    "shift_detected": 1,
    "timestamp": 1,
    "created_at": 1,
}
_SCHEDULER_JOB_PROJECTION = {
    "_id": 1,
    "job_name": 1,
    "status": 1,
    "details": 1,
    "started_at": 1,
    "finished_at": 1,
    "duration_ms": 1,
    "created_at": 1,
}
_FRESHNESS_PROJECTION = {
    "_id": 1,
    "source": 1,
    "last_update": 1,
    "is_stale": 1,
    "message": 1,
    "updated_at": 1,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    if not value:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str | datetime | None, field_name: str) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.astimezone(timezone.utc)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be ISO datetime.") from exc
    raise ValueError(f"{field_name} is required.")


def _coerce_float(value: Any, field_name: str, allow_none: bool = False) -> float | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} is required.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric.") from exc


def _serialize(document: dict) -> dict:
    doc = dict(document)
    if "_id" in doc:
        doc["id"] = str(doc.pop("_id"))
    for key, value in list(doc.items()):
        if isinstance(value, datetime):
            doc[key] = _to_iso(value)
    return doc


def _market_collection_for_source(source: str) -> str:
    mapping = collection_map()
    source_lower = source.lower()
    if source_lower in _WEATHER_SOURCE_ALIASES:
        return mapping["market_data_weather"]
    if source_lower in {"polygon", "stock"}:
        return mapping["market_data_stock"]
    return mapping["market_data_crypto"]


def _active_market_collection_for_source(source: str) -> str | None:
    source_lower = source.lower()
    if source_lower in _WEATHER_SOURCE_ALIASES:
        return None
    mapping = collection_map()
    if source_lower in {"polygon", "stock"}:
        return mapping["market_data_stock"]
    return mapping["market_data_crypto"]


def _all_active_market_collections() -> list[str]:
    mapping = collection_map()
    return [
        mapping["market_data_crypto"],
        mapping["market_data_stock"],
    ]


def _sort_and_limit(records: list[dict], key: str, limit: int) -> list[dict]:
    ordered = sorted(records, key=lambda item: item.get(key) or "", reverse=True)
    return ordered[:limit]


def _build_time_filter(
    query: dict[str, Any],
    field_name: str,
    start_time: str | datetime | None,
    end_time: str | datetime | None,
) -> None:
    if start_time is None and end_time is None:
        return
    range_query: dict[str, Any] = {}
    if start_time is not None:
        range_query["$gte"] = _parse_datetime(start_time, field_name)
    if end_time is not None:
        range_query["$lte"] = _parse_datetime(end_time, field_name)
    query[field_name] = range_query


def _normalize_market_document(payload: dict) -> dict:
    symbol = payload.get("symbol")
    if not symbol:
        raise ValueError("symbol is required.")

    now = _utc_now()
    source = str(payload.get("source") or "api")
    price_value = payload.get("price")
    if price_value is None:
        price_value = payload.get("value")

    price = _coerce_float(price_value, "price")
    if price is None or price <= 0:
        raise ValueError("price must be > 0.")

    return {
        "symbol": str(symbol).upper(),
        "name": str(payload.get("name") or symbol),
        "source": source,
        "price": price,
        "change_24h": _coerce_float(payload.get("change_24h"), "change_24h", allow_none=True),
        "volume_24h": _coerce_float(payload.get("volume_24h"), "volume_24h", allow_none=True),
        "market_cap": _coerce_float(payload.get("market_cap"), "market_cap", allow_none=True),
        "captured_at": _parse_datetime(payload["captured_at"], "captured_at")
        if payload.get("captured_at")
        else now,
        "created_at": now,
    }


def save_market_data(payload: dict) -> dict:
    document = _normalize_market_document(payload)
    collection_name = _market_collection_for_source(document["source"])
    result = get_collection(collection_name).insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize(document)


def upsert_market_data(payload: dict) -> dict:
    document = _normalize_market_document(payload)
    collection_name = _market_collection_for_source(document["source"])
    collection = get_collection(collection_name)

    query = {
        "symbol": document["symbol"],
        "source": document["source"],
        "captured_at": document["captured_at"],
    }
    update_set = {
        "name": document["name"],
        "price": document["price"],
        "change_24h": document["change_24h"],
        "volume_24h": document["volume_24h"],
    }
    market_cap = document.get("market_cap")
    if market_cap is not None:
        update_set["market_cap"] = market_cap

    update = {
        "$set": update_set,
        "$setOnInsert": {"created_at": document["created_at"]},
    }
    collection.update_one(query, update, upsert=True)

    source_value = str(document.get("source") or "").lower()
    if source_value in {"stock", "polygon"} and market_cap is not None and market_cap > 0:
        collection.update_many(
            {
                "symbol": document["symbol"],
                "source": document["source"],
                "$or": [
                    {"market_cap": None},
                    {"market_cap": {"$exists": False}},
                    {"market_cap": 0},
                ],
            },
            {"$set": {"market_cap": market_cap}},
        )

    saved = collection.find_one(query)
    if not saved:
        raise ValueError("Failed to upsert market data record.")
    return _serialize(saved)


def fetch_market_data(
    limit: int = 50,
    symbol: str | None = None,
    source: str | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(limit, _MAX_MARKET_READ_LIMIT))
    safe_offset = max(0, offset)
    window = min(_MAX_MARKET_READ_WINDOW, safe_limit + safe_offset)
    query = {"symbol": symbol.upper()} if symbol else {}
    collection_names = _all_active_market_collections()
    if source:
        source_value = source.lower()
        query["source"] = source_value
        source_collection = _active_market_collection_for_source(source_value)
        collection_names = [source_collection] if source_collection else []
    _build_time_filter(query, "captured_at", start_time, end_time)
    output: list[dict] = []
    for collection_name in collection_names:
        cursor = (
            get_collection(collection_name)
            .find(query, _MARKET_PROJECTION)
            .sort("captured_at", DESCENDING)
            .limit(window)
            .batch_size(500)
        )
        output.extend(_serialize(item) for item in cursor)
    ordered = sorted(output, key=lambda item: item.get("captured_at") or "", reverse=True)
    return ordered[safe_offset : safe_offset + safe_limit]


def fetch_market_stream_data(
    limit_per_source: int = 12,
    symbol: str | None = None,
    source: str | None = None,
) -> list[dict]:
    safe_limit = max(1, min(limit_per_source, 200))
    query: dict[str, Any] = {"symbol": symbol.upper()} if symbol else {}
    collection_names = _all_active_market_collections()
    if source:
        source_value = source.lower()
        query["source"] = source_value
        source_collection = _active_market_collection_for_source(source_value)
        collection_names = [source_collection] if source_collection else []

    output: list[dict] = []
    for collection_name in collection_names:
        cursor = (
            get_collection(collection_name)
            .find(query, _MARKET_PROJECTION)
            .sort("captured_at", DESCENDING)
            .limit(safe_limit)
            .batch_size(200)
        )
        output.extend(_serialize(item) for item in cursor)
    return _sort_and_limit(output, "captured_at", safe_limit * len(collection_names))


def fetch_latest_market_data(
    symbol: str | None = None,
    source: str | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
) -> dict | None:
    records = fetch_market_data(
        limit=1,
        symbol=symbol,
        source=source,
        start_time=start_time,
        end_time=end_time,
    )
    return records[0] if records else None


def fetch_market_data_rolling(
    window_minutes: int,
    limit: int = 5000,
    symbol: str | None = None,
    source: str | None = None,
) -> list[dict]:
    safe_window = max(1, int(window_minutes))
    start_time = _utc_now() - timedelta(minutes=safe_window)
    return fetch_market_data(
        limit=limit,
        symbol=symbol,
        source=source,
        start_time=start_time,
        end_time=_utc_now(),
    )


def fetch_market_data_for_forecast_training(
    *,
    window_minutes: int,
    limit_per_source: int = 30000,
    symbol: str | None = None,
) -> list[dict]:
    safe_window = max(1, int(window_minutes))
    safe_limit = max(1000, min(int(limit_per_source), 500000))
    start_time = _utc_now() - timedelta(minutes=safe_window)
    end_time = _utc_now()
    query: dict[str, Any] = {}
    _build_time_filter(query, "captured_at", start_time, end_time)
    if symbol:
        query["symbol"] = symbol.upper()

    mapping = collection_map()
    source_collections = {
        "crypto": mapping["market_data_crypto"],
        "stock": mapping["market_data_stock"],
    }

    latest_by_symbol_day: dict[tuple[str, str, str], dict[str, Any]] = {}
    for source, collection_name in source_collections.items():
        cursor = (
            get_collection(collection_name)
            .find(query, _MARKET_SERIES_PROJECTION)
            .sort("captured_at", DESCENDING)
            .limit(safe_limit)
            .batch_size(1000)
        )
        for row in cursor:
            captured_at = row.get("captured_at")
            symbol = str(row.get("symbol") or "").upper()
            value = row.get("price")
            if not isinstance(captured_at, datetime) or not symbol:
                continue
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric_value) or numeric_value <= 0:
                continue
            day_key = _to_iso(captured_at.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))
            if not day_key:
                continue
            key = (source, symbol, day_key)
            existing = latest_by_symbol_day.get(key)
            if existing and existing["captured_at"] >= captured_at:
                continue
            latest_by_symbol_day[key] = {
                "symbol": symbol,
                "source": source,
                "price": numeric_value,
                "captured_at": captured_at,
            }

    ordered = sorted(
        (_serialize(item) for item in latest_by_symbol_day.values()),
        key=lambda row: row.get("captured_at") or "",
    )
    return ordered


def _bucket_market_timestamp(value: datetime, bucket: str) -> datetime:
    target = value.astimezone(timezone.utc)
    if bucket == "1h":
        return target.replace(minute=0, second=0, microsecond=0)
    if bucket == "4h":
        return target.replace(hour=(target.hour // 4) * 4, minute=0, second=0, microsecond=0)
    if bucket == "1d":
        return target.replace(hour=0, minute=0, second=0, microsecond=0)
    if bucket == "1w":
        day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.weekday())
    if bucket == "1m":
        return target.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    raise ValueError("bucket must be one of: 1h, 4h, 1d, 1w, 1m")


def _reduce_points(points: list[dict], max_points: int) -> list[dict]:
    if len(points) <= max_points:
        return points
    if max_points <= 1:
        return points[-1:]
    last_index = len(points) - 1
    selected_indexes = {
        round(i * last_index / (max_points - 1))
        for i in range(max_points)
    }
    return [point for index, point in enumerate(points) if index in selected_indexes]


def _estimate_market_series_scan_window(
    *,
    start_dt: datetime,
    end_dt: datetime,
    bucket: str,
    context: str,
    symbol: str | None = None,
) -> int:
    bucket_seconds = {
        "1h": 3600,
        "4h": 4 * 3600,
        "1d": 24 * 3600,
        "1w": 7 * 24 * 3600,
        "1m": 30 * 24 * 3600,
    }.get(bucket, 3600)
    span_seconds = max(bucket_seconds, int((end_dt - start_dt).total_seconds()))
    expected_bucket_count = max(1, math.ceil(span_seconds / bucket_seconds))
    estimated_symbols = 8 if context == "all" else 4
    if symbol and context in {"crypto", "stock"}:
        estimated_symbols = 1
    oversample_per_bucket = {
        "1h": 50,
        "4h": 20,
        "1d": 8,
        "1w": 4,
        "1m": 2,
    }.get(bucket, 20)
    dynamic_window = expected_bucket_count * estimated_symbols * oversample_per_bucket
    return max(_MAX_MARKET_READ_WINDOW, min(dynamic_window, _MAX_MARKET_SERIES_SCAN_WINDOW))


def fetch_market_series(
    *,
    context: str = "all",
    symbol: str | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    bucket: str = "4h",
    max_points: int = 180,
) -> list[dict]:
    active_context = (context or "all").lower()
    if active_context not in {"all", "crypto", "stock"}:
        raise ValueError("context must be one of: all, crypto, stock")

    if start_time is None and end_time is None:
        end_dt = _utc_now()
        start_dt = end_dt - timedelta(days=30)
    else:
        end_dt = _parse_datetime(end_time, "end_time") if end_time else _utc_now()
        start_dt = _parse_datetime(start_time, "start_time") if start_time else end_dt - timedelta(days=30)
    if end_dt < start_dt:
        raise ValueError("end_time must be >= start_time.")

    selected_sources = {"crypto", "stock"} if active_context == "all" else {active_context}
    selected_symbol = str(symbol or "").strip().upper() or None
    if active_context == "all":
        selected_symbol = None
    query: dict[str, Any] = {}
    _build_time_filter(query, "captured_at", start_dt, end_dt)
    if selected_symbol:
        query["symbol"] = selected_symbol
    mapping = collection_map()
    source_collection = {
        "crypto": mapping["market_data_crypto"],
        "stock": mapping["market_data_stock"],
    }

    latest_by_bucket_symbol: dict[tuple[str, str], dict] = {}
    scan_window = _estimate_market_series_scan_window(
        start_dt=start_dt,
        end_dt=end_dt,
        bucket=bucket,
        context=active_context,
        symbol=selected_symbol,
    )
    for source in selected_sources:
        collection_name = source_collection[source]
        cursor = (
            get_collection(collection_name)
            .find(query, _MARKET_SERIES_PROJECTION)
            .sort("captured_at", DESCENDING)
            .limit(scan_window)
            .batch_size(500)
        )
        for row in cursor:
            captured_at = row.get("captured_at")
            if not isinstance(captured_at, datetime):
                continue
            bucket_dt = _bucket_market_timestamp(captured_at, bucket)
            bucket_key = _to_iso(bucket_dt)
            if not bucket_key:
                continue
            symbol = str(row.get("symbol") or "").upper()
            if not symbol:
                continue
            key = (bucket_key, f"{source}:{symbol}")
            existing = latest_by_bucket_symbol.get(key)
            if existing and existing["captured_at"] >= captured_at:
                continue
            value = row.get("price")
            try:
                numeric_value = float(value)
            except (TypeError, ValueError):
                continue
            if not math.isfinite(numeric_value) or numeric_value <= 0:
                continue
            latest_by_bucket_symbol[key] = {
                "bucket": bucket_key,
                "captured_at": captured_at,
                "source": source,
                "value": numeric_value,
            }

    totals_by_bucket: dict[str, dict] = {}
    for point in latest_by_bucket_symbol.values():
        bucket_key = point["bucket"]
        if bucket_key not in totals_by_bucket:
            totals_by_bucket[bucket_key] = {
                "timestamp": bucket_key,
                "total": 0.0,
                "crypto": None,
                "stock": None,
            }
        bucket = totals_by_bucket[bucket_key]
        source_key = point["source"]
        current_source_total = bucket[source_key]
        bucket[source_key] = (current_source_total or 0.0) + point["value"]
        bucket["total"] += point["value"]

    ordered = [totals_by_bucket[key] for key in sorted(totals_by_bucket.keys())]
    return _reduce_points(ordered, max(1, min(max_points, 1500)))


def save_forecast(payload: dict) -> dict:
    model = payload.get("model")
    target_symbol = payload.get("target_symbol")
    horizon = payload.get("horizon")
    if not model or not target_symbol or not horizon:
        raise ValueError("model, target_symbol, and horizon are required.")

    now = _utc_now()
    document = {
        "model": str(model),
        "target_symbol": str(target_symbol).upper(),
        "horizon": str(horizon),
        "source": str(payload.get("source") or "api"),
        "predicted_value": _coerce_float(payload.get("predicted_value"), "predicted_value"),
        "confidence": _coerce_float(payload.get("confidence"), "confidence", allow_none=True),
        "generated_at": _parse_datetime(payload["generated_at"], "generated_at")
        if payload.get("generated_at")
        else now,
        "created_at": now,
    }
    result = get_collection(collection_map()["forecast_outputs"]).insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize(document)


def fetch_forecasts(
    limit: int = 50,
    target_symbol: str | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    query = {"target_symbol": target_symbol.upper()} if target_symbol else {}
    # Forecast history views are run-history based, so filter by creation time
    # instead of target prediction timestamps.
    _build_time_filter(query, "created_at", start_time, end_time)
    cursor = (
        get_collection(collection_map()["forecast_outputs"])
        .find(query, _FORECAST_PROJECTION)
        .sort("generated_at", DESCENDING)
        .skip(safe_offset)
        .limit(safe_limit)
        .batch_size(200)
    )
    return [_serialize(item) for item in cursor]


def fetch_latest_forecast(target_symbol: str | None = None) -> dict | None:
    records = fetch_forecasts(limit=1, target_symbol=target_symbol)
    return records[0] if records else None


def save_alert(payload: dict) -> dict:
    severity = payload.get("severity")
    alert_type = payload.get("alert_type")
    message = payload.get("message")
    if not severity or not alert_type or not message:
        raise ValueError("severity, alert_type, and message are required.")

    now = _utc_now()
    document = {
        "severity": str(severity).lower(),
        "alert_type": str(alert_type),
        "source": str(payload.get("source") or "api"),
        "message": str(message),
        "is_active": bool(payload.get("is_active", True)),
        "triggered_at": _parse_datetime(payload["triggered_at"], "triggered_at")
        if payload.get("triggered_at")
        else now,
        "created_at": now,
    }
    result = get_collection(collection_map()["alerts"]).insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize(document)


def fetch_alerts(
    limit: int = 50,
    active_only: bool = False,
    severity: str | None = None,
    source: str | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(limit, 500))
    safe_offset = max(0, offset)
    query = {"is_active": True} if active_only else {}
    if severity:
        query["severity"] = severity.lower()
    if source:
        query["source"] = source.lower()
    _build_time_filter(query, "triggered_at", start_time, end_time)
    cursor = (
        get_collection(collection_map()["alerts"])
        .find(query, _ALERT_PROJECTION)
        .sort("triggered_at", DESCENDING)
        .skip(safe_offset)
        .limit(safe_limit)
        .batch_size(200)
    )
    return [_serialize(item) for item in cursor]


def fetch_latest_alert(active_only: bool = False) -> dict | None:
    records = fetch_alerts(limit=1, active_only=active_only)
    return records[0] if records else None


def save_processed_data(records: list[dict]) -> list[dict]:
    if not records:
        return []
    now = _utc_now()
    docs = []
    for item in records:
        docs.append(
            {
                "symbol": str(item["symbol"]).upper(),
                "source": str(item.get("source") or "processing"),
                "timestamp": _parse_datetime(item.get("timestamp"), "timestamp"),
                "value": _coerce_float(item.get("value"), "value"),
                "pct_change": _coerce_float(item.get("pct_change"), "pct_change", allow_none=True),
                "rolling_mean": _coerce_float(item.get("rolling_mean"), "rolling_mean", allow_none=True),
                "rolling_std": _coerce_float(item.get("rolling_std"), "rolling_std", allow_none=True),
                "z_score": _coerce_float(item.get("z_score"), "z_score", allow_none=True),
                "created_at": now,
            }
        )
    collection = get_collection(collection_map()["processed_data"])
    result = collection.insert_many(docs)
    return [_serialize({**doc, "_id": oid}) for doc, oid in zip(docs, result.inserted_ids)]


def fetch_processed_data(limit: int = 500, symbol: str | None = None) -> list[dict]:
    safe_limit = max(1, min(limit, 5000))
    query = {"symbol": symbol.upper()} if symbol else {}
    cursor = (
        get_collection(collection_map()["processed_data"])
        .find(query, _PROCESSED_PROJECTION)
        .sort("timestamp", DESCENDING)
        .limit(safe_limit)
        .batch_size(300)
    )
    return [_serialize(item) for item in cursor]


def fetch_processed_data_rolling(
    window_minutes: int,
    limit: int = 5000,
    symbol: str | None = None,
) -> list[dict]:
    safe_window = max(1, int(window_minutes))
    start_time = _utc_now() - timedelta(minutes=safe_window)
    query: dict[str, Any] = {"timestamp": {"$gte": start_time, "$lte": _utc_now()}}
    if symbol:
        query["symbol"] = symbol.upper()
    cursor = (
        get_collection(collection_map()["processed_data"])
        .find(query, _PROCESSED_PROJECTION)
        .sort("timestamp", DESCENDING)
        .limit(max(1, min(limit, 5000)))
        .batch_size(300)
    )
    return [_serialize(item) for item in cursor]


def save_anomaly_events(records: list[dict]) -> list[dict]:
    if not records:
        return []
    now = _utc_now()
    docs_by_identity: dict[tuple[str, str, datetime, str, str], dict] = {}
    for item in records:
        document = {
            "symbol": str(item["symbol"]).upper(),
            "source": str(item.get("source") or "processing"),
            "timestamp": _parse_datetime(item.get("timestamp"), "timestamp"),
            "value": _coerce_float(item.get("value"), "value"),
            "anomaly_type": str(item.get("anomaly_type") or "volatility"),
            "anomaly_score": _coerce_float(item.get("anomaly_score"), "anomaly_score"),
            "severity": str(item.get("severity") or "low"),
            "method": str(item.get("method") or "zscore+isolation_forest"),
            "is_anomaly": bool(item.get("is_anomaly", False)),
        }
        identity = (
            document["symbol"],
            document["source"],
            document["timestamp"],
            document["anomaly_type"],
            document["method"],
        )
        docs_by_identity[identity] = document

    if not docs_by_identity:
        return []

    collection = get_collection(collection_map()["anomaly_events"])
    operations = []
    for symbol, source, timestamp, anomaly_type, method in docs_by_identity:
        document = docs_by_identity[(symbol, source, timestamp, anomaly_type, method)]
        operations.append(
            UpdateOne(
                {
                    "symbol": symbol,
                    "source": source,
                    "timestamp": timestamp,
                    "anomaly_type": anomaly_type,
                    "method": method,
                },
                {
                    "$set": {
                        "value": document["value"],
                        "anomaly_score": document["anomaly_score"],
                        "severity": document["severity"],
                        "is_anomaly": document["is_anomaly"],
                        "updated_at": now,
                    },
                    "$setOnInsert": {
                        "created_at": now,
                    },
                },
                upsert=True,
            )
        )
    collection.bulk_write(operations, ordered=False)

    return [
        _serialize(
            {
                **document,
                "created_at": now,
                "updated_at": now,
            }
        )
        for document in docs_by_identity.values()
    ]


def fetch_anomaly_events(
    limit: int = 200,
    symbol: str | None = None,
    source: str | None = None,
    anomalies_only: bool = True,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(limit, 5000))
    safe_offset = max(0, offset)
    query: dict[str, Any] = {}
    if symbol:
        query["symbol"] = symbol.upper()
    if source:
        query["source"] = source.lower()
    if anomalies_only:
        query["is_anomaly"] = True
    _build_time_filter(query, "timestamp", start_time, end_time)
    pipeline = [
        {"$match": query},
        {"$sort": {"timestamp": -1, "created_at": -1}},
        {
            "$group": {
                "_id": {
                    "symbol": "$symbol",
                    "source": "$source",
                    "timestamp": "$timestamp",
                    "anomaly_type": "$anomaly_type",
                    "method": "$method",
                },
                "doc": {"$first": "$$ROOT"},
            }
        },
        {"$replaceRoot": {"newRoot": "$doc"}},
        {"$sort": {"timestamp": -1, "created_at": -1}},
        {"$skip": safe_offset},
        {"$limit": safe_limit},
        {"$project": _ANOMALY_PROJECTION},
    ]
    cursor = get_collection(collection_map()["anomaly_events"]).aggregate(
        pipeline,
        allowDiskUse=True,
    )
    return [_serialize(item) for item in cursor]


def fetch_training_dataset(
    window_minutes: int,
    symbol: str | None = None,
    limit: int = 5000,
    exclude_anomalies: bool = False,
) -> list[dict]:
    safe_window = max(1, int(window_minutes))
    window_end = _utc_now()
    window_start = window_end - timedelta(minutes=safe_window)
    processed_rows = fetch_processed_data_rolling(
        window_minutes=safe_window,
        limit=limit,
        symbol=symbol,
    )
    if not exclude_anomalies:
        return processed_rows

    anomaly_limit = max(limit, len(processed_rows))
    anomaly_rows = fetch_anomaly_events(
        limit=anomaly_limit,
        symbol=symbol,
        anomalies_only=True,
        start_time=window_start,
        end_time=window_end,
    )
    anomaly_index = {
        (str(item.get("symbol", "")).upper(), str(item.get("timestamp")))
        for item in anomaly_rows
    }
    return [
        row
        for row in processed_rows
        if (str(row.get("symbol", "")).upper(), str(row.get("timestamp"))) not in anomaly_index
    ]


def save_forecast_outputs(records: list[dict]) -> list[dict]:
    if not records:
        return []
    now = _utc_now()
    docs = []
    for item in records:
        docs.append(
            {
                "symbol": str(item["symbol"]).upper(),
                "source": str(item.get("source") or "processing").lower(),
                "model": str(item.get("model") or "rolling_fallback"),
                "horizon_step": int(item.get("horizon_step", 1)),
                "interval": str(item.get("interval") or "1m"),
                "predicted_value": _coerce_float(item.get("predicted_value"), "predicted_value"),
                "lower_bound": _coerce_float(item.get("lower_bound"), "lower_bound", allow_none=True),
                "upper_bound": _coerce_float(item.get("upper_bound"), "upper_bound", allow_none=True),
                "confidence": _coerce_float(item.get("confidence"), "confidence", allow_none=True),
                "unit": str(item.get("unit") or "").upper() or None,
                "generated_at": _parse_datetime(item.get("generated_at"), "generated_at"),
                "created_at": now,
            }
        )
    collection = get_collection(collection_map()["forecast_outputs"])
    result = collection.insert_many(docs)
    return [_serialize({**doc, "_id": oid}) for doc, oid in zip(docs, result.inserted_ids)]


def fetch_forecast_outputs(
    limit: int = 200,
    symbol: str | None = None,
    model: str | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(limit, 5000))
    safe_offset = max(0, offset)
    query = {"symbol": symbol.upper()} if symbol else {}
    if model:
        query["model"] = model
    # Filter by run timestamp (created_at) for dashboard history windows.
    _build_time_filter(query, "created_at", start_time, end_time)
    cursor = (
        get_collection(collection_map()["forecast_outputs"])
        .find(query, _FORECAST_OUTPUT_PROJECTION)
        .sort(
            [
                ("created_at", DESCENDING),
                ("symbol", ASCENDING),
                ("horizon_step", ASCENDING),
                ("generated_at", ASCENDING),
            ]
        )
        .skip(safe_offset)
        .limit(safe_limit)
        .batch_size(300)
    )
    return [_serialize(item) for item in cursor]


def save_correlation_metrics(records: list[dict]) -> list[dict]:
    if not records:
        return []
    now = _utc_now()
    docs = []
    for item in records:
        docs.append(
            {
                "symbol_a": str(item["symbol_a"]).upper(),
                "symbol_b": str(item["symbol_b"]).upper(),
                "source": str(item.get("source") or "processing"),
                "window_minutes": int(item.get("window_minutes", 60)),
                "pearson": _coerce_float(item.get("pearson"), "pearson", allow_none=True),
                "spearman": _coerce_float(item.get("spearman"), "spearman", allow_none=True),
                "rolling_corr": _coerce_float(item.get("rolling_corr"), "rolling_corr", allow_none=True),
                "shift_detected": bool(item.get("shift_detected", False)),
                "timestamp": _parse_datetime(item.get("timestamp"), "timestamp"),
                "created_at": now,
            }
        )
    collection = get_collection(collection_map()["correlation_metrics"])
    result = collection.insert_many(docs)
    return [_serialize({**doc, "_id": oid}) for doc, oid in zip(docs, result.inserted_ids)]


def fetch_correlation_metrics(
    limit: int = 200,
    symbol: str | None = None,
    shift_only: bool | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
    offset: int = 0,
) -> list[dict]:
    safe_limit = max(1, min(limit, 5000))
    safe_offset = max(0, offset)
    query: dict[str, Any] = {}
    if symbol:
        symbol_key = symbol.upper()
        query["$or"] = [{"symbol_a": symbol_key}, {"symbol_b": symbol_key}]
    if shift_only is True:
        query["shift_detected"] = True
    _build_time_filter(query, "timestamp", start_time, end_time)
    cursor = (
        get_collection(collection_map()["correlation_metrics"])
        .find(query, _CORRELATION_PROJECTION)
        .sort("timestamp", DESCENDING)
        .skip(safe_offset)
        .limit(safe_limit)
        .batch_size(300)
    )
    return [_serialize(item) for item in cursor]


def save_scheduler_job_log(payload: dict) -> dict:
    now = _utc_now()
    document = {
        "job_name": str(payload.get("job_name") or "unknown"),
        "status": str(payload.get("status") or "unknown"),
        "details": payload.get("details") or {},
        "started_at": _parse_datetime(payload["started_at"], "started_at")
        if payload.get("started_at")
        else now,
        "finished_at": _parse_datetime(payload["finished_at"], "finished_at")
        if payload.get("finished_at")
        else now,
        "duration_ms": _coerce_float(payload.get("duration_ms"), "duration_ms", allow_none=True),
        "created_at": now,
    }
    result = get_collection(collection_map()["scheduler_jobs"]).insert_one(document)
    document["_id"] = result.inserted_id
    return _serialize(document)


def fetch_scheduler_job_logs(
    limit: int = 200,
    offset: int = 0,
    job_name: str | None = None,
    status: str | None = None,
    start_time: str | datetime | None = None,
    end_time: str | datetime | None = None,
) -> list[dict]:
    safe_limit = max(1, min(limit, 5000))
    safe_offset = max(0, offset)
    query: dict[str, Any] = {}
    if job_name:
        query["job_name"] = job_name
    if status:
        query["status"] = status
    _build_time_filter(query, "started_at", start_time, end_time)
    cursor = (
        get_collection(collection_map()["scheduler_jobs"])
        .find(query, _SCHEDULER_JOB_PROJECTION)
        .sort("started_at", DESCENDING)
        .skip(safe_offset)
        .limit(safe_limit)
        .batch_size(200)
    )
    return [_serialize(item) for item in cursor]


def upsert_freshness_status(source: str, payload: dict) -> dict:
    now = _utc_now()
    document = {
        "source": source,
        "last_update": _parse_datetime(payload["last_update"], "last_update")
        if payload.get("last_update")
        else now,
        "is_stale": bool(payload.get("is_stale", False)),
        "message": str(payload.get("message") or ""),
        "updated_at": now,
    }
    collection = get_collection(collection_map()["freshness_status"])
    collection.update_one({"source": source}, {"$set": document}, upsert=True)
    saved = collection.find_one({"source": source})
    return _serialize(saved or document)


def fetch_freshness_status(source: str | None = None, include_inactive: bool = False) -> list[dict]:
    if source:
        source_value = source.lower()
        query: dict[str, Any] = {"source": source_value}
    else:
        query = {} if include_inactive else {"source": {"$in": sorted(_ACTIVE_MARKET_SOURCES)}}
    cursor = (
        get_collection(collection_map()["freshness_status"])
        .find(query, _FRESHNESS_PROJECTION)
        .sort("source", DESCENDING)
        .batch_size(100)
    )
    return [_serialize(item) for item in cursor]
