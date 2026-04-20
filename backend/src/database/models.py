from __future__ import annotations

from typing import TypedDict


class MarketDataDocument(TypedDict, total=False):
    symbol: str
    name: str
    source: str
    price: float
    change_24h: float | None
    volume_24h: float | None
    market_cap: float | None
    captured_at: str
    created_at: str


class ForecastDocument(TypedDict, total=False):
    model: str
    target_symbol: str
    horizon: str
    source: str
    predicted_value: float
    confidence: float | None
    generated_at: str
    created_at: str


class AlertDocument(TypedDict, total=False):
    severity: str
    alert_type: str
    source: str
    message: str
    is_active: bool
    triggered_at: str
    created_at: str
