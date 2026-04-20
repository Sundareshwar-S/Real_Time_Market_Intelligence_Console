from flask import Blueprint, jsonify, request

from ..core.config import get_settings
from ..core.utils import get_logger
from ..database.repository import (
    fetch_freshness_status,
    fetch_market_data,
    fetch_market_stream_data,
    save_anomaly_events,
    save_forecast,
    save_forecast_outputs,
    save_market_data,
    save_processed_data,
)
from ..scheduler.scheduler import scheduler_manager
from ..schemas.common_schema import build_error_response, build_success_response
from ..services.ingestion.crypto_service import fetch_crypto_data, validate_crypto_key
from ..services.ingestion.stock_service import fetch_stock_data, validate_stock_key
from ..services.processing.anomaly import detect_anomalies
from ..services.processing.cleaner import clean_and_engineer
from ..services.processing.forecast import generate_forecasts
from .dummy_payloads import (
    build_data_payload,
    build_forecast_payload,
)
from .websocket import get_stream_state, set_stream_active

ops_bp = Blueprint("ops", __name__, url_prefix="/api")
logger = get_logger("backend.api.ops")


SUPPORTED_TASKS = [
    "validate_keys",
    "emit_dummy_once",
    "scheduler_status",
    "start_scheduler",
    "stop_scheduler",
    "run_scheduler_job",
    "run_ingestion_cycle",
    "run_full_cycle",
    "run_history_backfill",
    "seed_dummy_db",
    "ingest_live_data",
    "run_processing_pipeline",
]


def _success(data: dict, *, no_data: bool = False, freshness: list[dict] | None = None):
    return (
        jsonify(
            build_success_response(
                data=data,
                source="operations",
                no_data=no_data,
                freshness=freshness,
            )
        ),
        200,
    )


def _error(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    details: dict | None = None,
):
    return jsonify(build_error_response(code, message, details)), status_code


@ops_bp.post("/start")
def start_stream():
    try:
        state = set_stream_active(True)
        scheduler = scheduler_manager.start()
        return _success(
            {
                "operation": "start",
                "stream": state,
                "scheduler": scheduler,
            }
        )
    except Exception as exc:
        logger.exception("Failed to start stream")
        return _error(
            "operation_failed",
            "Failed to start stream.",
            status_code=500,
            details={"reason": str(exc)},
        )


@ops_bp.post("/stop")
def stop_stream():
    try:
        scheduler = scheduler_manager.stop()
        state = set_stream_active(False)
        return _success(
            {
                "operation": "stop",
                "stream": state,
                "scheduler": scheduler,
            }
        )
    except Exception as exc:
        logger.exception("Failed to stop stream")
        return _error(
            "operation_failed",
            "Failed to stop stream.",
            status_code=500,
            details={"reason": str(exc)},
        )


