from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import pickle
from threading import RLock
from typing import Any

import joblib

from ...core.config import Settings, get_settings
from ...core.utils import get_logger

_LOGGER = get_logger("backend.processing.model_registry")
_LOCK = RLock()
_INITIALIZED = False
_REGISTRY_SETTINGS: Settings | None = None
_ANOMALY_MODELS: dict[str, Any] = {}
_FORECAST_MODELS: dict[str, Any] = {}
_METADATA: dict[str, Any] = {"version": 1, "updated_at": None, "anomaly": {}, "forecast": {}}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _model_dir(settings: Settings) -> Path:
    return Path(settings.ml_models_dir).resolve()


def _metadata_path(settings: Settings) -> Path:
    return _model_dir(settings) / settings.ml_metadata_file


def _symbol_key(symbol: str) -> str:
    return str(symbol).upper()


def _artifact_base(settings: Settings, model_type: str, symbol: str) -> Path:
    prefix = settings.ml_anomaly_model_prefix if model_type == "anomaly" else settings.ml_forecast_model_prefix
    filename = f"{prefix}_{_symbol_key(symbol)}"
    return _model_dir(settings) / filename


def _artifact_paths(settings: Settings, model_type: str, symbol: str) -> tuple[Path, Path]:
    base = _artifact_base(settings, model_type, symbol)
    return base.with_suffix(".joblib"), base.with_suffix(".pkl")


def _active_settings() -> Settings:
    return _REGISTRY_SETTINGS or get_settings()


def _normalize_metadata_entries(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for symbol, metadata in value.items():
        symbol_key = _symbol_key(symbol)
        normalized[symbol_key] = dict(metadata) if isinstance(metadata, dict) else {}
    return normalized


def _extract_symbol_from_artifact(stem: str, prefix: str) -> str | None:
    marker = f"{prefix}_"
    if not stem.startswith(marker):
        return None
    symbol = stem[len(marker) :]
    return _symbol_key(symbol) if symbol else None


def _discover_artifact_symbols(settings: Settings, model_type: str) -> set[str]:
    model_dir = _model_dir(settings)
    prefix = settings.ml_anomaly_model_prefix if model_type == "anomaly" else settings.ml_forecast_model_prefix
    discovered: set[str] = set()
    for extension in ("joblib", "pkl"):
        for artifact in model_dir.glob(f"{prefix}_*.{extension}"):
            symbol = _extract_symbol_from_artifact(artifact.stem, prefix)
            if symbol:
                discovered.add(symbol)
    return discovered


def _read_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "updated_at": _utc_now(), "anomaly": {}, "forecast": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("metadata payload must be object")
        payload.setdefault("version", 1)
        payload.setdefault("updated_at", _utc_now())
        payload.setdefault("anomaly", {})
        payload.setdefault("forecast", {})
        return payload
    except Exception:
        _LOGGER.exception("Failed reading model metadata file, recreating defaults.")
        return {"version": 1, "updated_at": _utc_now(), "anomaly": {}, "forecast": {}}


def _write_metadata(path: Path) -> None:
    _METADATA["updated_at"] = _utc_now()
    path.write_text(json.dumps(_METADATA, indent=2, sort_keys=True), encoding="utf-8")


def _load_artifact(joblib_path: Path, pickle_path: Path) -> tuple[Any | None, str | None]:
    if joblib_path.exists():
        return joblib.load(joblib_path), "joblib"
    if pickle_path.exists():
        with pickle_path.open("rb") as handle:
            return pickle.load(handle), "pickle"
    return None, None


def _snapshot_unlocked() -> dict[str, Any]:
    return {
        "initialized": _INITIALIZED,
        "anomaly_symbols": sorted(_ANOMALY_MODELS.keys()),
        "forecast_symbols": sorted(_FORECAST_MODELS.keys()),
        "metadata_updated_at": _METADATA.get("updated_at"),
    }


def initialize_model_registry(settings: Settings | None = None) -> dict[str, Any]:
    global _INITIALIZED, _METADATA, _REGISTRY_SETTINGS
    cfg = settings or get_settings()
    with _LOCK:
        if _INITIALIZED:
            return _snapshot_unlocked()

        _REGISTRY_SETTINGS = cfg
        model_dir = _model_dir(cfg)
        model_dir.mkdir(parents=True, exist_ok=True)
        metadata_path = _metadata_path(cfg)
        _METADATA = _read_metadata(metadata_path)
        _ANOMALY_MODELS.clear()
        _FORECAST_MODELS.clear()

        for model_type in ("anomaly", "forecast"):
            entries = _normalize_metadata_entries(_METADATA.get(model_type))
            _METADATA[model_type] = entries
            symbols = set(entries.keys()) | _discover_artifact_symbols(cfg, model_type)
            for symbol_key in sorted(symbols):
                entry = entries.get(symbol_key, {})
                joblib_path, pickle_path = _artifact_paths(cfg, model_type, symbol_key)
                model, loaded_format = _load_artifact(joblib_path, pickle_path)
                if model is None:
                    continue
                if model_type == "anomaly":
                    _ANOMALY_MODELS[symbol_key] = model
                    entry.setdefault("feature_columns", [])
                else:
                    _FORECAST_MODELS[symbol_key] = model
                    try:
                        entry["training_points"] = int(entry.get("training_points", 0))
                    except (TypeError, ValueError):
                        entry["training_points"] = 0
                entry["artifact"] = str(joblib_path if loaded_format == "joblib" else pickle_path)
                entry["format"] = loaded_format
                entry.setdefault("trained_at", None)
                entry.setdefault("model_type", type(model).__name__)
                entries[symbol_key] = entry

        _write_metadata(metadata_path)
        _INITIALIZED = True
        return _snapshot_unlocked()


def _ensure_initialized() -> None:
    if not _INITIALIZED:
        initialize_model_registry(_active_settings())


def get_anomaly_model(symbol: str) -> Any | None:
    _ensure_initialized()
    with _LOCK:
        return _ANOMALY_MODELS.get(_symbol_key(symbol))


def save_anomaly_model(symbol: str, model: Any, feature_columns: list[str] | None = None) -> dict[str, Any]:
    _ensure_initialized()
    cfg = _active_settings()
    symbol_key = _symbol_key(symbol)
    joblib_path, pickle_path = _artifact_paths(cfg, "anomaly", symbol_key)
    with _LOCK:
        _ANOMALY_MODELS[symbol_key] = model
        joblib_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, joblib_path)
        if pickle_path.exists():
            pickle_path.unlink()
        _METADATA.setdefault("anomaly", {})
        _METADATA["anomaly"][symbol_key] = {
            "artifact": str(joblib_path),
            "format": "joblib",
            "trained_at": _utc_now(),
            "feature_columns": feature_columns or [],
            "model_type": type(model).__name__,
        }
        _write_metadata(_metadata_path(cfg))
        return dict(_METADATA["anomaly"][symbol_key])


