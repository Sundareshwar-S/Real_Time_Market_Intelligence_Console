# DEP Mini Project Detailed Technical Report

Date: 2026-04-20
Project: Real-Time Market Intelligence Console

## Index

- [1) What This Project Is](#1-what-this-project-is)
- [2) Core Goal of the Project](#2-core-goal-of-the-project)
- [3) End-to-End System Flow](#3-end-to-end-system-flow)
- [4) Backend Architecture Overview](#4-backend-architecture-overview)
- [5) API Surface and Behavior](#5-api-surface-and-behavior)
- [6) Standard Response Envelope](#6-standard-response-envelope)
- [7) Scheduler Design and Jobs](#7-scheduler-design-and-jobs)
- [8) Data Ingestion Implementation](#8-data-ingestion-implementation)
- [9) Persistence and MongoDB Model](#9-persistence-and-mongodb-model)
- [10) Processing Pipeline Internals](#10-processing-pipeline-internals)
- [11) Mathematical Implementation: Feature Engineering](#11-mathematical-implementation-feature-engineering)
- [12) Mathematical Implementation: Anomaly Detection](#12-mathematical-implementation-anomaly-detection)
- [13) Scope Update: Weather and Correlation Removed](#13-scope-update-weather-and-correlation-removed)
- [14) Mathematical Implementation: Forecasting](#14-mathematical-implementation-forecasting)
- [15) Forecast Diagnostics and Accuracy Controls](#15-forecast-diagnostics-and-accuracy-controls)
- [16) Model Registry and Artifact Lifecycle](#16-model-registry-and-artifact-lifecycle)
- [17) WebSocket and Real-Time Event System](#17-websocket-and-real-time-event-system)
- [18) Frontend Architecture and State Model](#18-frontend-architecture-and-state-model)
- [19) Frontend Pages and UX Intent](#19-frontend-pages-and-ux-intent)
- [20) Validation, Error Handling, and Safety](#20-validation-error-handling-and-safety)
- [21) Performance Characteristics](#21-performance-characteristics)
- [22) Security and Configuration](#22-security-and-configuration)
- [23) Known Gaps and Limitations](#23-known-gaps-and-limitations)
- [24) How to Run the Project](#24-how-to-run-the-project)
- [25) How the Mathematics Works in Practice](#25-how-the-mathematics-works-in-practice)
- [26) Why This Implementation Is Strong](#26-why-this-implementation-is-strong)
- [27) Recommended Next Improvements](#27-recommended-next-improvements)
- [28) Final Summary](#28-final-summary)

## 1) What This Project Is

This project is a full-stack real-time analytics platform.
It continuously ingests market data, processes it, detects anomalies, generates forecasts, and streams updates to a live dashboard.
The backend is built with Flask + Socket.IO + MongoDB.
The frontend is built with React + Vite + Recharts.
The system also includes persisted machine learning model artifacts and a scheduler-based operations engine.

In simple terms:
This project is a live market intelligence pipeline, not just a static dashboard.

## 2) Core Goal of the Project

The goal is to turn fragmented market feeds into actionable live intelligence.

Primary goals:
- Ingest crypto and stock data continuously.
- Normalize heterogeneous provider payloads into a unified internal schema.
- Engineer robust time-series features from noisy streams.
- Detect anomalies in near real time.
- Generate forecast trajectories with confidence intervals.
- Maintain a focused analytics scope around ingestion, anomaly detection, and forecasting.
- Expose stable APIs and WebSocket events for a responsive frontend.
- Persist all major outputs for diagnostics and historical analysis.

Secondary goals:
- Support operator actions via control endpoints.
- Keep model lifecycle state visible and auditable.
- Degrade gracefully when providers fail.

## 3) End-to-End System Flow

The runtime data flow is:

1. Scheduler triggers ingestion jobs.
2. Ingestion services fetch raw provider data.
3. Repository layer validates and persists raw market rows.
4. Processing job loads recent market rows.
5. Cleaner resamples and engineers features.
6. Anomaly detector marks outliers and severity.
7. Forecast module produces multi-step predictions.
8. Results are stored in derived collections.
9. WebSocket emits event updates to connected clients.
10. Frontend store merges REST bootstrap and stream events.
11. Pages render KPIs, charts, and diagnostics.

## 4) Backend Architecture Overview

The backend entrypoint initializes:
- Flask app.
- CORS policy.
- Socket.IO transport.
- Mongo DB initialization.
- Model registry initialization.
- API blueprint registration.
- Scheduler manager wiring.

Registered blueprints include:
- /api/data
- /api/latest
- /api/series/market
- /api/forecast
- /api/forecast/diagnostics
- /api/anomalies
- /api/start
- /api/stop
- /api/run-task
- /api/websocket/status

Design principle:
Route handlers are thin, repository/services are thick.
This keeps request parsing and business logic separated.

## 5) API Surface and Behavior

### Data APIs
- GET /api/data
	Returns paginated market rows.
	Supports filters: symbol, source, start_time, end_time, limit, offset.
	Includes optional global crypto market cap from CoinGecko.

- GET /api/latest
	Returns newest market row matching filters.

### Series API
- GET /api/series/market
	Returns bucketed market aggregate series for context all|crypto|stock.
	Buckets supported: 1h, 4h, 1d, 1w, 1m.

### Forecast APIs
- GET /api/forecast
	Returns persisted forecast output rows.
	Supports symbol, model, date range, pagination.

- GET /api/forecast/diagnostics
	Builds/returns holdout diagnostics and model metadata summary.
	Supports holdout_steps and mape_threshold controls.

### Anomaly API
- GET /api/anomalies
	Returns anomaly events with deduplication and severity summary.

### Operations APIs
- POST /api/start
	Activates stream and starts scheduler.

- POST /api/stop
	Deactivates stream and stops scheduler.

- POST /api/run-task
	Executes operator tasks such as validate_keys, run_full_cycle, run_scheduler_job, ingest_live_data, run_history_backfill, run_processing_pipeline.

### WebSocket Status API
- GET /api/websocket/status
	Returns stream + connection status and freshness metadata.

## 6) Standard Response Envelope

Success envelope structure:
- status = success
- data = payload
- meta = timestamp, source, no_data, optional filters/pagination/freshness

Error envelope structure:
- status = error
- error.code
- error.message
- optional error.details
- meta.timestamp

This consistency simplifies frontend parsing and operational debugging.

## 7) Scheduler Design and Jobs

Scheduler manager uses APScheduler with:
- max_instances=1
- coalesce=true
- UTC timezone

Core jobs:
- crypto_ingest
- stock_ingest
- processing
- forecast
- anomaly_retrain
- forecast_retrain
- history_backfill (manual)

Guarding and resilience:
- Per-job lock map prevents overlapping execution.
- Retry wrapper with exponential backoff for transient errors.
- Job logs persisted with status, duration, details.
- System-status events emitted after job execution.

Freshness handling:
- Every ingestion path updates source freshness rows.
- Stale status combines explicit flag and age-based threshold logic.

## 8) Data Ingestion Implementation

### Crypto live ingestion
- Provider: FreeCryptoAPI.
- Supplemental metrics: CoinGecko simple price endpoint.
- Global market cap: CoinGecko global endpoint.
- Value coercion and payload normalization done per symbol.

### Stock live ingestion
- Provider: Polygon previous aggregate endpoint.
- Market cap enrichment: Polygon reference tickers endpoint.
- Includes TTL cache for market caps to reduce repeated requests.

### Historical backfill
- Stocks: Polygon range endpoint (daily bars).
- Crypto: Binance klines endpoint (daily candles).
- Backfill persists upserted historical rows.

### Removed scope note
- Weather ingestion and correlation analytics were removed from the current project scope.
- The active report and architecture focus on crypto/stock ingestion, anomaly detection, and forecasting.

## 9) Persistence and MongoDB Model

Collections include:
- crypto
- stock
- processed_data
- anomaly_events
- forecast_outputs
- alerts
- scheduler_jobs
- freshness_status

Important repository behaviors:
- Strict numeric coercion for price/value fields.
- UTC ISO timestamp normalization.
- Source-aware collection routing.
- Upsert patterns for idempotent market insertion.
- Dedup aggregation pipeline for anomaly fetch.
- Sampling and scan-window controls for series endpoints.

Index strategy includes:
- symbol + captured_at for market collections.
- symbol + timestamp for processed/anomaly data.
- symbol + generated_at for forecast outputs.
- unique index on freshness source.

## 10) Processing Pipeline Internals

The processing chain is composed of:
- Cleaner
- Anomaly detector
- Forecast generator

### Cleaner responsibilities
- Parse timestamps to UTC.
- Convert symbols to uppercase.
- Convert value/price to numeric.
- Drop invalid or non-positive records.
- Resample to configured interval.
- Fill short gaps via forward fill + interpolation.
- Remove spikes above threshold and re-fill.
- Compute engineered statistics.

Output features:
- value
- pct_change
- rolling_mean
- rolling_std
- z_score

### 10.1 Detailed Preprocessing Steps (Code-Accurate)

This subsection explains exactly how preprocessing is done in the backend before anomaly detection and forecasting.

Processing entrypoint sequence:
1. Fetch recent raw market rows from MongoDB.
2. Call clean_and_engineer(raw_rows, CleanerConfig).
3. Persist cleaned feature rows to processed_data.
4. Pass cleaned rows to anomaly and forecast services.

The cleaner runs per symbol group, not on all symbols mixed together.

### 10.2 Input Normalization Stage

For each incoming row, the cleaner performs strict coercion:
- timestamp parsed to UTC datetime.
- symbol converted to uppercase string.
- source converted to string.
- value resolved from price (or value fallback) and converted to numeric.

Rows are dropped immediately if:
- timestamp cannot be parsed,
- symbol is missing,
- value is non-numeric,
- value <= 0.

Why this matters:
- Eliminates invalid records before resampling.
- Prevents downstream math errors from bad numeric values.

### 10.3 Time Alignment and Resampling Stage

For each symbol:
- Records are sorted by timestamp.
- Data is reindexed by timestamp.
- Resampling is applied with mean aggregation at configured interval.

Default cleaner configuration:
- interval = 1 minute
- rolling_window = 5
- spike_threshold_pct = 5.0

Forecast pipeline override configuration:
- interval = 1 day
- rolling_window = 7
- spike_threshold_pct = 25.0

Why two profiles are used:
- Minute profile is better for near-real-time anomaly sensitivity.
- Daily profile is better for medium/long-horizon forecast stability.

### 10.4 Missing Value Repair Stage

After resampling, value gaps are repaired in two passes:
1. forward fill with limit 5
2. interpolation with limit 5 and bidirectional direction

Rows still missing value after repair are dropped.

Effect:
- Short outages are smoothed.
- Long or severe gaps are not fabricated aggressively.

### 10.5 Spike Filtering Stage

Cleaner computes short-term percentage change:
$$
pct\_change_t = \left(\frac{x_t - x_{t-1}}{x_{t-1}}\right)\times 100
$$

Spike rule:
$$
|pct\_change_t| > spike\_threshold\_pct
$$

If rule is true:
- value at that point is temporarily masked to NaN,
- fill + interpolation are applied again,
- unresolved points are dropped.

Purpose:
- Remove one-off feed glitches before feature generation.

### 10.6 Feature Engineering Stage

After cleaned values are stable, features are generated:

1) Percentage change:
$$
pct\_change_t = \left(\frac{x_t - x_{t-1}}{x_{t-1}}\right)\times 100
$$

