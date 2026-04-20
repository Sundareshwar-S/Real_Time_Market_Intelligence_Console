import { useEffect, useMemo, useState } from "react";
import Panel from "../components/common/Panel";
import ForecastRangeChart from "../components/charts/ForecastRangeChart";
import {
  getState,
  refreshDashboardData,
  runPipelineTask,
  setTimeRange,
  useAppStore,
} from "../store/store";
import { formatRelativeTime } from "../utils/formatters";

const AUTO_HYDRATE_TIMEOUT_MS = 25000;
const AUTO_HYDRATE_POLL_ATTEMPTS = 6;
const AUTO_HYDRATE_POLL_INTERVAL_MS = 3000;
const REFRESH_TIMEOUT_MS = 10000;

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function withTimeout(promise, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error("forecast_auto_generation_timed_out"));
    }, timeoutMs);
    promise
      .then((value) => {
        clearTimeout(timeout);
        resolve(value);
      })
      .catch((error) => {
        clearTimeout(timeout);
        reject(error);
      });
  });
}

function toNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatModelLabel(modelName) {
  const raw = String(modelName || "forecast").trim();
  if (!raw) {
    return "forecast";
  }
  return raw.replaceAll("_", " ");
}

function formatForecastValue(value, unit) {
  if (value == null || !Number.isFinite(Number(value))) {
    return "--";
  }
  const numeric = Number(value);
  if (String(unit || "").toUpperCase() === "USD") {
    return numeric.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function ForecastsPage() {
  const timeRange = useAppStore((s) => s.timeRange);
  const predictions = useAppStore((s) => s.forecasts.predictions);
  const generatedAt = useAppStore((s) => s.forecasts.updatedAt);
  const loading = useAppStore((s) => s.ui.loading);
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [valueView, setValueView] = useState("usd");
  const [autoHydrateAttempted, setAutoHydrateAttempted] = useState(false);
  const [autoHydrateRunning, setAutoHydrateRunning] = useState(false);
  const [autoHydrateError, setAutoHydrateError] = useState("");

  const normalizedPredictions = useMemo(
    () =>
      predictions
        .map((row) => ({
          symbol: String(row.symbol || "").toUpperCase(),
          model: String(row.model || "forecast"),
          horizon_step: Number(row.horizon_step || 0),
          interval: String(row.interval || ""),
          predicted_value: toNumber(row.predicted_value),
          lower_bound: toNumber(row.lower_bound),
          upper_bound: toNumber(row.upper_bound),
          confidence: toNumber(row.confidence),
          unit: row.unit ? String(row.unit).toUpperCase() : null,
          generated_at: row.generated_at || row.created_at || null,
          created_at: row.created_at || row.generated_at || null,
        }))
        .filter(
          (row) =>
            row.symbol &&
            row.horizon_step > 0 &&
            row.predicted_value != null &&
            row.generated_at
        ),
    [predictions]
  );

  const latestBySymbolHorizon = useMemo(() => {
    const isFallbackModel = (modelName) =>
      String(modelName || "").toLowerCase().includes("rolling_fallback");
    const byKey = new Map();
    for (const row of normalizedPredictions) {
      const key = `${row.symbol}:${row.horizon_step}`;
      const current = byKey.get(key);
      const rowTs = new Date(row.created_at || row.generated_at || 0).getTime();
      const currentTs = new Date(current?.created_at || current?.generated_at || 0).getTime();
      if (!current) {
        byKey.set(key, row);
        continue;
      }
      const currentIsFallback = isFallbackModel(current.model);
      const rowIsFallback = isFallbackModel(row.model);
      if (currentIsFallback && !rowIsFallback) {
        byKey.set(key, row);
        continue;
      }
      if (currentIsFallback === rowIsFallback && rowTs >= currentTs) {
        byKey.set(key, row);
      }
    }
    return [...byKey.values()];
  }, [normalizedPredictions]);

  const fallbackOnlyRows = useMemo(() => {
    if (latestBySymbolHorizon.length === 0) {
      return false;
    }
    const scopedRows =
      selectedSymbol && latestBySymbolHorizon.some((row) => row.symbol === selectedSymbol)
        ? latestBySymbolHorizon.filter((row) => row.symbol === selectedSymbol)
        : latestBySymbolHorizon;
    return scopedRows.every((row) =>
      String(row.model || "").toLowerCase().includes("rolling_fallback")
    );
  }, [latestBySymbolHorizon, selectedSymbol]);

  const availableSymbols = useMemo(
    () => [...new Set(latestBySymbolHorizon.map((row) => row.symbol))].sort(),
    [latestBySymbolHorizon]
  );

  useEffect(() => {
    if (!availableSymbols.length) {
      setSelectedSymbol("");
      return;
    }
    if (!selectedSymbol || !availableSymbols.includes(selectedSymbol)) {
      setSelectedSymbol(availableSymbols[0]);
    }
  }, [availableSymbols, selectedSymbol]);

  useEffect(() => {
    const shouldHydrate = latestBySymbolHorizon.length === 0 || fallbackOnlyRows;
    if (loading || !shouldHydrate || autoHydrateAttempted) {
      return;
    }
    let cancelled = false;
    setAutoHydrateAttempted(true);
    setAutoHydrateRunning(true);
    setAutoHydrateError("");

    const hydrate = async () => {
      try {
        await withTimeout(
          runPipelineTask("run_scheduler_job", { job: "forecast" }),
          AUTO_HYDRATE_TIMEOUT_MS
        );
      } catch (_error) {
        await withTimeout(
          runPipelineTask("run_full_cycle"),
          AUTO_HYDRATE_TIMEOUT_MS
        );
      }

      for (let attempt = 0; attempt < AUTO_HYDRATE_POLL_ATTEMPTS; attempt += 1) {
        await withTimeout(refreshDashboardData(), REFRESH_TIMEOUT_MS);
        if ((getState().forecasts.predictions || []).length > 0) {
          return;
        }
        if (attempt < AUTO_HYDRATE_POLL_ATTEMPTS - 1) {
          await sleep(AUTO_HYDRATE_POLL_INTERVAL_MS);
        }
      }
      throw new Error("forecast_data_not_ready_after_generation");
    };

    hydrate()
      .catch((error) => {
        if (cancelled) {
          return;
        }
        const message = String(error?.message || error || "forecast_autohydrate_failed");
        if (message.includes("timed_out")) {
          setAutoHydrateError("Forecast generation timed out. Retry.");
        } else if (message.includes("not_ready_after_generation")) {
          setAutoHydrateError("No forecast data available yet. Retry.");
        } else {
          setAutoHydrateError("Forecast generation failed. Retry.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setAutoHydrateRunning(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [autoHydrateAttempted, autoHydrateRunning, fallbackOnlyRows, latestBySymbolHorizon.length, loading]);

  const requestedDays = timeRange === "1y" ? 365 : 30;
  const symbolRows = latestBySymbolHorizon
    .filter((row) => row.symbol === selectedSymbol && row.horizon_step <= requestedDays)
    .sort((a, b) => a.horizon_step - b.horizon_step);
  const modelNames = [...new Set(symbolRows.map((row) => String(row.model || "forecast")))];
  const symbolUnit = symbolRows.find((row) => row.unit)?.unit || null;
  const modelLabel =
    modelNames.length === 0
      ? null
      : modelNames.length === 1
        ? formatModelLabel(modelNames[0])
        : `${modelNames.length} models`;

  const rawForecastSeries = symbolRows.map((row) => ({
    timestamp: row.generated_at,
    predicted: row.predicted_value,
    lower: row.lower_bound,
    upper: row.upper_bound,
    source: row.model,
    unit: row.unit || symbolUnit || null,
  }));
  const forecastSeries = useMemo(() => {
    if (valueView !== "pct") {
      return rawForecastSeries;
    }
    const baseline = rawForecastSeries[0]?.predicted;
    if (!Number.isFinite(Number(baseline)) || Number(baseline) === 0) {
      return rawForecastSeries;
    }
    const base = Number(baseline);
    return rawForecastSeries.map((row) => ({
      ...row,
      predicted: Number.isFinite(Number(row.predicted)) ? ((Number(row.predicted) - base) / base) * 100 : null,
      lower: Number.isFinite(Number(row.lower)) ? ((Number(row.lower) - base) / base) * 100 : null,
      upper: Number.isFinite(Number(row.upper)) ? ((Number(row.upper) - base) / base) * 100 : null,
      unit: "PCT",
    }));
  }, [rawForecastSeries, valueView]);

  const coverageText = autoHydrateRunning
    ? fallbackOnlyRows
      ? "Upgrading forecast model output..."
      : "Generating forecast data..."
    : symbolRows.length > 0
      ? `Showing next ${Math.min(requestedDays, symbolRows.length)} days (${selectedSymbol})${modelLabel ? ` • ${modelLabel}` : ""}${valueView === "pct" ? " • % change view" : symbolUnit === "USD" ? " • USD view" : ""}`
      : autoHydrateError || "No forecast data available yet.";

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2>Forecast Models</h2>
          <p>
            Predictive outputs for active market and pipeline vectors
            {generatedAt ? ` • updated ${formatRelativeTime(generatedAt)}` : ""}
            .
          </p>
        </div>
        <div className="overview-switches">
          <div className="segmented" aria-label="forecast-time-range">
            <button
              type="button"
              className={timeRange === "30d" ? "active" : ""}
              onClick={() => setTimeRange("30d")}
            >
              30D
            </button>
            <button
              type="button"
              className={timeRange === "1y" ? "active" : ""}
              onClick={() => setTimeRange("1y")}
            >
              1Y
            </button>
          </div>
          <div className="segmented" aria-label="forecast-value-view">
            <button
              type="button"
              className={valueView === "usd" ? "active" : ""}
              onClick={() => setValueView("usd")}
            >
              USD
            </button>
            <button
              type="button"
              className={valueView === "pct" ? "active" : ""}
              onClick={() => setValueView("pct")}
            >
              % Change
            </button>
          </div>
          {availableSymbols.length > 0 ? (
            <div className="segmented" aria-label="forecast-symbol-selector">
              <select value={selectedSymbol} onChange={(event) => setSelectedSymbol(event.target.value)}>
                {availableSymbols.map((symbol) => (
                  <option key={symbol} value={symbol}>
                    {symbol}
                  </option>
                ))}
              </select>
            </div>
          ) : !autoHydrateRunning ? (
            <button
              type="button"
              className="action-btn ghost"
              onClick={() => {
                setAutoHydrateError("");
                setAutoHydrateAttempted(false);
              }}
            >
              Retry Forecast
            </button>
          ) : null}
        </div>
      </header>

      <Panel title="Forecast Trend" subtitle={coverageText}>
        <ForecastRangeChart
          data={forecastSeries}
          valueMode={valueView === "pct" ? "percent" : "price"}
          unit={symbolUnit}
        />
      </Panel>

      <Panel title="Forecast Output Matrix" subtitle="Future daily predictions">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Date</th>
                <th>Symbol</th>
                <th>Model</th>
                <th>Forecast</th>
                <th>Confidence</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {symbolRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="table-empty-cell">
                    No forecasts generated yet.
                  </td>
                </tr>
              ) : null}
              {symbolRows.map((row) => {
                const spread =
                  row.upper_bound != null && row.lower_bound != null
                    ? row.upper_bound - row.lower_bound
                    : 0;
                const risk =
                  spread > Math.abs(Number(row.predicted_value || 0)) * 0.12
                    ? "High"
                    : spread > Math.abs(Number(row.predicted_value || 0)) * 0.06
                      ? "Medium"
                      : "Low";
                return (
                  <tr key={`${row.symbol}:${row.horizon_step}`}>
                    <td>{new Date(row.generated_at).toLocaleDateString()}</td>
                    <td>{row.symbol}</td>
                    <td>{row.model}</td>
                    <td>{formatForecastValue(row.predicted_value, row.unit || symbolUnit)}</td>
                    <td className="positive">
                      {row.confidence != null
                        ? `${(Number(row.confidence) * 100).toFixed(1)}%`
                        : "--"}
                    </td>
                    <td className={risk === "High" ? "negative" : risk === "Medium" ? "warning" : "positive"}>
                      {risk}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
