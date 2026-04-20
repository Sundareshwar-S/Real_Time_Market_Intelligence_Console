from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ...core.utils import format_timestamp

_BINANCE_PAIR_BY_SYMBOL = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "ADA": "ADAUSDT",
    "DOGE": "DOGEUSDT",
}


def _to_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_daily_klines(
    pair: str,
    *,
    start_ms: int,
    end_ms: int,
    timeout_seconds: int,
    base_url: str,
) -> tuple[list[list], list[dict]]:
    rows: list[list] = []
    errors: list[dict] = []
    cursor = start_ms

    while cursor <= end_ms:
        params = {
            "symbol": pair,
            "interval": "1d",
            "startTime": cursor,
            "endTime": end_ms,
            "limit": 1000,
        }
        try:
            response = httpx.get(
                f"{base_url.rstrip('/')}/api/v3/klines",
                params=params,
                timeout=timeout_seconds,
            )
        except httpx.RequestError as exc:
            errors.append({"pair": pair, "message": f"Request failed: {exc}"})
            break

        if response.status_code != 200:
            errors.append(
                {
                    "pair": pair,
                    "status_code": response.status_code,
                    "message": response.text[:200],
                }
            )
            break

        batch = response.json()
        if not isinstance(batch, list) or not batch:
            break

        rows.extend(batch)
        last_close_ms = int(batch[-1][6])
        next_cursor = last_close_ms + 1
        if next_cursor <= cursor or len(batch) < 1000:
            break
        cursor = next_cursor

    return rows, errors


def fetch_crypto_history(
    symbols: tuple[str, ...],
    days: int = 1460,
    timeout_seconds: int = 20,
    base_url: str = "https://api.binance.com",
) -> dict:
    provider = "binance_history"
    safe_days = max(1, days)
    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=safe_days)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    records: list[dict] = []
    errors: list[dict] = []

    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper()
        pair = _BINANCE_PAIR_BY_SYMBOL.get(symbol)
        if not pair:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol,
                    "message": "Unsupported symbol mapping for Binance pair.",
                }
            )
            continue

        klines, kline_errors = _fetch_daily_klines(
            pair,
            start_ms=start_ms,
            end_ms=end_ms,
            timeout_seconds=timeout_seconds,
            base_url=base_url,
        )
        for error in kline_errors:
            errors.append({"provider": provider, "symbol": symbol, **error})
        if not klines:
            continue

        previous_close: float | None = None
        for row in klines:
            open_price = _to_float(row[1])
            high = _to_float(row[2])
            low = _to_float(row[3])
            close = _to_float(row[4])
            volume = _to_float(row[5])
            close_time_ms = int(row[6])
            if close is None:
                continue

            captured_at = datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc)
            change_24h: float | None = None
            if previous_close is not None and previous_close != 0:
                change_24h = ((close - previous_close) / previous_close) * 100
            elif open_price is not None and open_price != 0:
                change_24h = ((close - open_price) / open_price) * 100

            records.append(
                {
                    "provider": provider,
                    "asset_type": "crypto",
                    "symbol": symbol,
                    "name": symbol,
                    "value": close,
                    "change_24h": change_24h,
                    "volume_24h": volume,
                    "market_cap": None,
                    "captured_at": format_timestamp(captured_at),
                    "meta": {"pair": pair, "high": high, "low": low},
                }
            )
            previous_close = close

    return {
        "provider": provider,
        "records": records,
        "errors": errors,
        "window": {"days": safe_days, "interval": "1d"},
    }