2) Rolling mean (window w):
$$
\mu_t = \frac{1}{w}\sum_{i=t-w+1}^{t} x_i
$$

3) Rolling standard deviation (window w):
$$
\sigma_t = \sqrt{\frac{1}{w}\sum_{i=t-w+1}^{t}(x_i-\mu_t)^2}
$$

4) Z-score:
$$
z_t = \frac{x_t-\mu_t}{\sigma_t}
$$

Implementation safeguards:
- rolling std NaN is filled as 0.
- zero std is treated safely by replacing denominator with NaN and filling z_score with 0.
- this avoids division-by-zero crashes.

### 10.7 Edge Cases and Failure-Safe Behavior

Cleaner returns empty output early when:
- raw_rows is empty,
- constructed DataFrame is empty,
- all rows are dropped during validation,
- all rows are dropped after repair or filtering.

Additional resilience details:
- each symbol is processed independently, so a bad symbol does not corrupt others.
- source field is preserved per symbol group.
- final normalized output is sorted by (symbol, timestamp).

### 10.8 Preprocessing-to-Model Interface

The cleaned output schema is exactly what downstream models expect:
- timestamp
- symbol
- source
- value
- pct_change
- rolling_mean
- rolling_std
- z_score

Anomaly service consumes value + pct_change + z_score for Isolation Forest.
Forecast service consumes cleaned value series (and z_score for filtering before training).

