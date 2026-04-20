from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import math

import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from ...core.config import get_settings
from ...core.utils import get_logger
from .model_registry import get_forecast_model, save_forecast_model

try:
    from prophet import Prophet
except Exception:  # pragma: no cover
    Prophet = None

_LOGGER = get_logger("backend.processing.forecast")
_PROPHET_READY: bool | None = None


@dataclass(frozen=True)
class ForecastConfig:
    interval_minutes: int = 1440
    horizon_steps: int = 365
    min_training_points: int = 90
    z_filter_threshold: float = 3.0


def _resolve_unit(source_name: str | None) -> str | None:
    normalized = str(source_name or "").lower()
    if any(token in normalized for token in ("stock", "polygon", "crypto", "freecrypto")):
        return "USD"
    return None


def _build_rolling_fallback(
    symbol: str,
    source: str,
    tail: pd.DataFrame,
    cfg: ForecastConfig,
) -> list[dict]:
    unit = _resolve_unit(source)
    last_ts = tail["timestamp"].max()
    base_value = float(tail["value"].iloc[-1])
    rolling_mean = float(tail["value"].tail(5).mean())
    rolling_std = float(tail["value"].tail(5).std() or 0.0)
    # Compute drift from recent momentum to avoid flat predictions
    recent_pct = tail["value"].pct_change().tail(5).mean()
    drift_rate = float(recent_pct) if pd.notna(recent_pct) else 0.0
    # Clamp drift to avoid extreme extrapolation
    drift_rate = max(-0.02, min(0.02, drift_rate))
    predictions: list[dict] = []
    for step in range(1, cfg.horizon_steps + 1):
        ts = last_ts + timedelta(minutes=step * cfg.interval_minutes)
        # Apply damped drift: exponential decay over horizon
        damping = 0.8 ** step
        value = (rolling_mean if rolling_mean > 0 else base_value) * (1 + drift_rate * step * damping)
        predictions.append(
            {
                "symbol": symbol,
                "source": source,
                "model": "rolling_fallback",
                "horizon_step": step,
                "interval": f"{cfg.interval_minutes}m",
                "predicted_value": float(value),
                "lower_bound": float(max(0.0, value - (1.96 * rolling_std))),
                "upper_bound": float(value + (1.96 * rolling_std)),
                "confidence": 0.75,
                "generated_at": ts.isoformat(),
                "unit": unit,
            }
        )
    return predictions


def _build_fallback_model(target: pd.DataFrame, cfg: ForecastConfig) -> dict:
    tail = target.sort_values("timestamp").copy()
    last_ts = tail["timestamp"].max()
    base_value = float(tail["value"].iloc[-1])
    rolling_mean = float(tail["value"].tail(5).mean())
    rolling_std = float(tail["value"].tail(5).std() or 0.0)
    recent_pct = tail["value"].pct_change().tail(5).mean()
    drift_rate = float(recent_pct) if pd.notna(recent_pct) else 0.0
    drift_rate = max(-0.02, min(0.02, drift_rate))
    return {
        "kind": "rolling_fallback_model",
        "interval_minutes": cfg.interval_minutes,
        "horizon_steps": cfg.horizon_steps,
        "base_value": base_value,
        "rolling_mean": rolling_mean,
        "rolling_std": rolling_std,
        "drift_rate": drift_rate,
        "last_timestamp": last_ts.isoformat(),
    }


