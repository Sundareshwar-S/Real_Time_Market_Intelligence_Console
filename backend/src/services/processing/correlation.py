from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math
import warnings

import pandas as pd


@dataclass(frozen=True)
class CorrelationConfig:
    interval: str = "1min"
    rolling_window: int = 20
    shift_threshold: float = 0.35
    min_points: int = 20


def _safe_float(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def compute_correlation_metrics(
    cleaned_records: list[dict],
    cfg: CorrelationConfig | None = None,
) -> list[dict]:
    if not cleaned_records:
        return []

    config = cfg or CorrelationConfig()
    frame = pd.DataFrame(cleaned_records)
    if frame.empty:
        return []

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "symbol", "value"])
    if frame.empty:
        return []

    pivot = (
        frame.set_index("timestamp")
        .groupby("symbol")["value"]
        .resample(config.interval)
        .mean()
        .reset_index()
        .pivot(index="timestamp", columns="symbol", values="value")
        .sort_index()
        .ffill()
        .interpolate(limit_direction="both")
    )

    if pivot.shape[0] < config.min_points or pivot.shape[1] < 2:
        return []

    results: list[dict] = []
    latest_ts = pivot.index.max()

    for symbol_a, symbol_b in combinations(pivot.columns.tolist(), 2):
        pair = pivot[[symbol_a, symbol_b]].dropna()
        if len(pair) < config.min_points:
            continue

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pearson = pair[symbol_a].corr(pair[symbol_b], method="pearson")
            spearman = pair[symbol_a].corr(pair[symbol_b], method="spearman")
            rolling_series = pair[symbol_a].rolling(config.rolling_window).corr(pair[symbol_b]).dropna()
        rolling_latest = _safe_float(rolling_series.iloc[-1]) if not rolling_series.empty else None
        pearson_value = _safe_float(pearson)
        spearman_value = _safe_float(spearman)
        shift_detected = False
        if rolling_series.size > 5:
            baseline = _safe_float(rolling_series.iloc[:-1].mean())
            if baseline is not None and rolling_latest is not None:
                shift_detected = abs(rolling_latest - baseline) >= config.shift_threshold

        if pearson_value is None and spearman_value is None and rolling_latest is None:
            continue

        results.append(
            {
                "symbol_a": symbol_a,
                "symbol_b": symbol_b,
                "source": "processing",
                "window_minutes": config.rolling_window,
                "pearson": pearson_value,
                "spearman": spearman_value,
                "rolling_corr": rolling_latest,
                "shift_detected": shift_detected,
                "timestamp": latest_ts.isoformat(),
            }
        )

    return results