This is why preprocessing is the most critical quality gate in the full ML pipeline.

## 11) Mathematical Implementation: Feature Engineering

### 11.1 Percentage Change

Implemented as:
$pct\_change_t = \frac{x_t - x_{t-1}}{x_{t-1}} \times 100$

Use:
- Captures short-run momentum.
- Drives anomaly type classification (spike/drop).

### 11.2 Rolling Mean

Implemented as moving average over window $w$:
$\mu_t = \frac{1}{w}\sum_{i=t-w+1}^{t} x_i$

Use:
- Local trend baseline.
- Stabilizes noisy minute-level fluctuations.

### 11.3 Rolling Standard Deviation

Implemented as:
$\sigma_t = \sqrt{\frac{1}{w}\sum_{i=t-w+1}^{t}(x_i-\mu_t)^2}$

Use:
- Local volatility estimate.

### 11.4 Z-Score

Implemented as:
$z_t = \frac{x_t - \mu_t}{\sigma_t}$

Use:
- Rule-based outlier detection.
- Direct severity thresholding.

## 12) Mathematical Implementation: Anomaly Detection

The anomaly detector is hybrid:
- Statistical thresholding via z-score.
- Isolation Forest on multivariate features.

Feature vector used by model:
- value
- pct_change
- z_score