def _predict_from_fallback_model(
    model_data: dict,
    symbol: str,
    source_name: str,
    cfg: ForecastConfig,
) -> list[dict]:
    unit = _resolve_unit(source_name)
    last_ts = pd.to_datetime(model_data.get("last_timestamp"), utc=True, errors="coerce")
    if pd.isna(last_ts):
        last_ts = pd.Timestamp.utcnow()
    rolling_mean = float(model_data.get("rolling_mean") or model_data.get("base_value") or 0.0)
    base_value = float(model_data.get("base_value") or rolling_mean or 0.0)
    rolling_std = float(model_data.get("rolling_std") or 0.0)
    drift_rate = float(model_data.get("drift_rate") or 0.0)
    if abs(drift_rate) < 1e-9 and rolling_mean > 0 and base_value > 0:
        drift_rate = (base_value - rolling_mean) / rolling_mean
    drift_rate = max(-0.02, min(0.02, drift_rate))
    predictions: list[dict] = []
    for step in range(1, cfg.horizon_steps + 1):
        ts = last_ts + timedelta(minutes=step * cfg.interval_minutes)
        damping = 0.8 ** step
        value = (rolling_mean if rolling_mean > 0 else base_value) * (1 + drift_rate * step * damping)
        predictions.append(
            {
                "symbol": symbol,
                "source": source_name,
                "model": "rolling_fallback_persisted",
                "horizon_step": step,
                "interval": f"{cfg.interval_minutes}m",
                "predicted_value": float(value),
                "lower_bound": float(max(0.0, value - (1.96 * rolling_std))),
                "upper_bound": float(value + (1.96 * rolling_std)),
                "confidence": 0.7,
                "generated_at": ts.isoformat(),
                "unit": unit,
            }
        )
    return predictions


def _prepare_prophet_training_frame(target: pd.DataFrame) -> pd.DataFrame:
    model_frame = target[["timestamp", "value"]].copy()
    model_frame["ds"] = pd.to_datetime(model_frame["timestamp"], utc=True, errors="coerce")
    # Prophet expects timezone-naive datetimes in ds.
    model_frame["ds"] = model_frame["ds"].dt.tz_localize(None)
    model_frame["y"] = pd.to_numeric(model_frame["value"], errors="coerce")
    model_frame = model_frame.dropna(subset=["ds", "y"]).sort_values("ds")
    model_frame = model_frame.drop_duplicates(subset=["ds"], keep="last")
    return model_frame[["ds", "y"]]


def _new_prophet_model() -> Prophet:
    return Prophet(
        interval_width=0.95,
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=True,
        changepoint_prior_scale=0.15,
    )


def _can_use_prophet() -> bool:
    global _PROPHET_READY
    if Prophet is None:
        return False
    if _PROPHET_READY is not None:
        return _PROPHET_READY
    try:
        _new_prophet_model()
        _PROPHET_READY = True
    except Exception as exc:
        _PROPHET_READY = False
        _LOGGER.warning("Prophet backend unavailable, using regression fallback: %s", exc)
    return _PROPHET_READY


def _train_prophet_model(target: pd.DataFrame) -> Prophet:
    if not _can_use_prophet():
        raise RuntimeError("prophet_backend_unavailable")
    model_frame = _prepare_prophet_training_frame(target)
    if model_frame.empty:
        raise ValueError("forecast_training_frame_empty")
    model = _new_prophet_model()
    model.fit(model_frame)
    return model


def _forecast_frequency(cfg: ForecastConfig) -> str:
    if cfg.interval_minutes % 1440 == 0:
        return "D"
    return f"{cfg.interval_minutes}min"


def _predict_prophet(
    model: Prophet,
    cfg: ForecastConfig,
    symbol: str,
    source_name: str,
) -> list[dict]:
    unit = _resolve_unit(source_name)
    future = model.make_future_dataframe(
        periods=cfg.horizon_steps,
        freq=_forecast_frequency(cfg),
    )
    predicted = model.predict(future).tail(cfg.horizon_steps)
    output: list[dict] = []
    for idx, row in enumerate(predicted.itertuples(index=False), start=1):
        width = float(row.yhat_upper - row.yhat_lower)
        confidence = max(0.0, min(0.99, 1.0 - (width / max(abs(float(row.yhat)), 1.0))))
        output.append(
            {
                "symbol": symbol,
                "source": source_name,
                "model": "prophet_persisted",
                "horizon_step": idx,
                "interval": f"{cfg.interval_minutes}m",
                "predicted_value": float(row.yhat),
                "lower_bound": float(max(0.0, row.yhat_lower)),
                "upper_bound": float(row.yhat_upper),
                "confidence": confidence,
                "generated_at": row.ds.isoformat(),
                "unit": unit,
            }
        )
    return output


