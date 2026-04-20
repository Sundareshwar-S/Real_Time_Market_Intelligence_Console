from time import perf_counter

import httpx

from ...core.utils import format_timestamp


def validate_openweather_key(api_key: str, timeout_seconds: int = 10) -> dict:
    provider = "openweather"
    if not api_key:
        return {
            "provider": provider,
            "ok": False,
            "status_code": None,
            "latency_ms": None,
            "message": "OPENWEATHER_API_KEY is not configured.",
        }

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": "London", "appid": api_key}
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


def fetch_weather_data(
    api_key: str,
    cities: tuple[str, ...],
    timeout_seconds: int = 10,
    base_url: str = "https://api.openweathermap.org",
) -> dict:
    provider = "openweather"
    if not api_key:
        return {
            "provider": provider,
            "records": [],
            "errors": [{"provider": provider, "symbol": None, "message": "OPENWEATHER_API_KEY is not configured."}],
        }

    records: list[dict] = []
    errors: list[dict] = []

    for city in cities:
        url = f"{base_url.rstrip('/')}/data/2.5/weather"
        params = {"q": city, "appid": api_key, "units": "metric"}
        try:
            response = httpx.get(url, params=params, timeout=timeout_seconds)
        except httpx.RequestError as exc:
            errors.append({"provider": provider, "symbol": city, "message": f"Request failed: {exc}"})
            continue

        if response.status_code != 200:
            errors.append(
                {
                    "provider": provider,
                    "symbol": city,
                    "status_code": response.status_code,
                    "message": response.text[:200],
                }
            )
            continue

        payload = response.json()
        main = payload.get("main") or {}
        weather_list = payload.get("weather") or []
        descriptor = weather_list[0].get("main") if weather_list else "Weather"

        records.append(
            {
                "provider": provider,
                "asset_type": "weather",
                "symbol": f"WTHR-{city.upper()}",
                "name": city,
                "value": main.get("temp"),
                "change_24h": None,
                "volume_24h": None,
                "market_cap": None,
                "captured_at": format_timestamp(),
                "meta": {
                    "feels_like": main.get("feels_like"),
                    "humidity": main.get("humidity"),
                    "condition": descriptor,
                },
            }
        )

    return {"provider": provider, "records": records, "errors": errors}
