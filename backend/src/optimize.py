"""
MongoDB Optimization Script — TTL indexes and collection maintenance.

Run once (or periodically) to:
- Create TTL indexes for automatic data expiration
- Purge old documents beyond the TTL window
- Compact collections to reclaim disk space

Usage:
    python backend/src/optimize.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is importable
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from pymongo import ASCENDING  # noqa: E402
from pymongo.errors import OperationFailure  # noqa: E402

from backend.src.core.utils import get_logger  # noqa: E402
from backend.src.database.db import collection_map, get_mongo_database  # noqa: E402

logger = get_logger("backend.optimize")

# TTL policies: collection_key -> (timestamp_field, max_age_days)
TTL_POLICIES = {
    "processed_data": ("timestamp", 7),
    "anomaly_events": ("timestamp", 14),
    "scheduler_jobs": ("started_at", 3),
    "correlation_metrics": ("timestamp", 7),
    "forecast_outputs": ("generated_at", 14),
    "alerts": ("triggered_at", 14),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_ttl_indexes() -> None:
    """Create TTL indexes on collections for automatic expiration."""
    mapping = collection_map()
    db = get_mongo_database()

    for collection_key, (field, max_age_days) in TTL_POLICIES.items():
        collection_name = mapping.get(collection_key)
        if not collection_name:
            logger.warning("No collection mapped for key: %s", collection_key)
            continue

        expire_seconds = max_age_days * 86400
        index_name = f"ttl_{field}_{max_age_days}d"
        collection = db[collection_name]

        # Check if TTL index already exists
        existing_indexes = collection.index_information()
        ttl_exists = False
        for idx_name, idx_info in existing_indexes.items():
            if idx_info.get("expireAfterSeconds") is not None:
                key_fields = [k for k, _ in idx_info.get("key", [])]
                if field in key_fields:
                    if idx_info["expireAfterSeconds"] == expire_seconds:
                        logger.info(
                            "TTL index already exists: %s.%s (%dd)",
                            collection_name,
                            field,
                            max_age_days,
                        )
                        ttl_exists = True
                    else:
                        # Drop and recreate with new TTL
                        logger.info(
                            "Updating TTL index: %s.%s → %dd",
                            collection_name,
                            field,
                            max_age_days,
                        )
                        collection.drop_index(idx_name)
                    break

        if not ttl_exists:
            try:
                collection.create_index(
                    [(field, ASCENDING)],
                    name=index_name,
                    expireAfterSeconds=expire_seconds,
                )
                logger.info(
                    "Created TTL index: %s.%s (expires after %dd)",
                    collection_name,
                    field,
                    max_age_days,
                )
            except OperationFailure as exc:
                logger.error(
                    "Failed to create TTL index on %s.%s: %s",
                    collection_name,
                    field,
                    exc,
                )


def purge_old_documents() -> None:
    """Delete documents older than the TTL window (immediate cleanup)."""
    mapping = collection_map()
    db = get_mongo_database()
    now = _utc_now()

    for collection_key, (field, max_age_days) in TTL_POLICIES.items():
        collection_name = mapping.get(collection_key)
        if not collection_name:
            continue

        cutoff = now - timedelta(days=max_age_days)
        collection = db[collection_name]

        try:
            result = collection.delete_many({field: {"$lt": cutoff}})
            if result.deleted_count > 0:
                logger.info(
                    "Purged %d old documents from %s (older than %dd)",
                    result.deleted_count,
                    collection_name,
                    max_age_days,
                )
            else:
                logger.info("No old documents to purge from %s", collection_name)
        except Exception as exc:
            logger.error("Failed to purge %s: %s", collection_name, exc)


def compact_collections() -> None:
    """Run compact on collections to reclaim disk space."""
    mapping = collection_map()
    db = get_mongo_database()

    for collection_key in TTL_POLICIES:
        collection_name = mapping.get(collection_key)
        if not collection_name:
            continue

        try:
            db.command("compact", collection_name)
            logger.info("Compacted collection: %s", collection_name)
        except OperationFailure as exc:
            # compact may not be supported on all storage engines or requires admin
            logger.warning("Could not compact %s: %s", collection_name, exc)


def print_collection_stats() -> None:
    """Print document counts and sizes for all collections."""
    mapping = collection_map()
    db = get_mongo_database()

    print("\n" + "=" * 60)
    print("Collection Statistics")
    print("=" * 60)

    total_docs = 0
    for key, name in sorted(mapping.items()):
        try:
            stats = db.command("collStats", name)
            count = stats.get("count", 0)
            size_mb = stats.get("size", 0) / (1024 * 1024)
            total_docs += count
            print(f"  {name:30s}  {count:>8,} docs  {size_mb:>8.1f} MB")
        except Exception:
            count = db[name].estimated_document_count()
            total_docs += count
            print(f"  {name:30s}  {count:>8,} docs  (size unknown)")

    print(f"\n  {'TOTAL':30s}  {total_docs:>8,} docs")
    print("=" * 60)


def main() -> None:
    """Run all optimization steps."""
    logger.info("Starting MongoDB optimization...")

    print_collection_stats()

    logger.info("Step 1/3: Creating TTL indexes...")
    create_ttl_indexes()

    logger.info("Step 2/3: Purging old documents...")
    purge_old_documents()

    logger.info("Step 3/3: Compacting collections...")
    compact_collections()

    print_collection_stats()

    print("\n✅ Optimization complete!")
    print("\nRecommendations:")
    print("  - MongoDB WiredTiger cache: set to 256MB-512MB in mongod.conf:")
    print("      storage.wiredTiger.engineConfig.cacheSizeGB: 0.25")
    print("  - Run this script periodically (e.g., weekly) to maintain performance")
    print("  - TTL indexes will automatically delete expired documents going forward")


if __name__ == "__main__":
    main()