@ops_bp.post("/run-task")
def run_task():
    try:
        payload = request.get_json(silent=True) or {}
        task_name = payload.get("task", "validate_keys")
        if not isinstance(task_name, str) or not task_name.strip():
            raise ValueError("task must be a non-empty string.")
        task_name = task_name.strip()
        settings = get_settings()

        if task_name == "validate_keys":
            timeout = max(1, settings.request_timeout_seconds)
            results = [
                validate_stock_key(settings.stock_api_key, timeout),
                validate_crypto_key(settings.crypto_api_key, timeout),
            ]
            all_ok = all(item["ok"] for item in results)
            return _success(
                {
                    "task": "validate_keys",
                    "ready": all_ok,
                    "results": results,
                }
            )

        if task_name == "emit_dummy_once":
            live_rows = fetch_market_stream_data(limit_per_source=8)
            freshness = fetch_freshness_status()
            return _success(
                {
                    "task": "emit_dummy_once",
                    "stream": get_stream_state(),
                    "event": "new_data",
                    "new_data": {
                        "items": [
                            {
                                "symbol": row.get("symbol"),
                                "source": row.get("source"),
                                "value": row.get("price") if row.get("price") is not None else row.get("value"),
                                "captured_at": row.get("captured_at"),
                            }
                            for row in live_rows
                        ],
                    },
                },
                freshness=freshness,
                no_data=len(live_rows) == 0,
            )

        if task_name == "scheduler_status":
            return _success(
                {
                    "task": "scheduler_status",
                    "scheduler": scheduler_manager.status(),
                }
            )

        if task_name == "start_scheduler":
            return _success(
                {
                    "task": "start_scheduler",
                    "scheduler": scheduler_manager.start(),
                }
            )

        if task_name == "stop_scheduler":
            return _success(
                {
                    "task": "stop_scheduler",
                    "scheduler": scheduler_manager.stop(),
                }
            )

        if task_name == "run_scheduler_job":
            job_name = payload.get("job")
            if not job_name:
                return _error(
                    "invalid_input",
                    "Missing 'job' in payload.",
                    details={
                        "supported_jobs": [
                            "crypto_ingest",
                            "stock_ingest",
                            "processing",
                            "correlation",
                            "forecast",
                            "history_backfill",
                            "anomaly_retrain",
                            "forecast_retrain",
                        ]
                    },
                )
            try:
                result = scheduler_manager.run_job_now(str(job_name))
            except ValueError as exc:
                return _error("invalid_input", str(exc))
            if result.get("status") == "failed":
                return _error(
                    "scheduler_job_failed",
                    f"Scheduler job '{job_name}' failed.",
                    status_code=500,
                    details={"result": result},
                )
            return _success(
                {
                    "task": "run_scheduler_job",
                    "result": result,
                }
            )

        if task_name == "run_ingestion_cycle":
            result = scheduler_manager.run_ingestion_cycle()
            return _success(
                {
                    "task": "run_ingestion_cycle",
                    "result": result,
                }
            )

        if task_name == "run_full_cycle":
            ingestion = scheduler_manager.run_ingestion_cycle()
            processing = scheduler_manager.run_job_now("processing")
            correlation = scheduler_manager.run_job_now("correlation")
            forecast = scheduler_manager.run_job_now("forecast")
            return _success(
                {
                    "task": "run_full_cycle",
                    "result": {
                        "ingestion": ingestion,
                        "processing": processing,
                        "correlation": correlation,
                        "forecast": forecast,
                    },
                }
            )

        if task_name == "run_history_backfill":
            requested_days = payload.get("days", 1460)
            try:
                days = int(requested_days)
            except (TypeError, ValueError):
                return _error("invalid_input", "days must be an integer.")
            if days < 30 or days > 3650:
                return _error("invalid_input", "days must be between 30 and 3650.")
            result = scheduler_manager.run_history_backfill_job(days=days)
            if result.get("status") == "failed":
                return _error(
                    "history_backfill_failed",
                    "Historical backfill failed.",
                    status_code=500,
                    details={"result": result},
                )
            return _success(
                {
                    "task": "run_history_backfill",
                    "result": result,
                }
            )

        if task_name == "seed_dummy_db":
            data_payload = build_data_payload()
            forecast_payload = build_forecast_payload()

            market_saved = [
                save_market_data(
                    {
                        "symbol": item["symbol"],
                        "name": item["name"],
                        "source": "dummy",
                        "price": item["price"],
                        "change_24h": item["change_24h"],
                    }
                )
                for item in data_payload["items"]
            ]
            forecast_saved = [
                save_forecast(
                    {
                        "model": row["model"],
                        "target_symbol": row["target"],
                        "horizon": row["horizon"],
                        "source": "dummy",
                        "predicted_value": row["value"],
                        "confidence": row["confidence"],
                    }
                )
                for row in forecast_payload["predictions"]
            ]

            return _success(
                {
                    "task": "seed_dummy_db",
                    "saved": {
                        "market_data": len(market_saved),
                        "forecasts": len(forecast_saved),
                    },
                }
            )

        if task_name == "ingest_live_data":
            timeout = max(1, settings.request_timeout_seconds)
            crypto_result = fetch_crypto_data(
                api_key=settings.crypto_api_key,
                symbols=settings.ingestion_crypto_symbols,
                timeout_seconds=timeout,
                base_url=settings.crypto_api_base_url,
            )
            stock_result = fetch_stock_data(
                api_key=settings.stock_api_key,
                tickers=settings.ingestion_stock_tickers,
                timeout_seconds=timeout,
                base_url=settings.stock_api_base_url,
            )

            fetched_records = crypto_result["records"] + stock_result["records"]
            fetch_errors = crypto_result["errors"] + stock_result["errors"]
            persisted = 0
            persist_errors: list[dict] = []

            for record in fetched_records:
                try:
                    save_market_data(
                        {
                            "symbol": record["symbol"],
                            "name": record["name"],
                            "source": record["provider"],
                            "price": record["value"],
                            "change_24h": record["change_24h"],
                            "volume_24h": record["volume_24h"],
                            "market_cap": record["market_cap"],
                        }
                    )
                    persisted += 1
                except (ValueError, KeyError) as exc:
                    persist_errors.append(
                        {
                            "provider": record.get("provider"),
                            "symbol": record.get("symbol"),
                            "message": f"Persistence failed: {exc}",
                        }
                    )

            return _success(
                {
                    "task": "ingest_live_data",
                    "curated_scope": {
                        "crypto_symbols": list(settings.ingestion_crypto_symbols),
                        "stock_tickers": list(settings.ingestion_stock_tickers),
                    },
                    "fetched_records": len(fetched_records),
                    "persisted_records": persisted,
                    "fetch_errors": fetch_errors,
                    "persist_errors": persist_errors,
                }
            )

        if task_name == "run_processing_pipeline":
            raw_records = fetch_market_data(limit=5000)
            if not raw_records:
                return _error(
                    "invalid_state",
                    "No market data available. Run ingest_live_data first.",
                )

            cleaned = clean_and_engineer(raw_records)
            anomalies = detect_anomalies(cleaned)
            forecasts = generate_forecasts(cleaned)

            saved_cleaned = save_processed_data(cleaned)
            saved_anomalies = save_anomaly_events(anomalies)
            saved_forecasts = save_forecast_outputs(forecasts)

            if forecasts:
                fallback_rows = [
                    save_forecast(
                        {
                            "model": row["model"],
                            "target_symbol": row["symbol"],
                            "horizon": f"t+{row['horizon_step']}*{row['interval']}",
                            "source": "processing",
                            "predicted_value": row["predicted_value"],
                            "confidence": row["confidence"],
                        }
                    )
                    for row in forecasts
                ]
            else:
                fallback_rows = []

            return _success(
                {
                    "task": "run_processing_pipeline",
                    "input_records": len(raw_records),
                    "cleaned_records": len(saved_cleaned),
                    "anomaly_records": len(saved_anomalies),
                    "forecast_records": len(saved_forecasts),
                    "forecast_rows_legacy": len(fallback_rows),
                }
            )

        return _error(
            "invalid_input",
            "Unsupported task.",
            details={"supported_tasks": SUPPORTED_TASKS},
        )
    except ValueError as exc:
        return _error("invalid_input", str(exc))
    except Exception as exc:
        logger.exception("Failed to run ops task")
        return _error(
            "operation_failed",
            "Failed to execute requested task.",
            status_code=500,
            details={"reason": str(exc)},
        )
