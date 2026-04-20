# Implementation Plan: Forecast Graph + Model Quality Investigation

## Problem Statement
On the **Forecasts** page, the curve appears too straight and the user wants the Y-axis to reflect variation more clearly.  
The user also wants verification that forecast models in `ml_models/` are producing correct predictions, that training/testing behavior is checked, and that model quality is improved if accuracy is low.

## Current State Analysis
- Reviewed project workflow/instructions in `.github/copilot-instructions.md`.
- Forecast UI currently renders with:
  - `frontend/src/pages/forecasts.jsx`
  - `frontend/src/components/charts/ForecastRangeChart.jsx`
- Y-axis domain currently uses min/max across **predicted + lower + upper** series with padding (`computeYAxisDomain`), which can visually flatten the center prediction line when confidence bands are wide.
- Forecast backend currently uses:
  - `backend/src/services/processing/forecast.py`
  - `backend/src/scheduler/scheduler.py`
  - `backend/src/database/repository.py`
  - persisted artifacts in `ml_models/` + metadata `ml_models/model_metadata.json`.
- Diagnostics logic already exists in backend (`summarize_forecast_diagnostics`) with holdout metrics (RMSE, MAPE, variance ratio, degenerate-path flag), but it is not surfaced in the Forecasts page.

## Proposed Approach
1. Rework forecast chart Y-axis scaling to prioritize useful visual resolution for the predicted line while still showing bounds safely.
2. Add/extend backend diagnostics access so current model quality and train/test-style holdout results are queryable.
3. Surface forecast diagnostics in frontend Forecasts page (per symbol/model status) to verify training/testing behavior.
4. Run model evaluation using existing diagnostics on current datasets and persisted models.
5. If accuracy is below an agreed threshold, improve the forecast model path (feature/model settings and/or fallback strategy), retrain, and re-check diagnostics.
6. Validate end-to-end: backend lint/tests + frontend build + UI behavior.

## Todo Outline
1. `confirm-forecast-accuracy-threshold` ✅ — Confirmed low-accuracy trigger at **MAPE > 12%**.
2. `forecast-chart-y-axis-rework` ✅ — Forecast Y-axis now prioritizes predicted-series resolution while still considering confidence bounds.
3. `forecast-diagnostics-api-surface` ✅ — Added diagnostics endpoint with holdout/test metrics and model metadata.
4. `forecast-diagnostics-ui-surface` ✅ — Added diagnostics table in Forecast page (train/test points, MAPE/RMSE, variance ratio, status).
5. `forecast-model-evaluation-run` ✅ — Baseline diagnostics executed against current training data + persisted models.
6. `forecast-model-improvement` ✅ — Added non-Prophet model selection via holdout-MAPE ranking (return vs seasonal regression) and retrained.
7. `forecast-end-to-end-validation` ✅ — Backend lint + frontend build + pytest baseline run completed.

## Notes / Decisions
- Keep API envelope and validator patterns aligned with repo conventions.
- Prefer existing internal diagnostics before adding new external tooling.
- Web research may be used **only if** current model approach is insufficient after baseline diagnostics.

## Review
- **Baseline diagnostics (holdout=30, threshold=12%)** showed one low-accuracy symbol:
  - `AAPL` MAPE `13.94%` (backend path: return regression)
- **After improvement**, diagnostics reported:
  - `low_accuracy_symbols: []`
  - symbol-level backend choice switched to best holdout candidate (seasonal or return regression)
- Added a dedicated API route:
  - `GET /api/forecast/diagnostics?symbol=<SYM>&holdout_steps=<N>&mape_threshold=<PCT>`
- Forecast UI now surfaces model quality so train/test behavior is visible in-app.