Isolation Forest details:
- sklearn IsolationForest.
- contamination constrained to [0.01, 0.5].
- random_state set for reproducibility.

Model behavior:
- Predicts -1 for anomaly, +1 for normal.
- decision_function converted to non-negative anomaly intensity.

Hybrid anomaly flag:
- is_anomaly = z_flag OR iso_flag.

Anomaly score:
- anomaly_score = max(abs(z_score), iso_score).

Severity mapping:
- z-trigger high if z >= threshold+1.
- z-trigger medium if z >= threshold.
- iso-trigger severity based on quantile cutoffs from iso_score distribution.

Type mapping logic:
- positive pct_change => spike
- negative pct_change => drop
- otherwise => volatility

Detailed implementation in this project:
- Model family: per-symbol IsolationForest from scikit-learn.
- Feature columns: value, pct_change, z_score.
- Minimum training rows per symbol:
	max(anomaly_min_training_points, rolling_window).
- Contamination is clamped into [0.01, 0.5] before fitting.
- If a persisted symbol model exists, it is loaded and reused.
- If inference fails on a persisted artifact, the model is retrained and overwritten.

Mathematical view of Isolation Forest:
- Isolation trees isolate anomalies using shorter path lengths.
- For a sample x, each tree gives path length h_t(x).
- Average path length is E[h(x)] over trees.
- Normalizer for sample size n is:
	c(n) = 2H(n-1) - 2(n-1)/n, where H is harmonic number.
