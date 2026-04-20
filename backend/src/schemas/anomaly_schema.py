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
    source_breakdown: dict[str, int] = {}
    severity_breakdown: dict[str, int] = {}
    for row in events:
        source = str(row.get("source") or "unknown").lower()
        severity = str(row.get("severity") or "unknown").lower()
        source_breakdown[source] = source_breakdown.get(source, 0) + 1
        severity_breakdown[severity] = severity_breakdown.get(severity, 0) + 1
    return {
        "events": events,
        "updated_at": updated_at,
        "summary": {
            "total_events": len(events),
            "source_breakdown": source_breakdown,
            "severity_breakdown": severity_breakdown,
            "symbols": len({str(row.get("symbol") or "").upper() for row in events if row.get("symbol")}),
        },
    }
