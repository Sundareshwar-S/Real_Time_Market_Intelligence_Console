from __future__ import annotations

import re


_LEGACY_HORIZON_RE = re.compile(r"^t\+(\d+)\*(.+)$")


def _parse_legacy_horizon(horizon: str | None) -> tuple[int | None, str | None]:
    value = str(horizon or "").strip()
    if not value:
        return None, None
    match = _LEGACY_HORIZON_RE.match(value)
    if not match:
        return None, None
    step, interval = match.groups()
    try:
        return int(step), interval
    except ValueError:
        return None, None


def map_forecast_item(row: dict) -> dict:
    horizon_step = row.get("horizon_step")
    interval = row.get("interval")
    if horizon_step is None or interval is None:
        legacy_step, legacy_interval = _parse_legacy_horizon(row.get("horizon"))
        if horizon_step is None:
            horizon_step = legacy_step
        if interval is None:
            interval = legacy_interval
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol") or row.get("target_symbol"),
        "source": row.get("source"),
        "model": row.get("model"),
        "horizon_step": horizon_step,
        "interval": interval,
        "predicted_value": row.get("predicted_value"),
        "lower_bound": row.get("lower_bound"),
        "upper_bound": row.get("upper_bound"),
        "confidence": row.get("confidence"),
        "unit": row.get("unit"),
        "generated_at": row.get("generated_at"),
        "created_at": row.get("created_at"),
    }


def build_forecast_payload(records: list[dict]) -> dict:
    predictions = [map_forecast_item(item) for item in records]
    generated_at = predictions[0]["generated_at"] if predictions else None
    units_by_symbol = {}
    for row in predictions:
        symbol = row.get("symbol")
        unit = row.get("unit")
        if symbol and unit:
            units_by_symbol[str(symbol).upper()] = unit
    return {
        "predictions": predictions,
        "generated_at": generated_at,
        "units_by_symbol": units_by_symbol,
    }