def _price_regression_features(values: list[float], timestamp: pd.Timestamp) -> list[float]:
    history = values[-14:] if len(values) >= 14 else values
    lag1 = history[-1]
    lag2 = history[-2] if len(history) >= 2 else lag1
    lag3 = history[-3] if len(history) >= 3 else lag2
    lag7 = history[-7] if len(history) >= 7 else lag3
    rolling_mean7 = sum(history[-7:]) / max(1, min(7, len(history)))
    recent = history[-7:] if len(history) >= 7 else history
    mean_recent = sum(recent) / max(1, len(recent))
    rolling_std7 = math.sqrt(sum((value - mean_recent) ** 2 for value in recent) / max(1, len(recent)))
    day_of_week = float(timestamp.dayofweek)
    day_of_year = float(timestamp.dayofyear)
    seasonal_sin = math.sin((2 * math.pi * day_of_year) / 365.25)
    seasonal_cos = math.cos((2 * math.pi * day_of_year) / 365.25)
    return [lag1, lag2, lag3, lag7, rolling_mean7, rolling_std7, day_of_week, seasonal_sin, seasonal_cos]


def _return_regression_features(returns: list[float], timestamp: pd.Timestamp) -> list[float]:
    history = returns[-60:] if len(returns) >= 60 else returns
    lag1 = history[-1]
    lag2 = history[-2] if len(history) >= 2 else lag1
    lag3 = history[-3] if len(history) >= 3 else lag2
    lag5 = history[-5] if len(history) >= 5 else lag3
    lag10 = history[-10] if len(history) >= 10 else lag5
    recent5 = history[-5:] if len(history) >= 5 else history
    recent10 = history[-10:] if len(history) >= 10 else history
    mean5 = sum(recent5) / max(1, len(recent5))
    mean10 = sum(recent10) / max(1, len(recent10))
    std10 = math.sqrt(sum((value - mean10) ** 2 for value in recent10) / max(1, len(recent10)))
    day_of_week = float(timestamp.dayofweek)
    day_of_year = float(timestamp.dayofyear)
    seasonal_sin = math.sin((2 * math.pi * day_of_year) / 365.25)
    seasonal_cos = math.cos((2 * math.pi * day_of_year) / 365.25)
    return [lag1, lag2, lag3, lag5, lag10, mean5, mean10, std10, day_of_week, seasonal_sin, seasonal_cos]


def _train_legacy_price_regression_model(target: pd.DataFrame, cfg: ForecastConfig) -> dict:
    ordered = target.sort_values("timestamp").copy()
    ordered["timestamp"] = pd.to_datetime(ordered["timestamp"], utc=True, errors="coerce")
    ordered["value"] = pd.to_numeric(ordered["value"], errors="coerce")
    ordered = ordered.dropna(subset=["timestamp", "value"])
    ordered = ordered.drop_duplicates(subset=["timestamp"], keep="last")
    if len(ordered) < max(30, cfg.min_training_points):
        raise ValueError("insufficient_points_for_regression_model")

    values = [float(item) for item in ordered["value"].tolist()]
    timestamps = [pd.Timestamp(item) for item in ordered["timestamp"].tolist()]
    x_rows: list[list[float]] = []
    y_rows: list[float] = []
    for index in range(14, len(values)):
        x_rows.append(_price_regression_features(values[:index], timestamps[index]))
        y_rows.append(values[index])
    if len(x_rows) < 20:
        raise ValueError("insufficient_feature_rows_for_regression_model")

    model = RandomForestRegressor(
        n_estimators=250,
        min_samples_leaf=2,
        random_state=42,
    )
    model.fit(x_rows, y_rows)
    return {
        "kind": "seasonal_regression_model",
        "model": model,
        "last_timestamp": timestamps[-1].isoformat(),
        "history": values[-30:],
        "interval_minutes": cfg.interval_minutes,
        "horizon_steps": cfg.horizon_steps,
    }


