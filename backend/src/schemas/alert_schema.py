from __future__ import annotations


def map_alert_item(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "severity": row.get("severity"),
        "type": row.get("alert_type"),
        "source": row.get("source"),
        "message": row.get("message"),
        "is_active": row.get("is_active"),
        "triggered_at": row.get("triggered_at"),
    }


def build_alerts_payload(records: list[dict]) -> dict:
    alerts = [map_alert_item(item) for item in records]
    updated_at = alerts[0]["triggered_at"] if alerts else None
    return {
        "alerts": alerts,
        "updated_at": updated_at,
    }
