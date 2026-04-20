from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..database.repository import (
    fetch_alerts,
    fetch_anomaly_events,
    fetch_freshness_status,
    fetch_market_data,
    fetch_scheduler_job_logs,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def build_metrics_snapshot(job_limit: int = 200, source: str | None = None) -> dict:
    now = _utc_now()
    freshness = fetch_freshness_status(source=source)
    jobs = fetch_scheduler_job_logs(limit=job_limit)
    active_alerts = fetch_alerts(limit=200, active_only=True, source=source)
    anomaly_events = fetch_anomaly_events(limit=200, anomalies_only=True)
    recent_market = fetch_market_data(limit=500, source=source)

    stale_sources = 0
    for row in freshness:
        last_update = _parse_iso_datetime(row.get("last_update"))
        age_seconds = (now - last_update).total_seconds() if last_update else None
        if row.get("is_stale") or age_seconds is None or age_seconds > 180:
            stale_sources += 1

    succeeded_jobs = sum(1 for item in jobs if item.get("status") in {"success", "skipped"})
    failed_jobs = sum(1 for item in jobs if item.get("status") == "failed")
    total_jobs = len(jobs)
    success_rate = (succeeded_jobs / total_jobs) if total_jobs else None

    latest_market_ts = recent_market[0]["captured_at"] if recent_market else None
    recent_window = now - timedelta(minutes=30)
    recent_anomalies = 0
    for row in anomaly_events:
        ts = _parse_iso_datetime(row.get("timestamp"))
        if ts and ts >= recent_window:
            recent_anomalies += 1

    return {
        "updated_at": now.isoformat().replace("+00:00", "Z"),
        "pipeline": {
            "scheduler_running": any(item.get("status") == "success" for item in jobs[:3]),
            "job_success_rate": success_rate,
            "total_jobs_observed": total_jobs,
            "failed_jobs_observed": failed_jobs,
        },
        "freshness": {
            "sources_total": len(freshness),
            "sources_stale": stale_sources,
            "latest_market_timestamp": latest_market_ts,
            "by_source": freshness,
        },
        "alerts": {
            "active_alerts": len(active_alerts),
            "recent_anomalies_30m": recent_anomalies,
        },
        "throughput": {
            "market_points_observed": len(recent_market),
            "scheduler_jobs_observed": total_jobs,
        },
    }
