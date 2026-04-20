from __future__ import annotations


def map_anomaly_item(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "source": row.get("source"),
        "value": row.get("value"),
        "type": row.get("anomaly_type"),
        "score": row.get("anomaly_score"),
        "severity": row.get("severity"),
        "method": row.get("method"),
        "is_anomaly": row.get("is_anomaly"),
        "timestamp": row.get("timestamp"),
    }


def build_anomaly_payload(records: list[dict]) -> dict:
    events = [map_anomaly_item(item) for item in records]
    updated_at = events[0]["timestamp"] if events else None
    return {
        "events": events,
        "updated_at": updated_at,
    }
