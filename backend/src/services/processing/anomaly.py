from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from ...core.config import get_settings
from .model_registry import get_anomaly_model, save_anomaly_model


@dataclass(frozen=True)
class AnomalyConfig:
    z_threshold: float = 3.0
    rolling_window: int = 20
    contamination: float = 0.05
    random_state: int = 42


def _classify_type(pct_change: float | None) -> str:
    if pct_change is None:
        return "volatility"
    if pct_change > 0:
        return "spike"
    if pct_change < 0:
        return "drop"
    return "volatility"


def _calibrated_iso_thresholds(iso_scores: pd.Series) -> tuple[float, float]:
    valid = pd.to_numeric(iso_scores, errors="coerce")
    valid = valid[valid.notna()]
    valid = valid[valid > 0]
    if valid.empty:
        return 0.75, 0.25
    high_cutoff = float(valid.quantile(0.9))
    medium_cutoff = float(valid.quantile(0.7))
    if not np.isfinite(high_cutoff):
        high_cutoff = 0.75
    if not np.isfinite(medium_cutoff):
        medium_cutoff = 0.25
    if high_cutoff < medium_cutoff:
        high_cutoff = medium_cutoff
    return high_cutoff, medium_cutoff


def _severity_for_row(
    *,
    z_score: float,
    z_flag: bool,
    iso_flag: bool,
    iso_score: float,
    iso_high_cutoff: float,
    iso_medium_cutoff: float,
    z_threshold: float,
) -> str:
    abs_z = abs(float(z_score))
    if z_flag:
        if abs_z >= z_threshold + 1.0:
            return "high"
        if abs_z >= z_threshold:
            return "medium"
        return "low"
    if iso_flag:
        if iso_score >= iso_high_cutoff:
            return "high"
        if iso_score >= iso_medium_cutoff:
            return "medium"
    return "low"


def _fit_model(feature_frame: pd.DataFrame, cfg: AnomalyConfig) -> IsolationForest:
    contamination = min(max(cfg.contamination, 0.01), 0.5)
    model = IsolationForest(
        contamination=contamination,
        random_state=cfg.random_state,
    )
    model.fit(feature_frame)
    return model


def detect_anomalies(
    cleaned_records: list[dict],
    config: AnomalyConfig | None = None,
) -> list[dict]:
    if not cleaned_records:
        return []

    cfg = config or AnomalyConfig()
    frame = pd.DataFrame(cleaned_records)
    if frame.empty:
        return []

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["pct_change"] = pd.to_numeric(frame.get("pct_change"), errors="coerce")
    frame["z_score"] = pd.to_numeric(frame.get("z_score"), errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["timestamp", "symbol", "value"])
    if frame.empty:
        return []

    output_rows: list[dict] = []
    settings = get_settings()
    min_points = max(settings.anomaly_min_training_points, cfg.rolling_window)
    feature_columns = ["value", "pct_change", "z_score"]

    for symbol, group in frame.groupby("symbol"):
        symbol_df = group.sort_values("timestamp").copy()
        symbol_df["z_flag"] = symbol_df["z_score"].abs() >= cfg.z_threshold

        if len(symbol_df) >= min_points:
            feature_frame = symbol_df[feature_columns].fillna(0.0)
            model = get_anomaly_model(symbol)
            if model is None:
                model = _fit_model(feature_frame, cfg)
                save_anomaly_model(symbol, model, feature_columns=feature_columns)
            try:
                iso_pred = model.predict(feature_frame)
                decision = model.decision_function(feature_frame)
            except Exception:
                model = _fit_model(feature_frame, cfg)
                save_anomaly_model(symbol, model, feature_columns=feature_columns)
                iso_pred = model.predict(feature_frame)
                decision = model.decision_function(feature_frame)

            symbol_df["iso_flag"] = iso_pred == -1
            symbol_df["iso_score"] = np.maximum(0.0, -decision)
            del feature_frame
        else:
            symbol_df["iso_flag"] = False
            symbol_df["iso_score"] = 0.0

        symbol_df["is_anomaly"] = symbol_df["z_flag"] | symbol_df["iso_flag"]
        symbol_df["anomaly_score"] = np.maximum(symbol_df["z_score"].abs(), symbol_df["iso_score"])
        symbol_df["anomaly_type"] = symbol_df["pct_change"].apply(
            lambda x: _classify_type(float(x) if pd.notna(x) else None)
        )
        iso_high_cutoff, iso_medium_cutoff = _calibrated_iso_thresholds(
            symbol_df.loc[symbol_df["iso_flag"], "iso_score"]
        )
        symbol_df["severity"] = symbol_df.apply(
            lambda row: _severity_for_row(
                z_score=float(row["z_score"]),
                z_flag=bool(row["z_flag"]),
                iso_flag=bool(row["iso_flag"]),
                iso_score=float(row["iso_score"]),
                iso_high_cutoff=iso_high_cutoff,
                iso_medium_cutoff=iso_medium_cutoff,
                z_threshold=cfg.z_threshold,
            ),
            axis=1,
        )

        for _, row in symbol_df.iterrows():
            output_rows.append(
                {
                    "timestamp": row["timestamp"].isoformat(),
                    "symbol": row["symbol"],
                    "source": row.get("source", "processing"),
                    "value": float(row["value"]),
                    "anomaly_type": row["anomaly_type"],
                    "anomaly_score": float(row["anomaly_score"]),
                    "severity": row["severity"],
                    "method": "zscore+isolation_forest_persisted",
                    "is_anomaly": bool(row["is_anomaly"]),
                }
            )
        del symbol_df

    del frame
    return output_rows


def retrain_anomaly_models(
    cleaned_records: list[dict],
    config: AnomalyConfig | None = None,
) -> dict:
    if not cleaned_records:
        return {"trained_models": 0, "symbols": [], "skipped_symbols": []}

    cfg = config or AnomalyConfig()
    settings = get_settings()
    min_points = max(settings.anomaly_min_training_points, cfg.rolling_window)
    frame = pd.DataFrame(cleaned_records)
    if frame.empty:
        return {"trained_models": 0, "symbols": [], "skipped_symbols": []}

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["pct_change"] = pd.to_numeric(frame.get("pct_change"), errors="coerce")
    frame["z_score"] = pd.to_numeric(frame.get("z_score"), errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["timestamp", "symbol", "value"])
    if frame.empty:
        return {"trained_models": 0, "symbols": [], "skipped_symbols": []}

    trained_symbols: list[str] = []
    skipped_symbols: list[str] = []
    feature_columns = ["value", "pct_change", "z_score"]

    for symbol, group in frame.groupby("symbol"):
        ordered = group.sort_values("timestamp").copy()
        if len(ordered) < min_points:
            skipped_symbols.append(symbol)
            continue
        feature_frame = ordered[feature_columns].fillna(0.0)
        model = _fit_model(feature_frame, cfg)
        save_anomaly_model(symbol, model, feature_columns=feature_columns)
        trained_symbols.append(symbol)

    return {
        "trained_models": len(trained_symbols),
        "symbols": trained_symbols,
        "skipped_symbols": skipped_symbols,
    }