- Canonical anomaly score is:
	s(x, n) = 2^{-E[h(x)] / c(n)}.

How this code converts model output to usable anomaly intensity:
- sklearn decision_function output is converted as:
	iso_score = max(0, -decision_function).
- Final anomaly score is:
	anomaly_score = max(|z_score|, iso_score).

Severity math used in implementation:
- z-score path:
	high if |z| >= z_threshold + 1,
	medium if |z| >= z_threshold,
	else low.
- Isolation path:
	high if iso_score >= q90,
	medium if iso_score >= q70,
	else low,
	where q90 and q70 are per-symbol quantiles from currently flagged iso samples.

## 13) Scope Update: Weather and Correlation Removed

This report version reflects your current project scope.

Removed modules:
- Weather ingestion and weather analytics.
- Correlation API, correlation processing, and correlation metrics reporting.

Current active quantitative scope:
- Feature engineering (rolling statistics + z-score).
- Hybrid anomaly detection.
- Forecast generation and forecast diagnostics.

Why this update is important:
- Prevents mismatch between documentation and implementation.
- Keeps architecture and mathematical description aligned with the shipped project.

Artifact note from current model directory:
- Legacy weather artifacts are still present in ml_models.
- They are historical artifacts and not part of the active runtime scope after your cleanup.

## 14) Mathematical Implementation: Forecasting

Forecasting is multi-path to maximize reliability.

### Primary path: Prophet

Model settings:
- interval_width 0.95
- weekly seasonality enabled
- yearly seasonality enabled
- daily seasonality disabled
- changepoint_prior_scale 0.15

Training frame conversion:
- timestamp -> ds
- value -> y
- timezone normalized and made Prophet-compatible.

Predictions:
- Multi-step horizon outputs.
- yhat, yhat_lower, yhat_upper used as value and interval bounds.

### Non-Prophet fallback paths

1) Return regression model (RandomForestRegressor)
- Trains on log-return features.
- Uses lagged returns, rolling means/std, seasonal terms.

2) Seasonal price regression model (RandomForestRegressor)
- Trains on lagged prices and cyclical calendar features.

3) Rolling fallback model
- Drifted rolling-mean projection with damping.
- Interval from recent rolling std.

Fallback selection:
- Holdout evaluation compares candidates.
- Chooses lower MAPE candidate when possible.

### Confidence and interval behavior

Return-regression path:
- Uses residual volatility and horizon scaling.
- Constructs lower/upper scenarios via bounded return uncertainty.

Rolling fallback path:
- Uses $value \pm 1.96 \cdot rolling\_std$.

Detailed implementation in this project:
- The system attempts Prophet first when backend dependencies are available.
- If Prophet is unavailable or fails, it falls back to regression-based models.
- If regression paths fail, it uses a deterministic rolling fallback model.
- Models are persisted per symbol through the model registry.

14.1 Prophet path math

Prophet conceptually decomposes a series as:
$$
y(t) = g(t) + s(t) + h(t) + \epsilon_t
$$
where g(t) is trend, s(t) seasonal terms, h(t) optional event effects, and \epsilon_t noise.

In this code configuration:
- weekly and yearly seasonality are enabled,
- daily seasonality is disabled,
- interval_width = 0.95.

Confidence calculation used in output records:
$$
confidence = \mathrm{clip}\left(1 - \frac{yhat\_upper - yhat\_lower}{\max(|yhat|, 1)}, 0, 0.99\right)
$$

14.2 Return-regression fallback math

Step 1: transform prices to log-returns:
$$
r_t = \log\left(\frac{p_t}{p_{t-1}}\right)
$$

Step 2: train RandomForestRegressor on lag, rolling, and seasonal features.

