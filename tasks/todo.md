# TODO

- [x] Re-read project workflow and architecture instructions
- [x] Reproduce chart regression after null-preserving coercion
- [x] Add configurable null-connection behavior to line chart renderer
- [x] Enable null-connection for market overview and markets pages
- [x] Validate build and file diagnostics

## Codebase Review and Remediation Plan

- [x] Gather baseline evidence (lint/build/test/diagnostics)
- [x] Review backend and frontend modules for hidden bugs and bottlenecks
- [x] Compare implementation patterns against web references (Flask-SocketIO + Vite guidance)
- [x] Fix critical backend issues (scheduler coverage, stream resilience, startup guards)
- [x] Fix high-impact frontend issues (initial bundle and realtime handler resilience)
- [x] Re-run validation checks and document outcomes

## Review

- Root cause: preserving null values removed false zero dips, but exposed null buckets as visible gaps in market line charts.
- Fix: keep null-safe coercion in store and enable chart-level null bridging for market charts via Recharts connectNulls.
- Validation: frontend build passed with BUILD_OK.

## Codebase Review Outcomes

- Correlation job gap fixed by wiring scheduled and on-demand correlation execution into scheduler and ops API.
- WebSocket stream loop now survives transient repository or emit failures via guarded retry/backoff.
- App startup no longer hard-crashes on DB/model registry bootstrap failures; degraded mode warnings are surfaced.
- Frontend route-level lazy loading enabled; production build now emits split page chunks instead of a single oversized bundle.
- Vite manual chunking configured for react/router, recharts, and socket.io client; build warnings for oversized chunks cleared.
- Socket event handlers are now guard-wrapped to avoid malformed payloads taking down realtime state updates.
- Pytest warning hygiene improved by pinning asyncio fixture loop scope in pytest.ini.
- Empty alert service module now explicitly documented as a placeholder to avoid silent confusion.
- Validation: backend lint passed, frontend build passed, pytest discovered no tests (exit code 5).
