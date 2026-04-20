"""Dummy payload builders for Phase 2 API contracts."""

from datetime import datetime, timezone

from ..core.utils import format_timestamp


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_data_payload() -> dict:
    return {
        "source": "dummy",
        "updated_at": format_timestamp(),
        "items": [
            {"symbol": "BTC", "name": "Bitcoin", "price": 64230.5, "change_24h": 4.2},
            {"symbol": "ETH", "name": "Ethereum", "price": 3450.2, "change_24h": -1.8},
            {"symbol": "SOL", "name": "Solana", "price": 145.8, "change_24h": 0.7},
        ],
    }


def build_latest_payload() -> dict:
    now = _utc_now()
    second = now.second
    return {
        "source": "dummy",
        "timestamp": format_timestamp(now),
        "market_cap_usd": 2.48e12 + (second * 1.0e8),
        "volume_24h_usd": 8.42e10 + (second * 5.0e6),
        "btc_dominance": 52.1 + (second % 5) * 0.03,
        "active_anomalies": 3 + (second % 2),
    }


def build_forecast_payload() -> dict:
    return {
        "source": "dummy",
        "generated_at": format_timestamp(),
        "predictions": [
            {"model": "ARIMA-LV4", "horizon": "24h", "target": "BTC", "value": 65120.0, "confidence": 0.914},
            {"model": "LSTM-CORR", "horizon": "72h", "target": "ETH", "value": 3520.0, "confidence": 0.887},
            {"model": "XGB-SPIKE", "horizon": "12h", "target": "SOL", "value": 149.2, "confidence": 0.942},
        ],
    }


def build_correlation_payload() -> dict:
    return {
        "source": "dummy",
        "updated_at": format_timestamp(),
        "pairs": [
            {"pair": "BTC/ETH", "score": 0.84, "trend": "rising"},
            {"pair": "SOL/NASDAQ", "score": 0.69, "trend": "stable"},
            {"pair": "BTC/DXY", "score": -0.58, "trend": "falling"},
        ],
    }


def build_alerts_payload() -> dict:
    return {
        "source": "dummy",
        "updated_at": format_timestamp(),
        "alerts": [
            {"severity": "high", "type": "volatility_spike", "message": "Unusual volume in Sector Alpha", "age": "2m"},
            {"severity": "medium", "type": "drift_detected", "message": "Correlation drift from baseline", "age": "14m"},
            {"severity": "medium", "type": "latency_increase", "message": "Ingestion latency above threshold", "age": "42m"},
        ],
    }


def build_metrics_payload() -> dict:
    return {
        "source": "dummy",
        "updated_at": format_timestamp(),
        "slo": {
            "availability_pct": 99.99,
            "freshness_ms": 42,
            "error_rate_pct": 0.02,
            "pipeline_health": "healthy",
        },
    }


def build_stream_payload() -> dict:
    now = _utc_now()
    second = now.second
    return {
        "timestamp": format_timestamp(now),
        "ticker": "BTCUSD",
        "price": round(64200 + (second * 1.7), 2),
        "change_1m": round((second % 10 - 5) * 0.12, 3),
        "active_alerts": 2 + (second % 3),
        "latency_ms": 35 + (second % 10),
    }