Step 3: infer bounded return:
$$
\hat{r}^{raw}_t = RF(x_t)
$$
$$
\hat{r}_t = 0.65\hat{r}^{raw}_t + 0.35\overline{r}_{recent}
$$
then clamp \hat{r}_t into a volatility-based return limit.

Step 4: map return back to price:
$$
\hat{p}_t = p_{t-1} \cdot e^{\hat{r}_t}
$$

Step 5: interval construction with horizon-scaled uncertainty:
$$
u_t = \max(\sigma_{residual}, 0.75\sigma_{recent})\sqrt{t}
$$
$$
r_t^{low} = \hat{r}_t - 1.64u_t, \quad r_t^{high} = \hat{r}_t + 1.64u_t
$$
$$
p_t^{low} = p_{t-1}e^{r_t^{low}}, \quad p_t^{high} = p_{t-1}e^{r_t^{high}}
$$

14.3 Seasonal price-regression fallback math

- RandomForestRegressor is trained directly on price-level features:
	lag1, lag2, lag3, lag7, rolling_mean7, rolling_std7, day_of_week,
	seasonal_sin(day_of_year), seasonal_cos(day_of_year).
- Predicted value is clamped to non-negative output.
- Interval uses recent local volatility envelope:
$$
\hat{p}_t \pm 1.64\sigma_{recent}
$$

14.4 Rolling fallback deterministic model math

Let rolling mean be m, drift d, step k.
Drift is clamped into [-0.02, 0.02], with exponential damping 0.8^k.
$$
\hat{p}_{t+k} = m\left(1 + d\,k\,0.8^k\right)
$$

Interval:
$$
[\hat{p}_{t+k} - 1.96\sigma_{rolling},\; \hat{p}_{t+k} + 1.96\sigma_{rolling}]
$$

14.5 Runtime model selection logic

- If Prophet is ready and a valid Prophet artifact exists, use it.
- If current artifact is non-Prophet dict, attempt upgrade to Prophet.
- On failure, choose best fallback via holdout MAPE comparison.
- Persist selected model artifact for future inference.

## 15) Forecast Diagnostics and Accuracy Controls

Diagnostics endpoint computes symbol-level quality indicators:
- RMSE
- MAPE
- variance_ratio
- degenerate_path indicator
- backend used for evaluation

Threshold controls:
- holdout_steps: between 7 and 180.
- mape_threshold: >0 and <=100.

Summary outputs include:
- evaluated symbol count
- low-accuracy symbol list
- degenerate symbol list
- model registry metadata snapshot

Metrics math used:

RMSE:
$$
RMSE = \sqrt{\frac{1}{n}\sum_{i=1}^{n}(y_i - \hat{y}_i)^2}
$$

MAPE:
$$
MAPE = \frac{100}{n}\sum_{i=1}^{n}\left|\frac{y_i - \hat{y}_i}{\max(|y_i|, 10^{-9})}\right|
$$

Variance ratio:
$$
variance\_ratio = \frac{std(\hat{y})}{std(y)}
$$

Degenerate forecast detection:
- If forecast variation range is too small relative to signal scale,
  the path is marked degenerate_path = true.

## 16) Model Registry and Artifact Lifecycle

Model registry responsibilities:
- Load models at startup.
- Resolve artifact locations.
- Persist anomaly and forecast models.
- Persist metadata JSON with trained_at, format, model_type, training_points.

Artifact naming conventions:
- anomaly_iforest_SYMBOL.joblib
- forecast_prophet_SYMBOL.joblib

Supported formats:
- joblib primary.
- pickle fallback load compatibility.

Lifecycle endpoints/jobs:
- anomaly_retrain scheduler job.
- forecast_retrain scheduler job.
- registry snapshot exposed via scheduler status payload.

16.1 What ML models are currently used in your project

Active anomaly model family:
- IsolationForest per symbol.
- Current active symbols in artifacts:
	AAPL, BTC, ETH, MSFT, SOL, TSLA.