def _train_return_regression_model(target: pd.DataFrame, cfg: ForecastConfig) -> dict:
    ordered = target.sort_values("timestamp").copy()
    ordered["timestamp"] = pd.to_datetime(ordered["timestamp"], utc=True, errors="coerce")
    ordered["value"] = pd.to_numeric(ordered["value"], errors="coerce")
    ordered = ordered.dropna(subset=["timestamp", "value"])
    ordered = ordered.drop_duplicates(subset=["timestamp"], keep="last")
    if len(ordered) < max(60, cfg.min_training_points):
        raise ValueError("insufficient_points_for_return_regression_model")

    prices = [max(1e-9, float(item)) for item in ordered["value"].tolist()]
    timestamps = [pd.Timestamp(item) for item in ordered["timestamp"].tolist()]
    returns = [math.log(prices[idx] / prices[idx - 1]) for idx in range(1, len(prices))]
    return_timestamps = timestamps[1:]
    x_rows: list[list[float]] = []
    y_rows: list[float] = []
    for index in range(30, len(returns)):
        x_rows.append(_return_regression_features(returns[:index], return_timestamps[index]))
        y_rows.append(returns[index])
    if len(x_rows) < 30:
        raise ValueError("insufficient_feature_rows_for_return_regression_model")

    model = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=2,
        random_state=42,
    )
    model.fit(x_rows, y_rows)
    train_predictions = model.predict(x_rows)
    residuals = [actual - predicted for actual, predicted in zip(y_rows, train_predictions)]
    residual_std = float(pd.Series(residuals).std() or 0.0)
    if not math.isfinite(residual_std) or residual_std <= 1e-9:
        residual_std = float(pd.Series(y_rows).std() or 0.005)
    residual_q05 = float(pd.Series(residuals).quantile(0.05))
    residual_q95 = float(pd.Series(residuals).quantile(0.95))
    return {
        "kind": "return_regression_model",
        "model": model,
        "last_timestamp": timestamps[-1].isoformat(),
        "last_price": prices[-1],
        "returns_history": returns[-90:],
        "residual_std": residual_std,
        "residual_q05": residual_q05,
        "residual_q95": residual_q95,
        "interval_minutes": cfg.interval_minutes,
        "horizon_steps": cfg.horizon_steps,
    }


def _predict_from_legacy_price_regression_model(
    model_data: dict,
    symbol: str,
    source_name: str,
    cfg: ForecastConfig,
) -> list[dict]:
    estimator = model_data.get("model")
    if estimator is None:
        raise ValueError("regression_model_missing_estimator")
    last_ts = pd.to_datetime(model_data.get("last_timestamp"), utc=True, errors="coerce")
    if pd.isna(last_ts):
        last_ts = pd.Timestamp.utcnow()
    history = [float(value) for value in model_data.get("history", []) if value is not None]
    if not history:
        history = [0.0]
    predictions: list[dict] = []
    unit = _resolve_unit(source_name)
    for step in range(1, cfg.horizon_steps + 1):
        ts = last_ts + timedelta(minutes=step * cfg.interval_minutes)
        features = _price_regression_features(history, ts)
        value = float(estimator.predict([features])[0])
        value = max(0.0, value)
        history.append(value)
        recent = history[-14:] if len(history) >= 14 else history
        mean_recent = sum(recent) / max(1, len(recent))
        std_recent = math.sqrt(sum((item - mean_recent) ** 2 for item in recent) / max(1, len(recent)))
        predictions.append(
            {
                "symbol": symbol,
                "source": source_name,
                "model": "seasonal_regression_persisted",
                "horizon_step": step,
                "interval": f"{cfg.interval_minutes}m",
                "predicted_value": value,
                "lower_bound": float(max(0.0, value - (1.64 * std_recent))),
                "upper_bound": float(value + (1.64 * std_recent)),
                "confidence": 0.82,
                "generated_at": ts.isoformat(),
                "unit": unit,
            }
        )
    return predictions