def get_forecast_model(symbol: str) -> Any | None:
    _ensure_initialized()
    with _LOCK:
        return _FORECAST_MODELS.get(_symbol_key(symbol))


def save_forecast_model(symbol: str, model: Any, training_points: int) -> dict[str, Any]:
    _ensure_initialized()
    cfg = _active_settings()
    symbol_key = _symbol_key(symbol)
    joblib_path, pickle_path = _artifact_paths(cfg, "forecast", symbol_key)
    with _LOCK:
        _FORECAST_MODELS[symbol_key] = model
        joblib_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, joblib_path)
        if pickle_path.exists():
            pickle_path.unlink()
        _METADATA.setdefault("forecast", {})
        _METADATA["forecast"][symbol_key] = {
            "artifact": str(joblib_path),
            "format": "joblib",
            "trained_at": _utc_now(),
            "training_points": int(training_points),
            "model_type": type(model).__name__,
        }
        _write_metadata(_metadata_path(cfg))
        return dict(_METADATA["forecast"][symbol_key])


def get_model_metadata(model_type: str, symbol: str) -> dict[str, Any] | None:
    _ensure_initialized()
    if model_type not in {"anomaly", "forecast"}:
        raise ValueError("model_type must be anomaly or forecast.")
    with _LOCK:
        value = _METADATA.get(model_type, {}).get(_symbol_key(symbol))
        return dict(value) if isinstance(value, dict) else None


def get_registry_snapshot() -> dict[str, Any]:
    _ensure_initialized()
    with _LOCK:
        return _snapshot_unlocked()