Active forecast model family:
- Multi-path engine with Prophet preferred and RandomForest/rolling fallback.
- Artifact file names are forecast_prophet_SYMBOL.joblib,
	but metadata model_type currently shows dict for active symbols,
	which indicates persisted non-Prophet model containers are in use now.

16.2 Artifact inventory from ml_models directory

Anomaly artifacts:
- anomaly_iforest_AAPL.joblib
- anomaly_iforest_BTC.joblib
- anomaly_iforest_ETH.joblib
- anomaly_iforest_MSFT.joblib
- anomaly_iforest_SOL.joblib
- anomaly_iforest_TSLA.joblib

Forecast artifacts:
- forecast_prophet_AAPL.joblib
- forecast_prophet_BTC.joblib
- forecast_prophet_ETH.joblib
- forecast_prophet_MSFT.joblib
- forecast_prophet_SOL.joblib
- forecast_prophet_TSLA.joblib

Legacy artifacts still present (not active scope):
- WTHR-LONDON
- WTHR-NEW YORK
- WTHR-TOKYO

16.3 Operational meaning

- Your deployed ML runtime currently uses persisted per-symbol anomaly models.
- Forecast runtime uses whichever persisted artifact path is valid,
	with automatic fallback and retraining logic for resilience.
- This design favors uptime and continuity over strict single-model purity.

## 17) WebSocket and Real-Time Event System

Event categories include:
- new_data
- anomaly_detected
- alert_triggered
- system_status
- stream_state
- scheduler_job
- scheduler_status

Compatibility events also handled:
- latest_data_points
- anomaly_events

Emission controls:
- Event throttle via per-event minimum interval.
- Payload signature hashing to avoid duplicate emissions.
- Stream active toggle controls periodic loop behavior.

Connection observability:
- Client heartbeat tracking.
- Connected client count.
- Last heartbeat timestamp.

## 18) Frontend Architecture and State Model

Frontend boot sequence:
- initializeRealtimeApp()
- bootstrapData() via REST
- connect socket and register handlers
- ensure pipeline is live

Global store state includes:
- context and timeRange
- market/anomalies/forecasts datasets
- chart series caches
- scheduler and freshness status
- connection diagnostics
- UI loading and errors

Important client behaviors:
- Context-aware source mapping (crypto vs stock aliases).
- Time-window query normalization.
- Dedup and merge logic by semantic keys.
- Bucketed series construction for chart density control.
- Auto-hydration of forecast data if absent.

## 19) Frontend Pages and UX Intent

Overview page:
- Global market pulse and key KPIs.
- Context switch and symbol selection.
- Stream health and freshness exposure.

Markets page:
- Asset explorer table.
- Context-filtered trend and volume insights.
- Category-specific chart rendering.

Anomalies page:
- Severity-focused anomaly monitoring.
- Liquidity vector visualization.
- Window-based anomaly bucketing.

Forecasts page:
- Forecast range chart.
- Model/accuracy diagnostics panel.
- Auto-refresh and generation retry flow.

Layout system:
- AppShell + TopBar + SideNav.
- Recharts-based reusable chart components.

## 20) Validation, Error Handling, and Safety

Input validation:
- limit/offset constraints.
- ISO datetime validation.
- symbol/source format regex validation.
- boolean parser safeguards.

Operational resilience:
- Network errors captured as structured messages.
- Retry for guarded scheduler jobs.
- Per-job locking to avoid concurrent collisions.
- Fallback models to avoid forecast downtime.

Data safety:
- Numeric coercion with strict failure paths.
- Non-finite checks for metrics and model inputs.
- NaN cleanup before training and inference.

## 21) Performance Characteristics

Performance-oriented choices:
- Mongo projections to limit read payload.
- Query limit ceilings to avoid unbounded scans.
- Batch sizes for cursor throughput.
- Dynamic scan window estimation for series APIs.
- In-memory caches for diagnostics and market-cap references.