def _predict_from_return_regression_model(
    model_data: dict,
    symbol: str,
    source_name: str,
    cfg: ForecastConfig,
) -> list[dict]:
    estimator = model_data.get("model")
    if estimator is None:
        raise ValueError("return_regression_model_missing_estimator")
    last_ts = pd.to_datetime(model_data.get("last_timestamp"), utc=True, errors="coerce")
    if pd.isna(last_ts):
        last_ts = pd.Timestamp.utcnow()
    last_price = float(model_data.get("last_price") or 0.0)
    if not math.isfinite(last_price) or last_price <= 0:
        raise ValueError("return_regression_model_missing_last_price")
    returns_history = [
        float(value) for value in model_data.get("returns_history", []) if value is not None and math.isfinite(float(value))
    ]
    if not returns_history:
        returns_history = [0.0]
    residual_std = float(model_data.get("residual_std") or 0.005)
    residual_std = max(1e-6, residual_std)
    unit = _resolve_unit(source_name)
    predictions: list[dict] = []
    current_price = last_price
    recent_window = returns_history[-30:] if len(returns_history) >= 30 else returns_history
    recent_mean = float(pd.Series(recent_window).mean() or 0.0)
    recent_vol = float(pd.Series(recent_window).std() or 0.01)
    recent_vol = min(0.05, max(0.002, recent_vol))
    for step in range(1, cfg.horizon_steps + 1):
        ts = last_ts + timedelta(minutes=step * cfg.interval_minutes)
        base_price = current_price
        features = _return_regression_features(returns_history, ts)
        raw_return = float(estimator.predict([features])[0])
        predicted_return = (0.65 * raw_return) + (0.35 * recent_mean)
        return_limit = min(0.04, max(0.01, recent_vol * 3.0))
        predicted_return = max(-return_limit, min(return_limit, predicted_return))
        predicted_price = max(0.0, base_price * math.exp(predicted_return))
        current_price = predicted_price
        returns_history.append(predicted_return)
        if len(returns_history) > 120:
            returns_history = returns_history[-120:]
        adaptive_window = returns_history[-30:] if len(returns_history) >= 30 else returns_history
        recent_mean = float(pd.Series(adaptive_window).mean() or recent_mean)
        recent_vol = float(pd.Series(adaptive_window).std() or recent_vol)
        recent_vol = min(0.05, max(0.002, recent_vol))
        scale = math.sqrt(step)
        uncertainty = max(residual_std, recent_vol * 0.75) * scale
        lower_return = max(-0.20, predicted_return - (1.64 * uncertainty))
        upper_return = min(0.20, predicted_return + (1.64 * uncertainty))
        lower_price = max(0.0, base_price * math.exp(lower_return))
        upper_price = max(predicted_price, base_price * math.exp(upper_return))
        if lower_price > upper_price:
            lower_price, upper_price = upper_price, lower_price
        confidence = max(0.55, min(0.92, 0.92 - (scale * uncertainty * 4.0)))
        predictions.append(
            {
                "symbol": symbol,
                "source": source_name,
                "model": "return_regression_persisted",
                "horizon_step": step,
                "interval": f"{cfg.interval_minutes}m",
                "predicted_value": predicted_price,
                "lower_bound": lower_price,
                "upper_bound": upper_price,
                "confidence": confidence,
                "generated_at": ts.isoformat(),
                "unit": unit,
            }
        )
    return predictions


def _predict_from_non_prophet_model(
    model_data: dict,
    symbol: str,
    source_name: str,
    cfg: ForecastConfig,
) -> list[dict]:
    kind = str(model_data.get("kind") or "").lower()
    if kind == "return_regression_model":
        return _predict_from_return_regression_model(model_data, symbol, source_name, cfg)
    if kind == "seasonal_regression_model":
        return _predict_from_legacy_price_regression_model(model_data, symbol, source_name, cfg)
    if kind == "rolling_fallback_model":
        return _predict_from_fallback_model(model_data, symbol, source_name, cfg)
    raise ValueError(f"unsupported_non_prophet_model_kind:{kind}")


def _train_preferred_non_prophet_model(
    target: pd.DataFrame,
    cfg: ForecastConfig,
    symbol: str,
    source_name: str,
) -> tuple[dict, list[dict]]:
    try:
        model_data = _train_return_regression_model(target, cfg)
        save_forecast_model(symbol, model_data, training_points=len(target))
        output = _predict_from_return_regression_model(model_data, symbol, source_name, cfg)
        return model_data, output
    except Exception as exc:
        _LOGGER.warning("Return-regression train failed for %s: %s", symbol, exc)
        try:
            model_data = _train_legacy_price_regression_model(target, cfg)
            save_forecast_model(symbol, model_data, training_points=len(target))
            output = _predict_from_legacy_price_regression_model(model_data, symbol, source_name, cfg)
            return model_data, output
        except Exception as legacy_exc:
            _LOGGER.warning("Legacy price-regression train failed for %s: %s", symbol, legacy_exc)
            fallback_model = _build_fallback_model(target, cfg)
            save_forecast_model(symbol, fallback_model, training_points=len(target))
            output = _predict_from_fallback_model(fallback_model, symbol, source_name, cfg)
            return fallback_model, output


