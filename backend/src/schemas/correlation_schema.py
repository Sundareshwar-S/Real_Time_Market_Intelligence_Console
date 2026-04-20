from __future__ import annotations

import math


def _safe_number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def map_correlation_item(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "symbol_a": row.get("symbol_a"),
        "symbol_b": row.get("symbol_b"),
        "source": row.get("source"),
        "window_minutes": row.get("window_minutes"),
        "pearson": _safe_number(row.get("pearson")),
        "spearman": _safe_number(row.get("spearman")),
        "rolling_corr": _safe_number(row.get("rolling_corr")),
        "shift_detected": row.get("shift_detected"),
        "timestamp": row.get("timestamp"),
    }


def build_correlation_payload(records: list[dict]) -> dict:
    pairs = [map_correlation_item(item) for item in records]
    updated_at = pairs[0]["timestamp"] if pairs else None
    return {
        "pairs": pairs,
        "updated_at": updated_at,
    }