Potential bottlenecks:
- High-frequency full-data rebootstrap on aggressive UI interactions.
- Large historical windows in forecast training.
- Forecast retraining cost if symbol universe grows substantially.

## 22) Security and Configuration

Configuration is environment-driven via Settings dataclass.
Sensitive keys loaded from environment:
- STOCK_API_KEY
- CRYPTO_API_KEY

Other operational settings:
- scheduler intervals
- timeout values
- CORS origin
- Socket.IO async mode
- Mongo connection details
- model directory paths

Current security posture notes:
- API-key handling is server-side.
- Input validation is present for all public query paths.
- No auth layer is currently implemented for control-plane endpoints.

## 23) Known Gaps and Limitations

- No authenticated role model for operation endpoints.
- Alert pipeline exists structurally but is not fully promoted as a first-class API route in current active blueprint set.
- No formal CI test suite coverage is currently enforced by discovered tests.
- Forecast confidence remains model-specific and heuristic in fallback modes.
- Forecast quality can still vary across symbols with sparse or irregular history.

## 24) How to Run the Project

Backend setup:
- Install dependencies from root and backend requirements files.
- Start backend with python backend/src/app.py.

Frontend setup:
- Install dependencies in frontend directory.
- Start Vite dev server with npm run dev.

Suggested operator boot flow:
1. Start backend.
2. Start frontend.
3. Use /api/start to activate stream + scheduler.
4. Optionally run /api/run-task with run_full_cycle for immediate data.

## 25) How the Mathematics Works in Practice

At runtime, each symbol stream goes through this quantitative loop:

1. Resample raw values to stable cadence.
2. Smooth and repair local missing values.
3. Compute rolling trend and volatility estimates.
4. Convert deviations into z-scores.
5. Apply hybrid anomaly model for robust outlier detection.
6. Build short/long horizon forecasts with best available model path.
7. Run diagnostics to monitor model accuracy and degeneration risk.
8. Persist outputs and emit operationally useful events.

This means the project is mathematically grounded at every stage:
- descriptive statistics for local dynamics,
- unsupervised learning for anomaly discovery,
- time-series forecasting for forward estimation.

## 26) Why This Implementation Is Strong

This codebase is strong because it combines:
- practical data engineering,
- real-time systems design,
- model lifecycle persistence,
- mathematically interpretable analytics,
- and usable frontend observability.

It is not just a visualization app.
It is an operational intelligence system.

## 27) Recommended Next Improvements

High-priority improvements:
- Add authentication and authorization for operation endpoints.
- Add explicit alert routes and alert-rule management UI.
- Add comprehensive pytest coverage for ingestion, repository, and API validators.
- Add decomposition endpoint for trend/seasonal/residual introspection.
- Add asynchronous queueing for heavy retraining workloads.

Model quality improvements:
- Add backtesting reports per symbol and model type.
- Add model drift alarms using rolling MAPE tracking.
- Add probabilistic calibration checks for interval quality.

Scalability improvements:
- Add partitioning strategy and retention policies in Mongo.
- Add streaming aggregation layer for very high-frequency feeds.

## 28) Final Summary

This project implements a complete real-time market intelligence stack.
It ingests live market feeds, enforces data normalization, computes engineered features, detects anomalies, generates resilient forecasts, and serves both REST and real-time channels to a modern React dashboard.

The mathematical core is explicit and practical:
- rolling statistics,
- z-score analytics,
- Isolation Forest,
- Prophet and regression-based forecasting with fallback safety.

The engineering core is equally clear:
- blueprint-based API architecture,
- repository-first persistence boundaries,
- guarded scheduler orchestration,
- model registry persistence,
- frontend state synchronization across REST and WebSocket.

Overall, this is a strong end-to-end applied ML systems project with clear architecture, real operational behavior, and meaningful analytical depth.
