from __future__ import annotations


def build_metrics_payload(metrics: dict) -> dict:
    return {
        "metrics": metrics,
        "updated_at": metrics.get("updated_at"),
    }
