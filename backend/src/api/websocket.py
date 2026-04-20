from __future__ import annotations

import hashlib
import json
from threading import Lock
from time import perf_counter

from flask import Blueprint, jsonify, request
from flask_socketio import SocketIO, emit

from ..core.config import get_settings
from ..core.utils import format_timestamp, get_logger
from ..database.repository import fetch_freshness_status, fetch_market_stream_data
from ..schemas.common_schema import build_error_response, build_success_response

websocket_bp = Blueprint("websocket", __name__, url_prefix="/api")
logger = get_logger("backend.api.websocket")
_events_registered = False
_background_started = False
_socketio_ref: SocketIO | None = None
_state_lock = Lock()
_stream_active = False
_emit_interval_seconds = 2
_connected_clients: set[str] = set()
_heartbeat_by_client: dict[str, str] = {}
_last_emit_at: dict[str, float] = {}
_last_data_signature_by_source: dict[str, str] = {}
_last_system_status_signature: str | None = None


def _hash_payload(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def _should_emit(event_name: str, min_interval: float, force: bool) -> bool:
    if force:
        return True
    now = perf_counter()
    with _state_lock:
        last = _last_emit_at.get(event_name, 0.0)
        if now - last < min_interval:
            return False
        _last_emit_at[event_name] = now
    return True


def _emit_event(
    event_name: str,
    payload: dict,
    *,
    min_interval: float = 0.0,
    force: bool = False,
) -> bool:
    if _socketio_ref is None:
        return False
    if not _should_emit(event_name, min_interval, force):
        return False
    _socketio_ref.emit(event_name, payload)
    return True


def _normalize_market_rows(rows: list[dict], source_hint: str | None = None) -> list[dict]:
    items = []
    for row in rows:
        value = row.get("value")
        if value is None:
            value = row.get("price")
        if value is None:
            continue
        source = str(row.get("source") or source_hint or "unknown").lower()
        items.append(
            {
                "symbol": str(row.get("symbol") or "").upper(),
                "name": row.get("name"),
                "source": source,
                "value": value,
                "change_24h": row.get("change_24h"),
                "volume_24h": row.get("volume_24h"),
                "market_cap": row.get("market_cap"),
                "captured_at": row.get("captured_at") or row.get("timestamp") or format_timestamp(),
            }
        )
    items.sort(key=lambda item: item.get("captured_at") or "", reverse=True)
    return items


def _build_data_signature(items: list[dict]) -> str:
    if not items:
        return ""
    slim = [
        {
            "symbol": row.get("symbol"),
            "source": row.get("source"),
            "value": row.get("value"),
            "captured_at": row.get("captured_at"),
        }
        for row in items
    ]
    return _hash_payload({"items": slim})


def _connection_health() -> dict:
    with _state_lock:
        last_heartbeat = max(_heartbeat_by_client.values()) if _heartbeat_by_client else None
        connected_clients = len(_connected_clients)
    return {
        "transport": "socketio",
        "connected_clients": connected_clients,
        "last_heartbeat_at": last_heartbeat,
    }


def _build_system_status(extra: dict | None = None) -> dict:
    payload = {
        "timestamp": format_timestamp(),
        "stream": get_stream_state(),
        "connection": _connection_health(),
        "freshness": fetch_freshness_status(),
    }
    if extra:
        payload.update(extra)
    return payload


def emit_system_status_event(extra: dict | None = None, *, force: bool = False) -> bool:
    global _last_system_status_signature
    payload = _build_system_status(extra)
    signature_payload = {key: value for key, value in payload.items() if key != "timestamp"}
    signature = _hash_payload(signature_payload)
    with _state_lock:
        if not force and signature == _last_system_status_signature:
            return False
        _last_system_status_signature = signature
    return _emit_event("system_status", payload, min_interval=1.0, force=force)


def emit_new_data_event(
    rows: list[dict],
    *,
    source: str = "stream",
    freshness: list[dict] | None = None,
    force: bool = False,
) -> bool:
    items = _normalize_market_rows(rows, source_hint=source)
    source_key = source.lower()
    signature = _build_data_signature(items)
    with _state_lock:
        previous = _last_data_signature_by_source.get(source_key)
        if not force and signature and signature == previous:
            return False
        _last_data_signature_by_source[source_key] = signature
    payload = {
        "timestamp": format_timestamp(),
        "source": source_key,
        "count": len(items),
        "items": items,
        "freshness": freshness if freshness is not None else fetch_freshness_status(),
    }
    return _emit_event("new_data", payload, min_interval=0.2, force=force)


def emit_anomaly_event(events: list[dict], *, source: str = "processing", force: bool = False) -> bool:
    anomaly_events = []
    for item in events:
        if item.get("is_anomaly") is False:
            continue
        anomaly_events.append(
            {
                "symbol": str(item.get("symbol") or "").upper(),
                "source": str(item.get("source") or source).lower(),
                "type": str(item.get("anomaly_type") or "volatility"),
                "score": item.get("anomaly_score"),
                "severity": str(item.get("severity") or "low"),
                "value": item.get("value"),
                "method": item.get("method") or "zscore+isolation_forest",
                "timestamp": item.get("timestamp") or format_timestamp(),
            }
        )
    if not anomaly_events:
        return False
    payload = {
        "timestamp": format_timestamp(),
        "source": source,
        "count": len(anomaly_events),
        "events": anomaly_events,
    }
    return _emit_event("anomaly_detected", payload, min_interval=0.1, force=force)


def emit_alert_event(alerts: list[dict], *, source: str = "processing", force: bool = False) -> bool:
    alert_items = []
    for item in alerts:
        alert_items.append(
            {
                "id": item.get("id"),
                "severity": item.get("severity"),
                "type": item.get("alert_type") or item.get("type"),
                "source": item.get("source") or source,
                "message": item.get("message"),
                "is_active": item.get("is_active"),
                "triggered_at": item.get("triggered_at") or format_timestamp(),
            }
        )
    if not alert_items:
        return False
    payload = {
        "timestamp": format_timestamp(),
        "source": source,
        "count": len(alert_items),
        "alerts": alert_items,
    }
    return _emit_event("alert_triggered", payload, min_interval=0.1, force=force)


@websocket_bp.get("/websocket/status")
def websocket_status():
    try:
        response = build_success_response(
            data={
                "service": "websocket",
                "status": "ready",
                "stream": get_stream_state(),
                "connection": _connection_health(),
            },
            source="websocket",
            freshness=fetch_freshness_status(),
            no_data=False,
        )
        return jsonify(response), 200
    except Exception as exc:
        logger.exception("Failed to read websocket status")
        return jsonify(
            build_error_response(
                "repository_error",
                "Failed to fetch websocket status.",
                {"reason": str(exc)},
            )
        ), 500


def get_stream_state() -> dict:
    with _state_lock:
        return {
            "active": _stream_active,
            "interval_seconds": _emit_interval_seconds,
            "connected_clients": len(_connected_clients),
        }


def set_stream_active(active: bool) -> dict:
    global _stream_active
    with _state_lock:
        _stream_active = active
        state = {
            "active": _stream_active,
            "interval_seconds": _emit_interval_seconds,
            "connected_clients": len(_connected_clients),
        }
    if _socketio_ref is not None:
        _socketio_ref.emit("stream_state", state)
    emit_system_status_event({"stream": state}, force=True)
    return state


def _stream_loop() -> None:
    while True:
        try:
            if _socketio_ref is None:
                return
            _socketio_ref.sleep(_emit_interval_seconds)
            if not get_stream_state()["active"]:
                emit_system_status_event({"reason": "stream_paused"})
                continue
            rows = fetch_market_stream_data(limit_per_source=8)
            freshness = fetch_freshness_status()
            emit_new_data_event(rows, source="stream", freshness=freshness)
            emit_system_status_event({"freshness": freshness})
        except Exception as exc:  # pragma: no cover - defensive stream loop resilience
            logger.exception("Websocket stream loop failed; retrying: %s", exc)
            if _socketio_ref is None:
                return
            _socketio_ref.sleep(5)


def register_socket_events(socketio: SocketIO) -> None:
    global _events_registered, _background_started, _socketio_ref, _emit_interval_seconds
    if _events_registered:
        return

    _events_registered = True
    _socketio_ref = socketio
    settings = get_settings()
    _emit_interval_seconds = max(1, settings.websocket_emit_interval_seconds)

    if not _background_started:
        _background_started = True
        socketio.start_background_task(_stream_loop)

    @socketio.on_error_default
    def on_socket_error(exc):
        logger.exception("Unhandled Socket.IO event error: %s", exc)
        try:
            emit("system_status", _build_system_status({"socket_error": str(exc)}))
        except Exception:
            logger.exception("Failed to emit socket error system_status event")

    @socketio.on("connect")
    def on_connect():
        sid = request.sid
        heartbeat_ts = format_timestamp()
        with _state_lock:
            _connected_clients.add(sid)
            _heartbeat_by_client[sid] = heartbeat_ts
        emit(
            "system_status",
            _build_system_status({"connection_event": "connect"}),
        )
        emit("stream_state", get_stream_state())
        emit_system_status_event({"connection_event": "connect"}, force=True)

    @socketio.on("disconnect")
    def on_disconnect():
        sid = request.sid
        with _state_lock:
            _connected_clients.discard(sid)
            _heartbeat_by_client.pop(sid, None)
        emit_system_status_event({"connection_event": "disconnect"}, force=True)

    @socketio.on("ping")
    def on_ping(payload=None):
        emit(
            "pong",
            {"echo": payload, "timestamp": format_timestamp()},
        )

    @socketio.on("client_heartbeat")
    def on_client_heartbeat(payload=None):
        sid = request.sid
        heartbeat_ts = format_timestamp()
        with _state_lock:
            _heartbeat_by_client[sid] = heartbeat_ts
        emit("heartbeat_ack", {"timestamp": heartbeat_ts, "echo": payload})

    @socketio.on("request_snapshot")
    def on_request_snapshot():
        rows = fetch_market_stream_data(limit_per_source=12)
        freshness = fetch_freshness_status()
        emit(
            "new_data",
            {
                "timestamp": format_timestamp(),
                "source": "snapshot",
                "count": len(rows),
                "items": _normalize_market_rows(rows),
                "freshness": freshness,
            },
        )
        emit(
            "system_status",
            _build_system_status({"connection_event": "snapshot", "freshness": freshness}),
        )
