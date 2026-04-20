from __future__ import annotations

from datetime import datetime, timezone

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from ..core.config import get_settings

_CLIENT: MongoClient | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_mongo_client() -> MongoClient:
    global _CLIENT
    if _CLIENT is None:
        settings = get_settings()
        _CLIENT = MongoClient(settings.mongo_uri, tz_aware=True)
    return _CLIENT


def get_mongo_database() -> Database:
    settings = get_settings()
    return get_mongo_client()[settings.mongo_db_name]


def get_collection(name: str) -> Collection:
    return get_mongo_database()[name]


def collection_map() -> dict[str, str]:
    settings = get_settings()
    return {
        "market_data_crypto": settings.mongo_crypto_collection,
        "market_data_stock": settings.mongo_stock_collection,
        "market_data_weather": settings.mongo_weather_collection,
        "processed_data": settings.mongo_processed_collection,
        "anomaly_events": settings.mongo_anomaly_collection,
        "forecast_outputs": settings.mongo_forecast_collection,
        "correlation_metrics": settings.mongo_correlation_collection,
        "alerts": settings.mongo_alert_collection,
        "scheduler_jobs": settings.mongo_scheduler_jobs_collection,
        "freshness_status": settings.mongo_freshness_collection,
    }


def init_db() -> None:
    db = get_mongo_database()
    mapping = collection_map()
    existing_collections = set(db.list_collection_names())

    for collection_name in mapping.values():
        if collection_name not in existing_collections:
            db.create_collection(collection_name)

    db[mapping["market_data_crypto"]].create_index([("symbol", ASCENDING), ("captured_at", DESCENDING)])
    db[mapping["market_data_stock"]].create_index([("symbol", ASCENDING), ("captured_at", DESCENDING)])
    db[mapping["market_data_weather"]].create_index([("symbol", ASCENDING), ("captured_at", DESCENDING)])
    db[mapping["processed_data"]].create_index([("symbol", ASCENDING), ("timestamp", DESCENDING)])
    db[mapping["anomaly_events"]].create_index([("symbol", ASCENDING), ("timestamp", DESCENDING)])
    db[mapping["anomaly_events"]].create_index(
        [
            ("symbol", ASCENDING),
            ("source", ASCENDING),
            ("timestamp", DESCENDING),
            ("anomaly_type", ASCENDING),
            ("method", ASCENDING),
            ("created_at", DESCENDING),
        ]
    )
    db[mapping["forecast_outputs"]].create_index([("symbol", ASCENDING), ("generated_at", DESCENDING)])
    db[mapping["correlation_metrics"]].create_index(
        [("symbol_a", ASCENDING), ("symbol_b", ASCENDING), ("timestamp", DESCENDING)]
    )
    db[mapping["alerts"]].create_index([("triggered_at", DESCENDING), ("is_active", ASCENDING)])
    db[mapping["scheduler_jobs"]].create_index([("job_name", ASCENDING), ("started_at", DESCENDING)])
    db[mapping["freshness_status"]].create_index([("source", ASCENDING)], unique=True)

    db[mapping["scheduler_jobs"]].update_one(
        {"job_name": "_bootstrap"},
        {"$setOnInsert": {"job_name": "_bootstrap", "status": "ready", "created_at": _utc_now()}},
        upsert=True,
    )
