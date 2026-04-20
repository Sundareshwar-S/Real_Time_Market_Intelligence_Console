from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CleanerConfig:
    interval: str = "1min"
    rolling_window: int = 5
    spike_threshold_pct: float = 5.0


def clean_and_engineer(
    raw_rows: list[dict],
    config: CleanerConfig | None = None,
) -> list[dict]:
    if not raw_rows:
        return []

    cfg = config or CleanerConfig()
    frame = pd.DataFrame(raw_rows)
    if frame.empty:
        return []

    frame["timestamp"] = pd.to_datetime(
        frame.get("captured_at", frame.get("timestamp")),
        utc=True,
        errors="coerce",
    )
    frame["symbol"] = frame.get("symbol", "").astype(str).str.upper()
    frame["source"] = frame.get("source", "unknown").astype(str)
    frame["value"] = pd.to_numeric(frame.get("price", frame.get("value")), errors="coerce")

    frame = frame.dropna(subset=["timestamp", "symbol", "value"])
    frame = frame[frame["value"] > 0]
    if frame.empty:
        return []

    normalized: list[dict] = []
    for symbol, group in frame.groupby("symbol"):
        symbol_df = group.sort_values("timestamp").set_index("timestamp")
        source_name = str(symbol_df["source"].iloc[-1])
        symbol_df = symbol_df[["value"]]

        resampled = symbol_df.resample(cfg.interval).mean()
        resampled["value"] = resampled["value"].ffill(limit=5).interpolate(limit=5, limit_direction="both")
        resampled = resampled.dropna(subset=["value"])
        if resampled.empty:
            continue

        pct = resampled["value"].pct_change() * 100
        spike_mask = pct.abs() > cfg.spike_threshold_pct
        if spike_mask.any():
            resampled.loc[spike_mask, "value"] = np.nan
            resampled["value"] = resampled["value"].ffill(limit=5).interpolate(limit=5, limit_direction="both")
        resampled = resampled.dropna(subset=["value"])

        resampled["pct_change"] = resampled["value"].pct_change() * 100
        resampled["rolling_mean"] = (
            resampled["value"].rolling(cfg.rolling_window, min_periods=1).mean()
        )
        resampled["rolling_std"] = (
            resampled["value"].rolling(cfg.rolling_window, min_periods=1).std().fillna(0.0)
        )
        std = resampled["rolling_std"].replace(0.0, np.nan)
        resampled["z_score"] = ((resampled["value"] - resampled["rolling_mean"]) / std).fillna(0.0)
        resampled["symbol"] = symbol
        resampled["source"] = source_name

        for row in resampled.reset_index().itertuples(index=False):
            normalized.append(
                {
                    "timestamp": row.timestamp.isoformat(),
                    "symbol": row.symbol,
                    "source": row.source,
                    "value": float(row.value),
                    "pct_change": float(row.pct_change) if pd.notna(row.pct_change) else None,
                    "rolling_mean": float(row.rolling_mean) if pd.notna(row.rolling_mean) else None,
                    "rolling_std": float(row.rolling_std) if pd.notna(row.rolling_std) else None,
                    "z_score": float(row.z_score) if pd.notna(row.z_score) else None,
                }
            )
        del resampled

    if not normalized:
        return []
    normalized.sort(key=lambda row: (row["symbol"], row["timestamp"]))
    return normalized