def summarize_forecast_diagnostics(
    cleaned_records: list[dict],
    cfg: ForecastConfig | None = None,
    holdout_steps: int = 30,
) -> dict:
    if not cleaned_records:
        return {
            "available": False,
            "reason": "empty_dataset",
            "symbols": {},
        }

    config = cfg or ForecastConfig()
    frame = pd.DataFrame(cleaned_records)
    if frame.empty:
        return {
            "available": False,
            "reason": "empty_dataframe",
            "symbols": {},
        }

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["z_score"] = pd.to_numeric(frame.get("z_score"), errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["timestamp", "symbol", "value"])
    if frame.empty:
        return {
            "available": False,
            "reason": "no_valid_points",
            "symbols": {},
        }

    settings = get_settings()
    min_points = max(settings.forecast_min_training_points, config.min_training_points)
    safe_holdout = max(7, int(holdout_steps))
    prophet_ready = _can_use_prophet()
    by_symbol: dict[str, dict] = {}

    for symbol, group in frame.groupby("symbol"):
        ordered = group.sort_values("timestamp").copy()
        filtered = ordered[ordered["z_score"].abs() < config.z_filter_threshold]
        target = filtered if len(filtered) >= min_points else ordered
        model_frame = _prepare_prophet_training_frame(target)
        if len(model_frame) < (min_points + safe_holdout):
            by_symbol[symbol] = {
                "status": "skipped",
                "reason": "insufficient_points",
                "training_points": int(len(model_frame)),
            }
            continue

        train_frame = model_frame.iloc[:-safe_holdout]
        actual_frame = model_frame.iloc[-safe_holdout:]
        if len(train_frame) < min_points:
            by_symbol[symbol] = {
                "status": "skipped",
                "reason": "insufficient_train_split",
                "training_points": int(len(train_frame)),
            }
            continue

        try:
            if prophet_ready:
                model = _new_prophet_model()
                model.fit(train_frame)
                predicted = model.predict(actual_frame[["ds"]])[["ds", "yhat"]]
                merged = actual_frame.merge(predicted, on="ds", how="inner")
                if merged.empty:
                    by_symbol[symbol] = {
                        "status": "skipped",
                        "reason": "no_prediction_overlap",
                    }
                    continue
                actual_values = merged["y"].astype(float).tolist()
                predicted_values = merged["yhat"].astype(float).tolist()
                backend = "prophet"
            else:
                eval_target = target.iloc[:-safe_holdout].copy()
                model_data = _train_return_regression_model(eval_target, config)
                eval_cfg = ForecastConfig(
                    interval_minutes=config.interval_minutes,
                    horizon_steps=safe_holdout,
                    min_training_points=config.min_training_points,
                    z_filter_threshold=config.z_filter_threshold,
                )
                source_name = (
                    str(target["source"].iloc[-1]) if "source" in target.columns and not target.empty else "processing"
                )
                predicted_rows = _predict_from_return_regression_model(model_data, symbol, source_name, eval_cfg)
                predicted_values = [float(item["predicted_value"]) for item in predicted_rows]
                actual_values = [float(item) for item in actual_frame["y"].astype(float).tolist()]
                min_len = min(len(actual_values), len(predicted_values))
                if min_len == 0:
                    by_symbol[symbol] = {
                        "status": "skipped",
                        "reason": "no_prediction_overlap",
                    }
                    continue
                actual_values = actual_values[:min_len]
                predicted_values = predicted_values[:min_len]
                backend = "return_regression"

            errors = pd.Series(actual_values) - pd.Series(predicted_values)
            rmse = float(math.sqrt((errors.pow(2).mean())))
            denom = pd.Series(actual_values).abs().clip(lower=1e-9)
            mape = float((errors.abs() / denom).mean() * 100.0)
            actual_std = float(pd.Series(actual_values).std() or 0.0)
            predicted_std = float(pd.Series(predicted_values).std() or 0.0)
            variance_ratio = predicted_std / actual_std if actual_std > 0 else 0.0
            variation_delta = float(max(predicted_values) - min(predicted_values)) if predicted_values else 0.0
            variation_floor = max(1e-6, float(abs(pd.Series(actual_values).mean()) * 0.001))
            degenerate = variation_delta < variation_floor
            by_symbol[symbol] = {
                "status": "ok",
                "backend": backend,
                "points": int(len(actual_values)),
                "rmse": rmse,
                "mape": mape,
                "variance_ratio": variance_ratio,
                "variation_delta": variation_delta,
                "degenerate_path": degenerate,
            }
        except Exception as exc:
            _LOGGER.warning("Forecast diagnostics failed for %s: %s", symbol, exc)
            by_symbol[symbol] = {
                "status": "error",
                "reason": str(exc),
            }

    ok_symbols = sum(1 for row in by_symbol.values() if row.get("status") == "ok")
    return {
        "available": True,
        "backend": "prophet" if prophet_ready else "return_regression",
        "evaluated_symbols": ok_symbols,
        "symbols": by_symbol,
    }


