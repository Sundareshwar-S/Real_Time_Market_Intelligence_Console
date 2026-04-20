from time import perf_counter

import httpx

from ...core.utils import format_timestamp

_COINGECKO_ID_BY_SYMBOL = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
}

_GLOBAL_MARKET_CAP_CACHE: dict[str, float | str | None] = {
    "market_cap_usd": None,
    "cached_at_perf": None,
}


def _to_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            normalized = value.strip().replace(",", "").replace("$", "").replace("%", "")
            if normalized == "":
                return None
            return float(normalized)
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_coingecko_market_metrics(
    symbols: tuple[str, ...],
    timeout_seconds: int = 10,
    base_url: str = "https://api.coingecko.com/api/v3",
) -> tuple[dict[str, dict], str | None]:
    symbol_to_id = {
        str(symbol).upper(): _COINGECKO_ID_BY_SYMBOL[str(symbol).upper()]
        for symbol in symbols
        if _COINGECKO_ID_BY_SYMBOL.get(str(symbol).upper())
    }
    if not symbol_to_id:
        return {}, None

    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/simple/price",
            params={
                "ids": ",".join(sorted(set(symbol_to_id.values()))),
                "vs_currencies": "usd",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            },
            timeout=timeout_seconds,
        )
    except httpx.RequestError as exc:
        return {}, f"CoinGecko request failed: {exc}"

    if response.status_code != 200:
        return {}, f"CoinGecko response status {response.status_code}: {response.text[:200]}"

    payload = response.json()
    metrics_by_symbol: dict[str, dict] = {}
    for symbol, coin_id in symbol_to_id.items():
        row = payload.get(coin_id) or {}
        price = _to_float(row.get("usd"))
        market_cap = _to_float(row.get("usd_market_cap"))
        volume_24h = _to_float(row.get("usd_24h_vol"))
        if price is None and market_cap is None and volume_24h is None:
            continue
        metrics_by_symbol[symbol] = {
            "price": price,
            "market_cap": market_cap,
            "volume_24h": volume_24h,
        }
    return metrics_by_symbol, None


def _extract_crypto_point(payload: dict, fallback_symbol: str) -> dict | None:
    symbols = payload.get("symbols")
    if isinstance(symbols, list) and symbols:
        point = symbols[0]
    elif isinstance(symbols, dict):
        point = symbols
    else:
        point = payload

    symbol = str(point.get("symbol") or fallback_symbol).upper()
    value = _to_float(point.get("last", point.get("price")))
    if value is None:
        return None
    return {
        "symbol": symbol,
        "name": symbol,
        "value": value,
        "change_24h": _to_float(point.get("daily_change_percentage", point.get("change_24h"))),
        "volume_24h": _to_float(point.get("volume", point.get("volume_24h"))),
        "market_cap": _to_float(point.get("market_cap")),
        "meta": {
            "source_exchange": point.get("source_exchange"),
            "raw_date": point.get("date"),
            "lowest": _to_float(point.get("lowest")),
            "highest": _to_float(point.get("highest")),
        },
    }


def fetch_global_crypto_market_cap_usd(
    timeout_seconds: int = 10,
    base_url: str = "https://api.coingecko.com/api/v3",
    cache_ttl_seconds: int = 300,
) -> dict:
    now_perf = perf_counter()
    cached_at_perf = _GLOBAL_MARKET_CAP_CACHE.get("cached_at_perf")
    cached_value = _GLOBAL_MARKET_CAP_CACHE.get("market_cap_usd")
    if (
        isinstance(cached_at_perf, (int, float))
        and (now_perf - float(cached_at_perf)) <= max(1, int(cache_ttl_seconds))
        and isinstance(cached_value, (int, float))
        and float(cached_value) > 0
    ):
        return {"market_cap_usd": float(cached_value), "source": "coingecko", "cached": True}

    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/global",
            timeout=timeout_seconds,
        )
    except httpx.RequestError as exc:
        return {"market_cap_usd": None, "source": "coingecko", "cached": False, "error": str(exc)}

    if response.status_code != 200:
        return {
            "market_cap_usd": None,
            "source": "coingecko",
            "cached": False,
            "error": f"status={response.status_code}",
        }

    payload = response.json()
    data = payload.get("data") or {}
    total_market_cap = data.get("total_market_cap") or {}
    market_cap_usd = _to_float(total_market_cap.get("usd"))
    if market_cap_usd is None or market_cap_usd <= 0:
        return {
            "market_cap_usd": None,
            "source": "coingecko",
            "cached": False,
            "error": "missing_usd_market_cap",
        }

    _GLOBAL_MARKET_CAP_CACHE["market_cap_usd"] = market_cap_usd
    _GLOBAL_MARKET_CAP_CACHE["cached_at_perf"] = now_perf
    return {"market_cap_usd": market_cap_usd, "source": "coingecko", "cached": False}


