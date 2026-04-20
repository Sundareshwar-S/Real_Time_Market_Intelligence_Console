from datetime import datetime, timezone
from time import perf_counter

import httpx

from ...core.utils import format_timestamp

_MARKET_CAP_CACHE_TTL_SECONDS = 6 * 60 * 60
_MARKET_CAP_CACHE: dict[str, tuple[float, datetime]] = {}


def _to_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_cached_market_cap(symbol: str) -> float | None:
    cached = _MARKET_CAP_CACHE.get(symbol)
    if not cached:
        return None
    value, captured_at = cached
    age_seconds = (datetime.now(timezone.utc) - captured_at).total_seconds()
    if age_seconds > _MARKET_CAP_CACHE_TTL_SECONDS:
        _MARKET_CAP_CACHE.pop(symbol, None)
        return None
    return value


def _set_cached_market_cap(symbol: str, value: float) -> None:
    _MARKET_CAP_CACHE[symbol] = (float(value), datetime.now(timezone.utc))


def _fetch_reference_market_caps(
    *,
    api_key: str,
    tickers: tuple[str, ...],
    timeout_seconds: int,
    base_url: str,
) -> tuple[dict[str, float], list[dict]]:
    market_caps: dict[str, float] = {}
    errors: list[dict] = []
    for ticker in tickers:
        symbol = str(ticker).upper()
        url = f"{base_url.rstrip('/')}/v3/reference/tickers/{symbol}"
        params = {"apiKey": api_key}
        try:
            response = httpx.get(url, params=params, timeout=timeout_seconds)
        except httpx.RequestError as exc:
            errors.append(
                {
                    "provider": "polygon_reference",
                    "symbol": symbol,
                    "message": f"Request failed: {exc}",
                }
            )
            continue

        if response.status_code != 200:
            cached_cap = _get_cached_market_cap(symbol)
            if cached_cap is not None:
                market_caps[symbol] = cached_cap
            else:
                errors.append(
                    {
                        "provider": "polygon_reference",
                        "symbol": symbol,
                        "status_code": response.status_code,
                        "message": response.text[:200],
                    }
                )
            continue

        payload = response.json()
        row = payload.get("results") or {}
        cap = _to_float(row.get("market_cap"))
        if cap is not None and cap > 0:
            market_caps[symbol] = cap
            _set_cached_market_cap(symbol, cap)
            continue
        cached_cap = _get_cached_market_cap(symbol)
        if cached_cap is not None:
            market_caps[symbol] = cached_cap
        else:
            errors.append(
                {
                    "provider": "polygon_reference",
                    "symbol": symbol,
                    "message": "market_cap missing in reference response.",
                }
            )
    return market_caps, errors


def validate_stock_key(api_key: str, timeout_seconds: int = 10) -> dict:
    provider = "polygon"
    if not api_key:
        return {
            "provider": provider,
            "ok": False,
            "status_code": None,
            "latency_ms": None,
            "message": "STOCK_API_KEY is not configured.",
        }

    url = "https://api.polygon.io/v2/aggs/ticker/AAPL/prev"
    params = {"adjusted": "true", "apiKey": api_key}
    start = perf_counter()

    try:
        response = httpx.get(url, params=params, timeout=timeout_seconds)
    except httpx.RequestError as exc:
        return {
            "provider": provider,
            "ok": False,
            "status_code": None,
            "latency_ms": round((perf_counter() - start) * 1000, 2),
            "message": f"Request failed: {exc}",
        }

    ok = response.status_code == 200
    message = "Key is valid and data fetched." if ok else response.text[:200]
    return {
        "provider": provider,
        "ok": ok,
        "status_code": response.status_code,
        "latency_ms": round((perf_counter() - start) * 1000, 2),
        "message": message,
    }


def fetch_stock_data(
    api_key: str,
    tickers: tuple[str, ...],
    timeout_seconds: int = 10,
    base_url: str = "https://api.polygon.io",
) -> dict:
    provider = "polygon"
    if not api_key:
        return {
            "provider": provider,
            "records": [],
            "errors": [{"provider": provider, "symbol": None, "message": "STOCK_API_KEY is not configured."}],
        }

    records: list[dict] = []
    errors: list[dict] = []
    market_caps, market_cap_errors = _fetch_reference_market_caps(
        api_key=api_key,
        tickers=tickers,
        timeout_seconds=timeout_seconds,
        base_url=base_url,
    )
    errors.extend(market_cap_errors)

    for ticker in tickers:
        symbol = ticker.upper()
        url = f"{base_url.rstrip('/')}/v2/aggs/ticker/{symbol}/prev"
        params = {"adjusted": "true", "apiKey": api_key}
        try:
            response = httpx.get(url, params=params, timeout=timeout_seconds)
        except httpx.RequestError as exc:
            errors.append({"provider": provider, "symbol": symbol, "message": f"Request failed: {exc}"})
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
        results = payload.get("results") or []
        if not results:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol,
                    "status_code": response.status_code,
                    "message": "No aggregate data returned.",
                }
            )
            continue

        point = results[0]
        close = point.get("c")
        open_price = point.get("o")
        timestamp_ms = point.get("t")
        if isinstance(timestamp_ms, (int, float)):
            captured_at = format_timestamp(datetime.fromtimestamp(float(timestamp_ms) / 1000, tz=timezone.utc))
        else:
            captured_at = format_timestamp()
        change_24h = None
        if isinstance(open_price, (int, float)) and open_price:
            change_24h = ((close - open_price) / open_price) * 100 if isinstance(close, (int, float)) else None

        records.append(
            {
                "provider": provider,
                "asset_type": "stock",
                "symbol": symbol,
                "name": symbol,
                "value": close,
                "change_24h": change_24h,
                "volume_24h": point.get("v"),
                "market_cap": market_caps.get(symbol),
                "captured_at": captured_at,
                "meta": {"vwap": point.get("vw"), "high": point.get("h"), "low": point.get("l")},
            }
        )

    return {"provider": provider, "records": records, "errors": errors}