def generate_forecasts(
    cleaned_records: list[dict],
    cfg: ForecastConfig | None = None,
) -> list[dict]:
    if not cleaned_records:
        return []

    config = cfg or ForecastConfig()
    frame = pd.DataFrame(cleaned_records)
    if frame.empty:
        return []

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["z_score"] = pd.to_numeric(frame.get("z_score"), errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["timestamp", "symbol", "value"])
    if frame.empty:
        return []

    forecasts: list[dict] = []
    settings = get_settings()
    min_points = max(settings.forecast_min_training_points, config.min_training_points)
    prophet_ready = _can_use_prophet()
    non_prophet_kinds = {"return_regression_model", "seasonal_regression_model", "rolling_fallback_model"}

    for symbol, group in frame.groupby("symbol"):
        symbol_df = group.sort_values("timestamp").copy()
        source_name = str(symbol_df["source"].iloc[-1]) if "source" in symbol_df.columns else "processing"
        filtered = symbol_df[symbol_df["z_score"].abs() < config.z_filter_threshold]
        target = filtered if len(filtered) >= min_points else symbol_df
        persisted = get_forecast_model(symbol)

        if len(target) < min_points:
            if isinstance(persisted, dict) and str(persisted.get("kind") or "").lower() in non_prophet_kinds:
                try:
                    forecasts.extend(_predict_from_non_prophet_model(persisted, symbol, source_name, config))
                    continue
                except Exception as exc:
                    _LOGGER.warning("Persisted non-prophet predict failed for %s: %s", symbol, exc)
            fallback_model = _build_fallback_model(target, config)
            save_forecast_model(symbol, fallback_model, training_points=len(target))
            forecasts.extend(_predict_from_fallback_model(fallback_model, symbol, source_name, config))
            continue

        if not prophet_ready:
            if isinstance(persisted, dict) and str(persisted.get("kind") or "").lower() in non_prophet_kinds:
                try:
                    forecasts.extend(_predict_from_non_prophet_model(persisted, symbol, source_name, config))
                    continue
                except Exception as exc:
                    _LOGGER.warning("Persisted non-prophet predict failed for %s: %s", symbol, exc)
            _, output = _train_preferred_non_prophet_model(target, config, symbol, source_name)
            forecasts.extend(output)
            continue

        model = persisted
        if isinstance(model, dict):
            try:
                upgraded = _train_prophet_model(target)
                save_forecast_model(symbol, upgraded, training_points=len(target))
                model = upgraded
                _LOGGER.info("Upgraded %s forecast artifact to Prophet model.", symbol)
            except Exception as exc:
                _LOGGER.warning(
                    "Prophet upgrade failed for %s, keeping non-prophet model: %s",
                    symbol,
                    exc,
                )
                if str(model.get("kind") or "").lower() in non_prophet_kinds:
                    try:
                        forecasts.extend(_predict_from_non_prophet_model(model, symbol, source_name, config))
                        continue
                    except Exception as non_prophet_exc:
                        _LOGGER.warning(
                            "Persisted non-prophet predict failed for %s after Prophet upgrade miss: %s",
                            symbol,
                            non_prophet_exc,
                        )
                _, output = _train_preferred_non_prophet_model(target, config, symbol, source_name)
                forecasts.extend(output)
                continue

        if model is None:
            try:
                model = _train_prophet_model(target)
                save_forecast_model(symbol, model, training_points=len(target))
            except Exception as exc:
                _LOGGER.warning("Prophet train failed for %s, using non-prophet model: %s", symbol, exc)
                _, output = _train_preferred_non_prophet_model(target, config, symbol, source_name)
                forecasts.extend(output)
                continue

        try:
            if model is None:
                raise ValueError("forecast model unavailable")
            forecasts.extend(_predict_prophet(model, config, symbol, source_name))
        except Exception as exc:
            _LOGGER.warning("Forecast predict failed for %s, retrying/recovering: %s", symbol, exc)
            if prophet_ready:
                try:
                    retrained = _train_prophet_model(target)
                    save_forecast_model(symbol, retrained, training_points=len(target))
                    forecasts.extend(_predict_prophet(retrained, config, symbol, source_name))
                    continue
                except Exception as retrain_exc:
                    _LOGGER.warning("Prophet retrain failed for %s, using non-prophet model: %s", symbol, retrain_exc)
            persisted = get_forecast_model(symbol)
            if isinstance(persisted, dict) and str(persisted.get("kind") or "").lower() in non_prophet_kinds:
                try:
                    forecasts.extend(_predict_from_non_prophet_model(persisted, symbol, source_name, config))
                    continue
                except Exception as non_prophet_exc:
                    _LOGGER.warning("Persisted non-prophet predict failed for %s: %s", symbol, non_prophet_exc)
            _, output = _train_preferred_non_prophet_model(target, config, symbol, source_name)
            forecasts.extend(output)

    return forecasts


