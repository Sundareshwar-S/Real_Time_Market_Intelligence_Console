from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    project_root = Path(__file__).resolve().parents[2]
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

from flask import Flask, jsonify
from flask_cors import CORS
from flask_socketio import SocketIO

from backend.src.api.anomalies import anomalies_bp
from backend.src.api.correlation import correlation_bp
from backend.src.api.data import data_bp
from backend.src.api.forecast import forecast_bp
from backend.src.api.ops import ops_bp
from backend.src.api.series import series_bp
from backend.src.api.websocket import register_socket_events, websocket_bp
from backend.src.core.config import get_settings
from backend.src.core.utils import format_timestamp, get_logger
from backend.src.database.db import init_db
from backend.src.scheduler.scheduler import scheduler_manager
from backend.src.services.processing.model_registry import initialize_model_registry

socketio = SocketIO()


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(data_bp)
    app.register_blueprint(forecast_bp)
    app.register_blueprint(anomalies_bp)
    app.register_blueprint(correlation_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(series_bp)
    app.register_blueprint(websocket_bp)


def create_app() -> Flask:
    settings = get_settings()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = settings.secret_key
    app.config["JSON_SORT_KEYS"] = False
    logger = get_logger("backend.app")

    allowed_origins = [settings.cors_origin]
    CORS(
        app,
        resources={r"/api/*": {"origins": allowed_origins}},
        supports_credentials=False,
    )
    socketio.init_app(
        app,
        cors_allowed_origins=allowed_origins,
        async_mode=settings.socketio_async_mode,
    )

    bootstrap_warnings: list[str] = []
    try:
        init_db()
    except Exception as exc:  # pragma: no cover - defensive startup handling
        logger.exception("Database initialization failed")
        bootstrap_warnings.append(f"database_init_failed:{exc}")

    try:
        model_registry_state = initialize_model_registry(settings)
    except Exception as exc:  # pragma: no cover - defensive startup handling
        logger.exception("Model registry initialization failed")
        bootstrap_warnings.append(f"model_registry_init_failed:{exc}")
        model_registry_state = {
            "models": [],
            "metadata_updated_at": None,
            "errors": [str(exc)],
        }

    register_blueprints(app)
    register_socket_events(socketio)
    scheduler_manager.set_socketio(socketio)
    app.config["ML_MODEL_REGISTRY"] = model_registry_state
    app.config["BOOTSTRAP_WARNINGS"] = bootstrap_warnings

    if bootstrap_warnings:
        logger.warning("Backend bootstrapped with warnings: %s", bootstrap_warnings)
    logger.info("Backend bootstrap completed.")

    @app.get("/")
    def root():
        warnings = app.config.get("BOOTSTRAP_WARNINGS", [])
        return jsonify(
            {
                "service": "Real-Time Market Intelligence Console",
                "status": "degraded" if warnings else "running",
                "timestamp": format_timestamp(),
                "warnings": warnings,
            }
        )

    return app


if __name__ == "__main__":
    current_settings = get_settings()
    application = create_app()
    socketio.run(
        application,
        host=current_settings.host,
        port=current_settings.port,
        debug=current_settings.debug,
    )
