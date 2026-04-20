"""Application configuration loaded from environment variables."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE)


def _read_int(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer.") from exc


def _read_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_csv(name: str, default: str) -> tuple[str, ...]:
    raw_value = os.getenv(name, default)
    values = [item.strip() for item in raw_value.split(",") if item.strip()]
    if not values:
        values = [item.strip() for item in default.split(",") if item.strip()]
    return tuple(values)


@dataclass(frozen=True)
class Settings:
    db_path: str
    mongo_uri: str
    mongo_db_name: str
    mongo_crypto_collection: str
    mongo_stock_collection: str
    mongo_weather_collection: str
    mongo_processed_collection: str
    mongo_anomaly_collection: str
    mongo_forecast_collection: str
    mongo_correlation_collection: str
    mongo_alert_collection: str
    mongo_scheduler_jobs_collection: str
    mongo_freshness_collection: str
    ml_models_dir: str
    ml_metadata_file: str
    ml_anomaly_model_prefix: str
    ml_forecast_model_prefix: str
    anomaly_training_window_minutes: int
    forecast_training_window_minutes: int
    anomaly_min_training_points: int
    forecast_min_training_points: int
    stock_api_key: str
    crypto_api_key: str
    scheduler_interval_seconds: int
    scheduler_ingest_interval_seconds: int
    scheduler_processing_interval_seconds: int
    scheduler_correlation_interval_seconds: int
    scheduler_forecast_interval_seconds: int
    scheduler_anomaly_retrain_interval_seconds: int
    scheduler_forecast_retrain_interval_seconds: int
    scheduler_freshness_stale_seconds: int
    request_timeout_seconds: int
    websocket_emit_interval_seconds: int
    ingestion_crypto_symbols: tuple[str, ...]
    ingestion_stock_tickers: tuple[str, ...]
    crypto_api_base_url: str
    stock_api_base_url: str
    cors_origin: str
    secret_key: str
    host: str
    port: int
    debug: bool
    socketio_async_mode: str
    openweather_api_key: str
    ingestion_weather_cities: tuple[str, ...]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    default_db_path = PROJECT_ROOT / "data" / "market_intelligence.db"
    return Settings(
        db_path=os.getenv("DB_PATH", str(default_db_path)),
        mongo_uri=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        mongo_db_name=os.getenv("MONGO_DB_NAME", "Real_Time_Market_Intelligence_Console"),
        mongo_crypto_collection=os.getenv("MONGO_CRYPTO_COLLECTION", "crypto"),
        mongo_stock_collection=os.getenv("MONGO_STOCK_COLLECTION", "stock"),
        mongo_weather_collection=os.getenv("MONGO_WEATHER_COLLECTION", "weather"),
        mongo_processed_collection=os.getenv("MONGO_PROCESSED_COLLECTION", "processed_data"),
        mongo_anomaly_collection=os.getenv("MONGO_ANOMALY_COLLECTION", "anomaly_events"),
        mongo_forecast_collection=os.getenv("MONGO_FORECAST_COLLECTION", "forecast_outputs"),
        mongo_correlation_collection=os.getenv("MONGO_CORRELATION_COLLECTION", "correlation_metrics"),
        mongo_alert_collection=os.getenv("MONGO_ALERT_COLLECTION", "alerts"),
        mongo_scheduler_jobs_collection=os.getenv("MONGO_SCHEDULER_COLLECTION", "scheduler_jobs"),
        mongo_freshness_collection=os.getenv("MONGO_FRESHNESS_COLLECTION", "freshness_status"),
        ml_models_dir=os.getenv("ML_MODELS_DIR", str(PROJECT_ROOT / "ml_models")),
        ml_metadata_file=os.getenv("ML_METADATA_FILE", "model_metadata.json"),
        ml_anomaly_model_prefix=os.getenv("ML_ANOMALY_MODEL_PREFIX", "anomaly_iforest"),
        ml_forecast_model_prefix=os.getenv("ML_FORECAST_MODEL_PREFIX", "forecast_prophet"),
        anomaly_training_window_minutes=_read_int("ANOMALY_TRAINING_WINDOW_MINUTES", 1440),
        forecast_training_window_minutes=_read_int("FORECAST_TRAINING_WINDOW_MINUTES", 1051200),
        anomaly_min_training_points=_read_int("ANOMALY_MIN_TRAINING_POINTS", 30),
        forecast_min_training_points=_read_int("FORECAST_MIN_TRAINING_POINTS", 60),
        stock_api_key=os.getenv("STOCK_API_KEY", ""),
        crypto_api_key=os.getenv("CRYPTO_API_KEY", ""),
        scheduler_interval_seconds=_read_int("SCHEDULER_INTERVAL_SECONDS", 90),
        scheduler_ingest_interval_seconds=_read_int("SCHEDULER_INGEST_INTERVAL_SECONDS", 90),
        scheduler_processing_interval_seconds=_read_int("SCHEDULER_PROCESSING_INTERVAL_SECONDS", 180),
        scheduler_correlation_interval_seconds=_read_int("SCHEDULER_CORRELATION_INTERVAL_SECONDS", 900),
        scheduler_forecast_interval_seconds=_read_int("SCHEDULER_FORECAST_INTERVAL_SECONDS", 14400),
        scheduler_anomaly_retrain_interval_seconds=_read_int("SCHEDULER_ANOMALY_RETRAIN_INTERVAL_SECONDS", 7200),
        scheduler_forecast_retrain_interval_seconds=_read_int("SCHEDULER_FORECAST_RETRAIN_INTERVAL_SECONDS", 43200),
        scheduler_freshness_stale_seconds=_read_int("SCHEDULER_FRESHNESS_STALE_SECONDS", 300),
        request_timeout_seconds=_read_int("REQUEST_TIMEOUT_SECONDS", 10),
        websocket_emit_interval_seconds=_read_int("WEBSOCKET_EMIT_INTERVAL_SECONDS", 2),
        ingestion_crypto_symbols=_read_csv("INGESTION_CRYPTO_SYMBOLS", "BTC,ETH,SOL"),
        ingestion_stock_tickers=_read_csv("INGESTION_STOCK_TICKERS", "AAPL,MSFT,TSLA"),
        crypto_api_base_url=os.getenv("CRYPTO_API_BASE_URL", "https://api.freecryptoapi.com"),
        stock_api_base_url=os.getenv("STOCK_API_BASE_URL", "https://api.polygon.io"),
        cors_origin=os.getenv("CORS_ORIGIN", "http://localhost:5173"),
        secret_key=os.getenv("SECRET_KEY", "dev-secret-key"),
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=_read_int("FLASK_PORT", 5000),
        debug=_read_bool("FLASK_DEBUG", False),
        socketio_async_mode=os.getenv("SOCKETIO_ASYNC_MODE", "threading"),
        openweather_api_key=os.getenv("OPENWEATHER_API_KEY", ""),
        ingestion_weather_cities=_read_csv("INGESTION_WEATHER_CITIES", "London,New York,Tokyo"),
    )
