from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import gc
from threading import Lock
from time import perf_counter, sleep
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler

from ..api.websocket import (
    emit_anomaly_event,
    emit_new_data_event,
    emit_system_status_event,
)
from ..core.config import get_settings
from ..core.utils import get_logger
from ..database.repository import (
    fetch_freshness_status,
    fetch_market_data,
    fetch_market_data_rolling,
    fetch_market_data_for_forecast_training,
    fetch_scheduler_job_logs,
    fetch_training_dataset,
    save_anomaly_events,
    save_correlation_metrics,
    save_forecast_outputs,
    save_market_data,
    save_processed_data,
    save_scheduler_job_log,
    upsert_market_data,
    upsert_freshness_status,
)
from ..services.ingestion.crypto_history_service import fetch_crypto_history
from ..services.ingestion.crypto_service import fetch_crypto_data
from ..services.ingestion.stock_history_service import fetch_stock_history
from ..services.ingestion.stock_service import fetch_stock_data
from ..services.processing.anomaly import detect_anomalies, retrain_anomaly_models
from ..services.processing.cleaner import CleanerConfig, clean_and_engineer
from ..services.processing.correlation import CorrelationConfig, compute_correlation_metrics
from ..services.processing.forecast import (
    ForecastConfig,
    generate_forecasts,
    retrain_forecast_models,
    summarize_forecast_diagnostics,
)
from ..services.processing.model_registry import get_registry_snapshot, initialize_model_registry


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class SchedulerManager:
    def __init__(self) -> None:
        self._logger = get_logger("backend.scheduler")
        self._scheduler = self._build_scheduler()
        self._socketio = None
        self._lock_map = {
            "crypto_ingest": Lock(),
            "stock_ingest": Lock(),
            "history_backfill": Lock(),
            "processing": Lock(),
            "correlation": Lock(),
            "forecast": Lock(),
            "anomaly_retrain": Lock(),
            "forecast_retrain": Lock(),
        }
        self._running = False

    @staticmethod
    def _build_scheduler() -> BackgroundScheduler:
        return BackgroundScheduler(timezone="UTC", job_defaults={"max_instances": 1, "coalesce": True})

    def set_socketio(self, socketio) -> None:
        self._socketio = socketio

    def start(self) -> dict:
        if self._running:
            return {"running": True, "message": "Scheduler already running."}

        self._scheduler = self._build_scheduler()
        settings = get_settings()
        initialize_model_registry(settings)
        now = _utc_now()
        self._scheduler.add_job(
            self.run_crypto_job,
            trigger="interval",
            seconds=max(30, settings.scheduler_ingest_interval_seconds),
            id="crypto_ingest",
            replace_existing=True,
            next_run_time=now,
        )
        self._scheduler.add_job(
            self.run_stock_job,
            trigger="interval",
            seconds=max(30, settings.scheduler_ingest_interval_seconds),
            id="stock_ingest",
            replace_existing=True,
            next_run_time=now + timedelta(seconds=20),
        )
        self._scheduler.add_job(
            self.run_processing_job,
            trigger="interval",
            seconds=max(30, settings.scheduler_processing_interval_seconds),
            id="processing",
            replace_existing=True,
            next_run_time=now + timedelta(seconds=45),
        )
        self._scheduler.add_job(
            self.run_correlation_job,
            trigger="interval",
            seconds=max(300, settings.scheduler_correlation_interval_seconds),
            id="correlation",
            replace_existing=True,
            next_run_time=now + timedelta(seconds=60),
        )
        self._scheduler.add_job(
            self.run_forecast_job,
            trigger="interval",
            seconds=max(300, settings.scheduler_forecast_interval_seconds),
            id="forecast",
            replace_existing=True,
            next_run_time=now + timedelta(seconds=75),
        )
        self._scheduler.add_job(
            self.run_anomaly_retrain_job,
            trigger="interval",
            seconds=max(300, settings.scheduler_anomaly_retrain_interval_seconds),
            id="anomaly_retrain",
            replace_existing=True,
            next_run_time=now + timedelta(seconds=105),
        )
        self._scheduler.add_job(
            self.run_forecast_retrain_job,
            trigger="interval",
            seconds=max(600, settings.scheduler_forecast_retrain_interval_seconds),
            id="forecast_retrain",
            replace_existing=True,
            next_run_time=now + timedelta(seconds=135),
        )
        self._scheduler.start()
        self._running = True
        self._emit("scheduler_status", {"running": True, "timestamp": _utc_now().isoformat()})
        emit_system_status_event(
            {
                "scheduler": {
                    "running": True,
                    "event": "scheduler_started",
                    "timestamp": _utc_now().isoformat(),
                }
            },
            force=True,
        )
        return {"running": True, "message": "Scheduler started."}

    def stop(self) -> dict:
        if not self._running:
            return {"running": False, "message": "Scheduler already stopped."}
        self._scheduler.shutdown(wait=False)
        self._running = False
        self._emit("scheduler_status", {"running": False, "timestamp": _utc_now().isoformat()})
        emit_system_status_event(
            {
                "scheduler": {
                    "running": False,
                    "event": "scheduler_stopped",
                    "timestamp": _utc_now().isoformat(),
                }
            },
            force=True,
        )
        return {"running": False, "message": "Scheduler stopped."}

    def is_running(self) -> bool:
        return self._running

    def run_job_now(self, job_name: str) -> dict:
        job_map: dict[str, Callable[[], dict]] = {
            "crypto_ingest": self.run_crypto_job,
            "stock_ingest": self.run_stock_job,
            "history_backfill": self.run_history_backfill_job,
            "processing": self.run_processing_job,
            "correlation": self.run_correlation_job,
            "forecast": self.run_forecast_job,
            "anomaly_retrain": self.run_anomaly_retrain_job,
            "forecast_retrain": self.run_forecast_retrain_job,
        }
        if job_name not in job_map:
            raise ValueError(f"Unsupported scheduler job: {job_name}")
        return job_map[job_name]()

    def status(self) -> dict:
        freshness_rows = fetch_freshness_status()
        stale_seconds = get_settings().scheduler_freshness_stale_seconds
        now = _utc_now()
        freshness: list[dict] = []
        for row in freshness_rows:
            current = dict(row)
            last_update = _parse_iso_datetime(current.get("last_update"))
            age_seconds = (now - last_update).total_seconds() if last_update else None
            is_stale_by_time = age_seconds is None or age_seconds > stale_seconds
            current["age_seconds"] = age_seconds
            current["is_stale"] = bool(current.get("is_stale")) or is_stale_by_time
            freshness.append(current)

        model_registry = get_registry_snapshot()
        anomaly_retrain_logs = fetch_scheduler_job_logs(limit=1, job_name="anomaly_retrain")
        forecast_retrain_logs = fetch_scheduler_job_logs(limit=1, job_name="forecast_retrain")
        scheduled_jobs = []
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time
            scheduled_jobs.append(
                {
                    "job_name": job.id,
                    "next_run_time": next_run.astimezone(timezone.utc).isoformat() if next_run else None,
                }
            )

        return {
            "running": self._running,
            "freshness": freshness,
            "recent_jobs": fetch_scheduler_job_logs(limit=20),
            "scheduled_jobs": scheduled_jobs,
            "model_registry": model_registry,
            "model_lifecycle": {
                "anomaly_retrain": anomaly_retrain_logs[0] if anomaly_retrain_logs else None,
                "forecast_retrain": forecast_retrain_logs[0] if forecast_retrain_logs else None,
                "registry_updated_at": model_registry.get("metadata_updated_at"),
            },
        }

    def _emit(self, event_name: str, payload: dict) -> None:
        if self._socketio is None:
            return
        self._socketio.emit(event_name, payload)

    def _with_retry(self, func: Callable[[], dict], retries: int = 2, base_delay: float = 0.75) -> dict:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return func()
            except Exception as exc:
                last_error = exc
                if attempt == retries:
                    break
                sleep(base_delay * (2**attempt))
        assert last_error is not None
        raise last_error

    def _run_guarded(self, job_name: str, runner: Callable[[], dict]) -> dict:
        lock = self._lock_map[job_name]
        if not lock.acquire(blocking=False):
            skipped = {"job_name": job_name, "status": "skipped", "details": {"reason": "already_running"}}
            save_scheduler_job_log(
                {
                    "job_name": job_name,
                    "status": "skipped",
                    "details": skipped["details"],
                    "started_at": _utc_now(),
                    "finished_at": _utc_now(),
                    "duration_ms": 0.0,
                }
            )
            self._emit("scheduler_job", skipped)
            emit_system_status_event(
                {
                    "scheduler": {
                        "running": self._running,
                        "last_job": skipped,
                    }
                },
                force=True,
            )
            return skipped

        started = _utc_now()
        timer = perf_counter()
        status = "failed"
        details: dict = {"error": "job_execution_incomplete"}
        return_payload = {"job_name": job_name, "status": status, "details": details}
        try:
            details = self._with_retry(runner)
            status = "success"
            return_payload = {"job_name": job_name, "status": status, "details": details}
        except Exception as exc:
            status = "failed"
            details = {"error": str(exc)}
            self._logger.exception("Scheduler job failed: %s", job_name)
            return_payload = {"job_name": job_name, "status": status, "details": details}
        finally:
            finished = _utc_now()
            duration_ms = (perf_counter() - timer) * 1000
            try:
                try:
                    save_scheduler_job_log(
                        {
                            "job_name": job_name,
                            "status": status,
                            "details": details,
                            "started_at": started,
                            "finished_at": finished,
                            "duration_ms": duration_ms,
                        }
                    )
                except Exception:
                    self._logger.exception("Failed to persist scheduler job log: %s", job_name)
                try:
                    self._emit(
                        "scheduler_job",
                        {
                            "job_name": job_name,
                            "status": status,
                            "details": details,
                            "started_at": started.isoformat(),
                            "finished_at": finished.isoformat(),
                            "duration_ms": duration_ms,
                        },
                    )
                except Exception:
                    self._logger.exception("Failed to emit scheduler job event: %s", job_name)
                try:
                    emit_system_status_event(
                        {
                            "scheduler": {
                                "running": self._running,
                                "last_job": {
                                    "job_name": job_name,
                                    "status": status,
                                    "started_at": started.isoformat(),
                                    "finished_at": finished.isoformat(),
                                    "duration_ms": duration_ms,
                                },
                            }
                        },
                        force=True,
                    )
                except Exception:
                    self._logger.exception("Failed to emit scheduler system status event: %s", job_name)
            finally:
                lock.release()
        return return_payload

    def _update_freshness(self, source: str, success: bool, message: str = "") -> None:
        now = _utc_now().isoformat()
        freshness = {
            "last_update": now,
            "is_stale": not success,
            "message": message,
        }
        if not success:
            freshness["message"] = message or "source update failed"
        upsert_freshness_status(source, freshness)

    def run_crypto_job(self) -> dict:
        def job() -> dict:
            settings = get_settings()
            result = fetch_crypto_data(
                api_key=settings.crypto_api_key,
                symbols=settings.ingestion_crypto_symbols,
                timeout_seconds=settings.request_timeout_seconds,
                base_url=settings.crypto_api_base_url,
            )
            persisted = 0
            persisted_records: list[dict] = []
            for record in result["records"]:
                try:
                    save_market_data(
                        {
                            "symbol": record["symbol"],
                            "name": record["name"],
                            "source": "crypto",
                            "price": record["value"],
                            "change_24h": record.get("change_24h"),
                            "volume_24h": record.get("volume_24h"),
                            "market_cap": record.get("market_cap"),
                            "captured_at": record.get("captured_at"),
                        }
                    )
                    persisted += 1
                    persisted_records.append(record)
                except ValueError as exc:
                    result["errors"].append(
                        {
                            "provider": "persistence",
                            "symbol": record.get("symbol"),
                            "message": str(exc),
                        }
                    )
            self._update_freshness("crypto", persisted > 0, f"errors={len(result['errors'])}")
            emit_new_data_event(
                persisted_records,
                source="crypto",
                freshness=fetch_freshness_status(),
            )
            return {
                "fetched": len(result["records"]),
                "persisted": persisted,
                "errors": result["errors"],
            }

        return self._run_guarded("crypto_ingest", job)

    def run_stock_job(self) -> dict:
        def job() -> dict:
            settings = get_settings()
            result = fetch_stock_data(
                api_key=settings.stock_api_key,
                tickers=settings.ingestion_stock_tickers,
                timeout_seconds=settings.request_timeout_seconds,
                base_url=settings.stock_api_base_url,
            )
            persisted = 0
            persisted_records: list[dict] = []
            for record in result["records"]:
                try:
                    upsert_market_data(
                        {
                            "symbol": record["symbol"],
                            "name": record["name"],
                            "source": "stock",
                            "price": record["value"],
                            "change_24h": record.get("change_24h"),
                            "volume_24h": record.get("volume_24h"),
                            "market_cap": record.get("market_cap"),
                            "captured_at": record.get("captured_at"),
                        }
                    )
                    persisted += 1
                    persisted_records.append(record)
                except ValueError as exc:
                    result["errors"].append(
                        {
                            "provider": "persistence",
                            "symbol": record.get("symbol"),
                            "message": str(exc),
                        }
                    )
            self._update_freshness("stock", persisted > 0, f"errors={len(result['errors'])}")
            emit_new_data_event(
                persisted_records,
                source="stock",
                freshness=fetch_freshness_status(),
            )
            return {
                "fetched": len(result["records"]),
                "persisted": persisted,
                "errors": result["errors"],
            }

        return self._run_guarded("stock_ingest", job)

    def run_processing_job(self) -> dict:
        def job() -> dict:
            raw_records = fetch_market_data(limit=1000)
            if not raw_records:
                return {
                    "input_records": 0,
                    "cleaned_records": 0,
                    "anomaly_records": 0,
                    "warning": "no_market_data_available",
                }
            cleaned = clean_and_engineer(raw_records)
            anomalies = detect_anomalies(cleaned)
            saved_cleaned = save_processed_data(cleaned)
            del cleaned
            saved_anomalies = save_anomaly_events(anomalies)
            emit_anomaly_event(anomalies, source="processing")
            return {
                "input_records": len(raw_records),
                "cleaned_records": len(saved_cleaned),
                "anomaly_records": len(saved_anomalies),
            }

        result = self._run_guarded("processing", job)
        gc.collect()
        return result

    def run_correlation_job(self) -> dict:
        def job() -> dict:
            settings = get_settings()
            training_rows = fetch_training_dataset(
                window_minutes=settings.anomaly_training_window_minutes,
                limit=5000,
                exclude_anomalies=False,
            )
            if not training_rows:
                return {
                    "input_records": 0,
                    "correlation_records": 0,
                    "shift_records": 0,
                    "warning": "no_training_data_available",
                }

            correlations = compute_correlation_metrics(
                training_rows,
                CorrelationConfig(interval="1h", rolling_window=24, min_points=24),
            )
            saved = save_correlation_metrics(correlations)
            shift_count = sum(1 for row in saved if row.get("shift_detected"))

            self._emit(
                "correlation_updates",
                {
                    "count": len(saved),
                    "shift_records": shift_count,
                    "metrics": saved[:20],
                },
            )
            emit_system_status_event(
                {
                    "analytics": {
                        "correlation_records": len(saved),
                        "correlation_shifts": shift_count,
                        "updated_at": _utc_now().isoformat(),
                    }
                }
            )
            return {
                "input_records": len(training_rows),
                "correlation_records": len(saved),
                "shift_records": shift_count,
            }

        result = self._run_guarded("correlation", job)
        gc.collect()
        return result

    def run_forecast_job(self) -> dict:
        def job() -> dict:
            settings = get_settings()
            training_rows = fetch_market_data_for_forecast_training(
                window_minutes=settings.forecast_training_window_minutes,
                limit_per_source=30000,
            )
            cleaned = clean_and_engineer(
                training_rows,
                CleanerConfig(interval="1d", rolling_window=7, spike_threshold_pct=25.0),
            )
            del training_rows
            forecasts = generate_forecasts(
                cleaned,
                ForecastConfig(
                    interval_minutes=1440,
                    horizon_steps=365,
                    min_training_points=90,
                    z_filter_threshold=3.0,
                ),
            )
            saved = save_forecast_outputs(forecasts)
            self._emit("forecast_updates", {"predictions": saved[:20]})
            emit_system_status_event(
                {
                    "analytics": {
                        "forecast_records": len(saved),
                        "updated_at": _utc_now().isoformat(),
                    }
                }
            )
            return {"forecast_records": len(saved)}

        result = self._run_guarded("forecast", job)
        gc.collect()
        return result

    def run_ingestion_cycle(self) -> dict:
        job_runners = [self.run_crypto_job, self.run_stock_job]
        job_results: list[dict] = []
        with ThreadPoolExecutor(max_workers=len(job_runners), thread_name_prefix="ingest-cycle") as executor:
            futures = [executor.submit(runner) for runner in job_runners]
            for future in as_completed(futures):
                job_results.append(future.result())
        emit_system_status_event(
            {
                "ingestion_cycle": {
                    "completed_at": _utc_now().isoformat(),
                    "ok": all(item.get("status") in {"success", "skipped"} for item in job_results),
                    "jobs": job_results,
                }
            },
            force=True,
        )
        return {
            "jobs": job_results,
            "ok": all(item.get("status") in {"success", "skipped"} for item in job_results),
        }

    def run_history_backfill_job(self, days: int = 1460) -> dict:
        def job() -> dict:
            settings = get_settings()
            safe_days = max(30, min(int(days), 3650))
            years = max(1, min(10, round(safe_days / 365)))

            stock_history = fetch_stock_history(
                api_key=settings.stock_api_key,
                tickers=settings.ingestion_stock_tickers,
                period_years=years,
                timeout_seconds=max(10, settings.request_timeout_seconds * 2),
                base_url=settings.stock_api_base_url,
            )
            crypto_history = fetch_crypto_history(
                symbols=settings.ingestion_crypto_symbols,
                days=safe_days,
                timeout_seconds=max(10, settings.request_timeout_seconds * 2),
            )

            persisted = {"stock": 0, "crypto": 0}
            persist_errors: list[dict] = []

            for record in stock_history["records"]:
                try:
                    upsert_market_data(
                        {
                            "symbol": record["symbol"],
                            "name": record["name"],
                            "source": "stock",
                            "price": record["value"],
                            "change_24h": record.get("change_24h"),
                            "volume_24h": record.get("volume_24h"),
                            "market_cap": record.get("market_cap"),
                            "captured_at": record.get("captured_at"),
                        }
                    )
                    persisted["stock"] += 1
                except Exception as exc:  # pragma: no cover - defensive persistence handling
                    persist_errors.append(
                        {
                            "source": "stock",
                            "symbol": record.get("symbol"),
                            "message": str(exc),
                        }
                    )

            for record in crypto_history["records"]:
                try:
                    upsert_market_data(
                        {
                            "symbol": record["symbol"],
                            "name": record["name"],
                            "source": "crypto",
                            "price": record["value"],
                            "change_24h": record.get("change_24h"),
                            "volume_24h": record.get("volume_24h"),
                            "market_cap": record.get("market_cap"),
                            "captured_at": record.get("captured_at"),
                        }
                    )
                    persisted["crypto"] += 1
                except Exception as exc:  # pragma: no cover - defensive persistence handling
                    persist_errors.append(
                        {
                            "source": "crypto",
                            "symbol": record.get("symbol"),
                            "message": str(exc),
                        }
                    )

            self._update_freshness(
                "stock",
                persisted["stock"] > 0,
                f"history_backfill errors={len(stock_history['errors'])}",
            )
            self._update_freshness(
                "crypto",
                persisted["crypto"] > 0,
                f"history_backfill errors={len(crypto_history['errors'])}",
            )
            emit_system_status_event(
                {
                    "backfill": {
                        "days": safe_days,
                        "persisted": persisted,
                        "completed_at": _utc_now().isoformat(),
                    }
                },
                force=True,
            )

            return {
                "days": safe_days,
                "stock": {
                    "fetched": len(stock_history["records"]),
                    "persisted": persisted["stock"],
                    "errors": stock_history["errors"],
                },
                "crypto": {
                    "fetched": len(crypto_history["records"]),
                    "persisted": persisted["crypto"],
                    "errors": crypto_history["errors"],
                },
                "persist_errors": persist_errors,
            }

        return self._run_guarded("history_backfill", job)

    def run_anomaly_retrain_job(self) -> dict:
        def job() -> dict:
            settings = get_settings()
            dataset_source = "processed_rolling"
            training_rows = fetch_training_dataset(
                window_minutes=settings.anomaly_training_window_minutes,
                limit=2000,
                exclude_anomalies=False,
            )
            if not training_rows:
                dataset_source = "market_rolling_fallback"
                raw_rows = fetch_market_data_rolling(
                    window_minutes=settings.anomaly_training_window_minutes,
                    limit=2000,
                )
                training_rows = clean_and_engineer(raw_rows)
            result = retrain_anomaly_models(training_rows)
            snapshot = get_registry_snapshot()
            lifecycle_result = {
                **result,
                "dataset_records": len(training_rows),
                "dataset_source": dataset_source,
                "training_window_minutes": settings.anomaly_training_window_minutes,
                "registry_updated_at": snapshot.get("metadata_updated_at"),
            }
            self._emit(
                "model_updates",
                {
                    "model_type": "anomaly",
                    "result": lifecycle_result,
                    "registry": snapshot,
                },
            )
            emit_system_status_event(
                {
                    "model_updates": {
                        "model_type": "anomaly",
                        "result": lifecycle_result,
                    }
                },
                force=True,
            )
            return lifecycle_result

        result = self._run_guarded("anomaly_retrain", job)
        gc.collect()
        return result

    def run_forecast_retrain_job(self) -> dict:
        def job() -> dict:
            settings = get_settings()
            dataset_source = "market_training_2y_daily"
            raw_rows = fetch_market_data_for_forecast_training(
                window_minutes=settings.forecast_training_window_minutes,
                limit_per_source=30000,
            )
            cleaned_rows = clean_and_engineer(
                raw_rows,
                CleanerConfig(interval="1d", rolling_window=7, spike_threshold_pct=25.0),
            )
            training_rows = [row for row in cleaned_rows if abs(float(row.get("z_score") or 0.0)) < 3.0]
            forecast_cfg = ForecastConfig(
                interval_minutes=1440,
                horizon_steps=365,
                min_training_points=90,
                z_filter_threshold=3.0,
            )
            result = retrain_forecast_models(
                training_rows,
                forecast_cfg,
            )
            diagnostics = summarize_forecast_diagnostics(
                training_rows,
                forecast_cfg,
                holdout_steps=30,
            )
            snapshot = get_registry_snapshot()
            lifecycle_result = {
                **result,
                "dataset_records": len(training_rows),
                "dataset_source": dataset_source,
                "training_window_minutes": settings.forecast_training_window_minutes,
                "diagnostics": diagnostics,
                "registry_updated_at": snapshot.get("metadata_updated_at"),
            }
            self._emit(
                "model_updates",
                {
                    "model_type": "forecast",
                    "result": lifecycle_result,
                    "registry": snapshot,
                },
            )
            emit_system_status_event(
                {
                    "model_updates": {
                        "model_type": "forecast",
                        "result": lifecycle_result,
                    }
                },
                force=True,
            )
            return lifecycle_result

        result = self._run_guarded("forecast_retrain", job)
        gc.collect()
        return result


scheduler_manager = SchedulerManager()