def validate_crypto_key(api_key: str, timeout_seconds: int = 10) -> dict:
    provider = "freecryptoapi"
    if not api_key:
        return {
            "provider": provider,
            "ok": False,
            "status_code": None,
            "latency_ms": None,
            "message": "CRYPTO_API_KEY is not configured.",
        }

    url = "https://api.freecryptoapi.com/v1/getData"
    params = {"symbol": "BTC", "token": api_key}
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

    payload = response.json() if response.status_code == 200 else {}
    ok = response.status_code == 200 and payload.get("status") in {"success", True}
    message = "Key is valid and data fetched." if ok else (payload.get("error") or response.text[:200])
    return {
        "provider": provider,
        "ok": ok,
        "status_code": response.status_code,
        "latency_ms": round((perf_counter() - start) * 1000, 2),
        "message": message,
    }


def fetch_crypto_data(
    api_key: str,
    symbols: tuple[str, ...],
    timeout_seconds: int = 10,
    base_url: str = "https://api.freecryptoapi.com",
) -> dict:
    provider = "freecryptoapi"
    if not api_key:
        return {
            "provider": provider,
            "records": [],
            "errors": [{"provider": provider, "symbol": None, "message": "CRYPTO_API_KEY is not configured."}],
        }

    records: list[dict] = []
    errors: list[dict] = []
    supplemental_metrics, supplemental_error = _fetch_coingecko_market_metrics(
        symbols,
        timeout_seconds=timeout_seconds,
    )
    if supplemental_error:
        errors.append({"provider": "coingecko", "symbol": None, "message": supplemental_error})

    for symbol in symbols:
        url = f"{base_url.rstrip('/')}/v1/getData"
        params = {"symbol": symbol.upper(), "token": api_key}
        try:
            response = httpx.get(url, params=params, timeout=timeout_seconds)
        except httpx.RequestError as exc:
            errors.append({"provider": provider, "symbol": symbol.upper(), "message": f"Request failed: {exc}"})
            continue

        if response.status_code != 200:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol.upper(),
                    "status_code": response.status_code,
                    "message": response.text[:200],
                }
            )
            continue

        payload = response.json()
        if payload.get("status") not in {"success", True}:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol.upper(),
                    "status_code": response.status_code,
                    "message": str(payload.get("error") or "Provider returned unsuccessful status."),
                }
            )
            continue

        point = _extract_crypto_point(payload, symbol.upper())
        if point is None:
            errors.append(
                {
                    "provider": provider,
                    "symbol": symbol.upper(),
                    "status_code": response.status_code,
                    "message": "Provider payload missing numeric price data.",
                }
            )
            continue

        metrics_fallback = supplemental_metrics.get(point["symbol"], {})
        price = point["value"]
        if price is None or price <= 0:
            price = metrics_fallback.get("price")
        if price is None or price <= 0:
            errors.append(
                {
                    "provider": provider,
                    "symbol": point["symbol"],
                    "status_code": response.status_code,
                    "message": "Provider returned non-positive price and no fallback price was available.",
                }
            )
            continue
        coingecko_volume_24h = metrics_fallback.get("volume_24h")
        volume_24h = coingecko_volume_24h if coingecko_volume_24h is not None else point["volume_24h"]
        market_cap = point["market_cap"]
        if market_cap is None:
            market_cap = metrics_fallback.get("market_cap")

        records.append(
            {
                "provider": provider,
                "asset_type": "crypto",
                "symbol": point["symbol"],
                "name": point["name"],
                "value": price,
                "change_24h": point["change_24h"],
                "volume_24h": volume_24h,
                "market_cap": market_cap,
                "captured_at": format_timestamp(),
                "meta": point["meta"],
            }
        )

    return {"provider": provider, "records": records, "errors": errors}