def retrain_forecast_models(
    cleaned_records: list[dict],
    cfg: ForecastConfig | None = None,
) -> dict:
    if not cleaned_records:
        return {"trained_models": 0, "symbols": [], "skipped_symbols": []}

    config = cfg or ForecastConfig()
    settings = get_settings()
    min_points = max(settings.forecast_min_training_points, config.min_training_points)

    frame = pd.DataFrame(cleaned_records)
    if frame.empty:
        return {"trained_models": 0, "symbols": [], "skipped_symbols": []}

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["z_score"] = pd.to_numeric(frame.get("z_score"), errors="coerce").fillna(0.0)
    frame = frame.dropna(subset=["timestamp", "symbol", "value"])
    if frame.empty:
        return {"trained_models": 0, "symbols": [], "skipped_symbols": []}

    trained_symbols: list[str] = []
    skipped_symbols: list[str] = []
    prophet_ready = _can_use_prophet()
    for symbol, group in frame.groupby("symbol"):
        ordered = group.sort_values("timestamp").copy()
        filtered = ordered[ordered["z_score"].abs() < config.z_filter_threshold]
        target = filtered if len(filtered) >= min_points else ordered
        if len(target) < min_points:
            skipped_symbols.append(symbol)
            continue
        try:
            if prophet_ready:
                model = _train_prophet_model(target)
                save_forecast_model(symbol, model, training_points=len(target))
            else:
                model = _train_return_regression_model(target, config)
                save_forecast_model(symbol, model, training_points=len(target))
            trained_symbols.append(symbol)
        except Exception as exc:
            _LOGGER.warning("Forecast retrain primary model failed for %s: %s", symbol, exc)
            try:
                model = _train_return_regression_model(target, config)
                save_forecast_model(symbol, model, training_points=len(target))
                trained_symbols.append(symbol)
            except Exception as regression_exc:
                _LOGGER.warning("Forecast retrain return-regression fallback failed for %s: %s", symbol, regression_exc)
                try:
                    legacy_model = _train_legacy_price_regression_model(target, config)
                    save_forecast_model(symbol, legacy_model, training_points=len(target))
                    trained_symbols.append(symbol)
                except Exception as legacy_exc:
                    _LOGGER.warning("Forecast retrain legacy-regression fallback failed for %s: %s", symbol, legacy_exc)
                    try:
                        fallback_model = _build_fallback_model(target, config)
                        save_forecast_model(symbol, fallback_model, training_points=len(target))
                        trained_symbols.append(symbol)
                    except Exception:
                        skipped_symbols.append(symbol)

    return {
        "trained_models": len(trained_symbols),
        "symbols": trained_symbols,
        "skipped_symbols": skipped_symbols,
    }
