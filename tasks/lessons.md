# Lessons

- When fixing false zero dips by preserving null values, also verify chart rendering behavior for null buckets. In Recharts Line, use connectNulls for time-series that should remain visually continuous across missing samples.
- Never label a KPI as market cap when data is actually price sums; if market-cap data is unavailable, surface explicit unavailable/alternate labels instead of fallbacking silently.
- For provider endpoints that return a market timestamp (e.g., Polygon `prev` bar `t`), persist that timestamp rather than wall-clock ingest time to avoid artificial flat lines in historical charts.
- For slowly-changing reference fields like stock market cap, never overwrite stored values with null on transient provider misses; keep last known non-null value and backfill null historical rows once a valid API response arrives.
- For mixed-source liquidity charts, skip incomplete source buckets before plotting and use an outlier-robust y-axis domain; otherwise sparse buckets can force near-zero lows and visually flatten the later trend.
- Do not apply strict dual-source bucket filtering uniformly across long windows (like 30D); it can collapse history and make different windows look identical. Use coverage-aware inclusion with quality thresholds.
