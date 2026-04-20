from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ...core.utils import format_timestamp


def _to_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_stock_history(
    api_key: str,
    tickers: tuple[str, ...],
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    period_years: int = 4,
    timeout_seconds: int = 20,
    base_url: str = "https://api.polygon.io",
) -> dict:
    provider = "polygon_history"
    end = end_time.astimezone(timezone.utc) if end_time else datetime.now(timezone.utc)
    start = (
        start_time.astimezone(timezone.utc)
        if start_time
        else end - timedelta(days=max(1, period_years) * 365)
    )

    if not api_key:
        return {
            "provider": provider,
            "records": [],
            "errors": [
                {
                    "provider": provider,
                    "symbol": None,
                    "message": "STOCK_API_KEY is not configured.",
                }
            ],
            "window": {
                "start_time": format_timestamp(start),
                "end_time": format_timestamp(end),
                "interval": "1d",
            },
        }

    records: list[dict] = []
    errors: list[dict] = []
    start_label = start.date().isoformat()
    end_label = end.date().isoformat()

    for ticker in tickers:
        symbol = str(ticker).upper()
        url = f"{base_url.rstrip('/')}/v2/aggs/ticker/{symbol}/range/1/day/{start_label}/{end_label}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": api_key,
        }
        try:
            response = httpx.get(url, params=params, timeout=timeout_seconds)
        except httpx.RequestError as exc:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol,
                    "message": f"Request failed: {exc}",
                }
            )
            continue

        if response.status_code != 200:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol,
                    "status_code": response.status_code,
                    "message": response.text[:200],
                }
            )
            continue

        payload = response.json()
        result_rows = payload.get("results") or []
        if not result_rows:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol,
                    "message": "No historical rows returned.",
                }
            )
            continue

        previous_close: float | None = None
        for row in result_rows:
            close = _to_float(row.get("c"))
            if close is None:
                continue
            open_price = _to_float(row.get("o"))
            high = _to_float(row.get("h"))
            low = _to_float(row.get("l"))
            volume = _to_float(row.get("v"))
            timestamp_ms = row.get("t")
            if timestamp_ms is None:
                continue
            captured_at = datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=timezone.utc)

            change_24h: float | None = None
            if previous_close is not None and previous_close != 0:
                change_24h = ((close - previous_close) / previous_close) * 100
            elif open_price is not None and open_price != 0:
                change_24h = ((close - open_price) / open_price) * 100

            records.append(
                {
                    "provider": provider,
                    "asset_type": "stock",
                    "symbol": symbol,
                    "name": symbol,
                    "value": close,
                    "change_24h": change_24h,
                    "volume_24h": volume,
                    "market_cap": None,
                    "captured_at": format_timestamp(captured_at),
                    "meta": {"high": high, "low": low},
                }
            )
            previous_close = close

    return {
        "provider": provider,
        "records": records,
        "errors": errors,
        "window": {
            "start_time": format_timestamp(start),
            "end_time": format_timestamp(end),
            "interval": "1d",
        },
    }
