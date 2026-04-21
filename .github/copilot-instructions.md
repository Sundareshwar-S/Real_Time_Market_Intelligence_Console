# Copilot Instructions for DEP_MINI_PROJECT

## Workflow priorities in this repo
- Use planning for non-trivial work (multi-step or architecture-impacting changes) before implementation.
- Use sub-agents for parallelizable research/verification to keep the main thread focused.
- Prefer fixing issues directly after reproducing them, then verify behavior with the existing run/build/test commands below.

## Build, run, test, and lint commands

### Backend (Flask + Socket.IO)
- Install deps: `pip install -r requirements.txt` and `pip install -r backend/requirements.txt`
- Run server (project root): `python backend/src/app.py`
- Alternate run mode: `python -m backend.src.app`
- Lint: `python -m ruff check backend/src`
- Test suite: `python -m pytest`
- Single test: `python -m pytest path/to/test_file.py::test_name`

### Frontend (React + Vite)
- Install deps: `cd frontend && npm install`
- Dev server: `npm run dev`
- Production build: `npm run build`
- Preview build: `npm run preview`

## High-level architecture
- `backend/src/app.py` wires Flask blueprints, Socket.IO events, Mongo initialization, scheduler integration, and ML model registry initialization.
- API routes in `backend/src/api/` expose repository-backed data and operations (`/api/data`, `/api/latest`, `/api/forecast`, `/api/correlation`, `/api/alerts`, `/api/anomalies`, `/api/metrics`, `/api/start`, `/api/stop`, `/api/run-task`, `/api/websocket/status`).
- `backend/src/scheduler/scheduler.py` runs background ingestion + processing + correlation + forecast + retraining jobs, stores outcomes, and emits realtime events.
- `backend/src/database/repository.py` is the persistence boundary for Mongo collections (market, processed, anomaly, forecast, correlation, alerts, freshness, scheduler logs).
- Processing pipeline (`backend/src/services/processing/`) cleans/engineers data, detects anomalies, generates forecasts, computes correlations, and persists outputs.
- Frontend bootstraps from `frontend/src/app.jsx` via `initializeRealtimeApp()` in `frontend/src/store/store.js`, then merges REST bootstrap payloads with Socket.IO live events.
- Frontend store drives dashboard state by context (`all|crypto|stock|weather`) and timeframe (`30d|1y|4y`), including source alias mapping for backend filters.

## Key codebase conventions
- Use the shared API envelope from `backend/src/schemas/common_schema.py`:
  - success: `{ status, data, meta }`
  - error: `{ status: "error", error, meta }`
- Parse and validate query parameters with `backend/src/api/validators.py` helpers (`parse_limit_offset`, `parse_symbol`, `parse_source`, `parse_time_range`, etc.) instead of ad-hoc route parsing.
- Keep DB access in repository functions; route handlers should validate input, call repository/service functions, and shape responses via schema builders.
- Normalize timestamps to UTC ISO strings (`...Z`) across backend payloads and frontend state.
- Realtime event names expected by frontend store are:
  - `new_data`
  - `anomaly_detected`
  - `alert_triggered`
  - `system_status`
  - plus legacy compatibility events already handled in store (`latest_data_points`, `anomaly_events`, `alert_updates`).
- Frontend API URLs should be built through `frontend/src/api/endpoints.js` helpers (`buildEndpointUrl`, `buildReadEndpoint`) to keep query normalization consistent.

## folder structure

DEP_MINI_PROJECT/
│
├── DEP_Mini_Project_Report.md
├── pytest.ini
├── requirements.txt
├── backend/
│   ├── __init__.py
│   ├── requirements.txt
│   └── src/
│       ├── __init__.py
│       ├── app.py                     # Flask entry point (MAIN)
│       ├── optimize.py
│       ├── api/
│       │   ├── __init__.py
│       │   ├── anomalies.py
│       │   ├── correlation.py
│       │   ├── data.py
│       │   ├── dummy_payloads.py
│       │   ├── forecast.py
│       │   ├── ops.py
│       │   ├── series.py
│       │   ├── validators.py
│       │   └── websocket.py
│       ├── core/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   └── utils.py
│       ├── database/
│       │   ├── __init__.py
│       │   ├── db.py
│       │   ├── models.py
│       │   └── repository.py
│       ├── scheduler/
│       │   ├── __init__.py
│       │   └── scheduler.py
│       ├── schemas/
│       │   ├── __init__.py
│       │   ├── alert_schema.py
│       │   ├── anomaly_schema.py
│       │   ├── common_schema.py
│       │   ├── correlation_schema.py
│       │   ├── data_schema.py
│       │   ├── forecast_schema.py
│       │   └── metrics_schema.py
│       └── services/
│           ├── __init__.py
│           ├── metrics_service.py
│           ├── alerts/
│           │   ├── __init__.py
│           │   ├── alert_service.py
│           │   └── notifier.py
│           ├── ingestion/
│           │   ├── __init__.py
│           │   ├── crypto_history_service.py
│           │   ├── crypto_service.py
│           │   ├── stock_history_service.py
│           │   ├── stock_service.py
│           │   └── weather_service.py
│           └── processing/
│               ├── __init__.py
│               ├── anomaly.py
│               ├── cleaner.py
│               ├── correlation.py
│               ├── forecast.py
│               └── model_registry.py
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── app.jsx
│       ├── main.jsx
│       ├── api/
│       │   ├── endpoints.js
│       │   ├── restClient.js
│       │   └── socketClient.js
│       ├── components/
│       │   ├── charts/
│       │   ├── common/
│       │   └── layout/
│       ├── data/
│       ├── pages/
│       │   ├── anomalies.jsx
│       │   ├── forecasts.jsx
│       │   ├── markets.jsx
│       │   └── overview.jsx
│       ├── store/
│       │   └── store.js
│       ├── styles/
│       │   └── style.css
│       └── utils/
│           └── formatters.js
├── ml_models/
└── .env

---

# Workflow Orchestration

## 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately — don’t keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

## 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

## 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

## 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: “Would a staff engineer approve this?”
- Run tests, check logs, demonstrate correctness

## 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask “is there a more elegant way?”
- If a fix feels hacky: “Knowing everything I know now, implement the elegant solution”
- Skip this for simple, obvious fixes — don’t over-engineer
- Challenge your own work before presenting it

## 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don’t ask for hand-holding
- Point at logs, errors, failing tests — then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how

---

## Task Management

1. **Plan First**: Write plan to `tasks/todo.md` with checkable items  
2. **Verify Plan**: Check in before starting implementation  
3. **Track Progress**: Mark items complete as you go  
4. **Explain Changes**: High-level summary at each step  
5. **Document Results**: Add review section to `tasks/todo.md`  
6. **Capture Lessons**: Update `tasks/lessons.md` after corrections  

---

## Core Principles

- **Simplicity First**: Make every change as simple as possible. Impact minimal code.  
- **No Laziness**: Find root causes. No temporary fixes. Senior developer standards.  
- **Minimal Impact**: Changes should only touch what's necessary. Avoid introducing bugs.   

---
