# Real-Time Market Intelligence Console

An end-to-end market intelligence dashboard that ingests live and historical data, runs anomaly detection and forecasting, computes cross-market correlations, and streams updates to a React frontend in real time.

## What this project does

- Ingests crypto, stock, and weather-linked signals.
- Stores raw and processed datasets in MongoDB.
- Detects anomalies with statistical + model-assisted methods.
- Generates forecasts with Prophet-based model pipelines.
- Computes correlation metrics and shift-aware relationships.
- Streams updates over Socket.IO to a live dashboard.

## Tech stack

- Backend: Flask, Flask-SocketIO, APScheduler, Pandas, scikit-learn, Prophet, PyMongo
- Frontend: React, Vite, Recharts, Socket.IO Client
- Data store: MongoDB
- Tooling: pytest, Ruff

## Repository structure

```text
DEP_MINI_PROJECT/
|- backend/                 # Flask app, APIs, scheduler, services, DB repository
|- frontend/                # React + Vite dashboard
|- ml_models/               # Serialized anomaly/forecast model artifacts
|- requirements.txt         # Root Python dependencies
|- backend/requirements.txt # Backend-specific Python dependencies
|- pytest.ini
```

## Quick start

### 1. Prerequisites

- Python 3.10+
- Node.js 18+
- MongoDB running locally (or a reachable MongoDB URI)

### 2. Clone and install dependencies

```bash
git clone https://github.com/Sundareshwar-S/DEP_MINI_PROJECT.git
cd DEP_MINI_PROJECT

python -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
pip install -r backend/requirements.txt

cd frontend
npm install
cd ..
```

### 3. Configure environment

Create a .env file in the repository root.

Example values:

```env
# Flask
FLASK_HOST=0.0.0.0
FLASK_PORT=5000
FLASK_DEBUG=false
SECRET_KEY=dev-secret-key

# CORS / Socket
CORS_ORIGIN=http://localhost:5173
SOCKETIO_ASYNC_MODE=threading
WEBSOCKET_EMIT_INTERVAL_SECONDS=2

# MongoDB
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=Real_Time_Market_Intelligence_Console

# API keys (optional but recommended)
STOCK_API_KEY=
CRYPTO_API_KEY=
OPENWEATHER_API_KEY=

# Ingestion defaults
INGESTION_CRYPTO_SYMBOLS=BTC,ETH,SOL
INGESTION_STOCK_TICKERS=AAPL,MSFT,TSLA
INGESTION_WEATHER_CITIES=London,New York,Tokyo
```

### 4. Run backend and frontend

Backend (from repo root):

```bash
source .venv/bin/activate
python backend/src/app.py
```

Alternative backend launch:

```bash
source .venv/bin/activate
python -m backend.src.app
```

Frontend (new terminal):

```bash
cd frontend
npm run dev
```

Then open:

- Frontend: http://localhost:5173
- Backend health/root: http://localhost:5000/

## Backend API overview

Base URL: http://localhost:5000

All API responses use a shared envelope:

- Success: { status, data, meta }
- Error: { status: "error", error, meta }

### Read endpoints

| Method | Path | Purpose | Useful query params |
|---|---|---|---|
| GET | /api/data | Paginated market records | limit, offset, symbol, source, start_time, end_time |
| GET | /api/latest | Most recent market snapshot | symbol, source, start_time, end_time |
| GET | /api/forecast | Forecast outputs | limit, offset, symbol, model, start_time, end_time |
| GET | /api/forecast/diagnostics | Forecast quality diagnostics | symbol, holdout_steps, mape_threshold |
| GET | /api/anomalies | Anomaly events | limit, offset, symbol, source, anomalies_only, start_time, end_time |
| GET | /api/correlation | Correlation metrics | limit, offset, symbol, shift_only, start_time, end_time |
| GET | /api/series/market | Aggregated chart series | context, symbol, start_time, end_time, bucket, max_points |
| GET | /api/websocket/status | WebSocket service status | none |

### Operation endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | /api/start | Start stream + scheduler |
| POST | /api/stop | Stop stream + scheduler |
| POST | /api/run-task | Run operational task |

Example run-task payload:

```json
{ "task": "run_full_cycle" }
```

Supported tasks include:

- validate_keys
- emit_dummy_once
- scheduler_status
- start_scheduler
- stop_scheduler
- run_scheduler_job
- run_ingestion_cycle
- run_full_cycle
- run_history_backfill
- seed_dummy_db
- ingest_live_data
- run_processing_pipeline

## Realtime events

The frontend consumes Socket.IO events such as:

- new_data
- anomaly_detected
- alert_triggered
- system_status

Legacy compatibility events are also handled in the store:

- latest_data_points
- anomaly_events
- alert_updates

## Testing and linting

From repository root:

```bash
source .venv/bin/activate
python -m ruff check backend/src
python -m pytest
```

Run one test:

```bash
python -m pytest path/to/test_file.py::test_name
```

Frontend production build:

```bash
cd frontend
npm run build
npm run preview
```

## Architecture at a glance

- backend/src/app.py creates Flask app, registers blueprints, initializes DB and model registry, and wires Socket.IO.
- backend/src/scheduler/scheduler.py orchestrates ingestion, processing, correlation, forecasting, retraining, and freshness updates.
- backend/src/database/repository.py is the persistence boundary for all Mongo collections.
- backend/src/services/processing contains data cleaning, anomaly detection, correlation, forecasting, and model registry logic.
- frontend/src/store/store.js bootstraps REST data and merges realtime events into dashboard state.

## Common issues

- Frontend cannot connect to backend:
  - Confirm backend is running on port 5000.
  - Check CORS_ORIGIN and VITE_API_BASE_URL.
- No live data appears:
  - Ensure stream/scheduler is started via POST /api/start or UI controls.
  - Verify API keys (if required by your data providers).
- Mongo connection errors:
  - Verify MONGO_URI and local MongoDB service status.
- Forecast/anomaly output missing:
  - Run POST /api/run-task with task run_full_cycle.

## Project report

Detailed project report is available in DEP_Mini_Project_Report.md.
