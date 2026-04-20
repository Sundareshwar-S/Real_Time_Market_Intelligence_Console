from __future__ import annotations


def map_market_item(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "source": row.get("source"),
        "value": row.get("price") if row.get("price") is not None else row.get("value"),
        "change_24h": row.get("change_24h"),
        "volume_24h": row.get("volume_24h"),
        "market_cap": row.get("market_cap"),
        "captured_at": row.get("captured_at"),
    }


def build_data_payload(
    records: list[dict],
    *,
    global_crypto_market_cap: float | None = None,
    global_crypto_market_cap_source: str | None = None,
) -> dict:
    items = [map_market_item(item) for item in records]
    updated_at = items[0]["captured_at"] if items else None
    payload = {
        "items": items,
        "updated_at": updated_at,
    }
    if global_crypto_market_cap is not None:
        payload["global_crypto_market_cap"] = global_crypto_market_cap
    if global_crypto_market_cap_source:
        payload["global_crypto_market_cap_source"] = global_crypto_market_cap_source
    return payload


def build_latest_payload(record: dict | None) -> dict:
    if not record:
        return {"latest": None}
    return {"latest": map_market_item(record)}
