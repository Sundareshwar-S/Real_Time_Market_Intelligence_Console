import { useMemo } from "react";
import KpiCard from "../components/common/KpiCard";
import Panel from "../components/common/Panel";
import RealtimeLineChart from "../components/charts/RealtimeLineChart";
import SeverityBarChart from "../components/charts/SeverityBarChart";
import { setAnomalyWindow, useAppStore } from "../store/store";
import { formatRelativeTime } from "../utils/formatters";

const WINDOW_MS = {
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
  "30d": 30 * 24 * 60 * 60 * 1000,
};

function getWindowBucketTimestamp(timestamp, anomalyWindow) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return null;
  }
  if (anomalyWindow === "24h") {
    date.setUTCMinutes(0, 0, 0);
  } else if (anomalyWindow === "7d") {
    date.setUTCHours(Math.floor(date.getUTCHours() / 6) * 6, 0, 0, 0);
  } else {
    date.setUTCHours(0, 0, 0, 0);
  }
  return date.toISOString();
}

function calculatePercentile(sortedValues, percentile) {
  if (!sortedValues.length) {
    return Number.POSITIVE_INFINITY;
  }
  const clamped = Math.max(0, Math.min(1, percentile));
  const index = Math.floor((sortedValues.length - 1) * clamped);
  return sortedValues[index];
}

export default function AnomaliesPage() {
  const anomalyWindow = useAppStore((s) => s.anomalyWindow);
  const anomalyEvents = useAppStore((s) => s.anomalies.events);
  const marketSeries = useAppStore((s) => s.charts.marketSeries);

  const windowMs = WINDOW_MS[anomalyWindow] || WINDOW_MS["24h"];
  const filteredEvents = useMemo(() => {
    const cutoff = Date.now() - windowMs;
    return anomalyEvents.filter((event) => {
      const ts = new Date(event.timestamp || 0).getTime();
      return Number.isFinite(ts) && ts >= cutoff;
    });
  }, [anomalyEvents, windowMs]);

  const severityCutoffs = useMemo(() => {
    const scores = filteredEvents
      .map((event) => Number(event.score ?? 0))
      .filter((score) => Number.isFinite(score))
      .sort((a, b) => a - b);
    return {
      high: calculatePercentile(scores, 0.9),
      medium: calculatePercentile(scores, 0.7),
    };
  }, [filteredEvents]);

  const eventsWithEffectiveSeverity = useMemo(
    () =>
      filteredEvents.map((event) => {
        const score = Number(event.score ?? 0);
        const declaredSeverity = String(event.severity || "low").toLowerCase();
        let effectiveSeverity = declaredSeverity;
        if (declaredSeverity !== "high" && declaredSeverity !== "medium" && Number.isFinite(score)) {
          if (score >= severityCutoffs.high) {
            effectiveSeverity = "high";
          } else if (score >= severityCutoffs.medium) {
            effectiveSeverity = "medium";
          }
        }
        return { ...event, effectiveSeverity };
      }),
    [filteredEvents, severityCutoffs.high, severityCutoffs.medium]
  );

  const sortedEffectiveEvents = useMemo(
    () =>
      [...eventsWithEffectiveSeverity].sort(
        (a, b) => new Date(b.timestamp || 0).getTime() - new Date(a.timestamp || 0).getTime()
      ),
    [eventsWithEffectiveSeverity]
  );

  const criticalCount = eventsWithEffectiveSeverity.filter(
    (event) => event.effectiveSeverity === "high"
  ).length;
  const mediumCount = eventsWithEffectiveSeverity.filter(
    (event) => event.effectiveSeverity === "medium"
  ).length;
  const confidence = filteredEvents.length
    ? Math.max(
        0,
        100 -
          eventsWithEffectiveSeverity
            .slice(0, 100)
            .reduce((acc, event) => acc + Math.min(1, (event.score ?? 0) / 10), 0)
      )
    : 100;

  const liquiditySeries = useMemo(() => {
    const cutoff = Date.now() - windowMs;
    const scoped = marketSeries
      .filter((point) => {
        const ts = new Date(point.timestamp || 0).getTime();
        return Number.isFinite(ts) && ts >= cutoff;
      })
      .sort((a, b) => new Date(a.timestamp || 0).getTime() - new Date(b.timestamp || 0).getTime());
    const normalized = scoped.flatMap((point) => {
      const rawCrypto = Number(point.crypto);
      const rawStock = Number(point.stock);
      const rawTotal = Number(point.total);
      const crypto = Number.isFinite(rawCrypto) && rawCrypto > 0 ? rawCrypto : null;
      const stock = Number.isFinite(rawStock) && rawStock > 0 ? rawStock : null;
      const sourceCoverage = Number(crypto != null) + Number(stock != null);

      if (sourceCoverage === 2) {
        return [{ ...point, total: crypto + stock, crypto, stock, sourceCoverage }];
      }
      if (sourceCoverage === 1) {
        const total = Number.isFinite(rawTotal) && rawTotal > 0 ? rawTotal : (crypto ?? stock);
        if (!Number.isFinite(total) || total <= 0) {
          return [];
        }
        return [{ ...point, total, crypto, stock, sourceCoverage }];
      }
      if (!Number.isFinite(rawTotal) || rawTotal <= 0) {
        return [];
      }
      return [{ ...point, total: rawTotal, crypto, stock, sourceCoverage }];
    });
    const dualCoverageTotals = normalized
      .filter((point) => point.sourceCoverage === 2)
      .map((point) => Number(point.total))
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((a, b) => a - b);
    const dualCoverageMedian = calculatePercentile(dualCoverageTotals, 0.5);
    const minAllowedPartialTotal =
      Number.isFinite(dualCoverageMedian) && dualCoverageMedian > 0
        ? dualCoverageMedian * 0.35
        : 0;
    const coverageAware = normalized.filter((point) => {
      if (point.sourceCoverage >= 2 || minAllowedPartialTotal <= 0) {
        return true;
      }
      return Number(point.total) >= minAllowedPartialTotal;
    });
    return coverageAware.map((point, index, all) => {
      const start = Math.max(0, index - 5);
      const baselineWindow = all.slice(start, index + 1);
      const baseline =
        baselineWindow.reduce((acc, row) => acc + Number(row.total || 0), 0) /
        Math.max(1, baselineWindow.length);
      return {
        ...point,
        baseline,
      };
    });
  }, [marketSeries, windowMs]);

  const liquidityDomain = useMemo(() => {
    const values = liquiditySeries
      .flatMap((point) => [Number(point.total), Number(point.baseline)])
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((a, b) => a - b);
    if (values.length < 2) {
      return ["auto", "auto"];
    }
    const lowerBound = calculatePercentile(values, 0.05);
    const upperBound = calculatePercentile(values, 0.95);
    const min = Math.max(0, Math.min(lowerBound, upperBound));
    const max = Math.max(lowerBound, upperBound);
    const spread = Math.max(max - min, max * 0.02, 1);
    const padding = spread * 0.12;
    const domainMin = Math.max(0, min - padding);
    const domainMax = max + padding;
    if (!Number.isFinite(domainMin) || !Number.isFinite(domainMax) || domainMax <= domainMin) {
      return ["auto", "auto"];
    }
    return [domainMin, domainMax];
  }, [liquiditySeries]);

  const anomalySeries = useMemo(() => {
    const bucketed = new Map();
    for (const event of eventsWithEffectiveSeverity) {
      const bucketTimestamp = getWindowBucketTimestamp(event.timestamp, anomalyWindow);
      if (!bucketTimestamp) {
        continue;
      }
      if (!bucketed.has(bucketTimestamp)) {
        bucketed.set(bucketTimestamp, {
          timestamp: bucketTimestamp,
          high: 0,
          medium: 0,
          low: 0,
          total: 0,
        });
      }
      const point = bucketed.get(bucketTimestamp);
      const severity = String(event.effectiveSeverity || "low").toLowerCase();
      if (severity === "high") {
        point.high += 1;
      } else if (severity === "medium") {
        point.medium += 1;
      } else {
        point.low += 1;
      }
      point.total += 1;
    }
    return [...bucketed.values()].sort(
      (a, b) => new Date(a.timestamp || 0).getTime() - new Date(b.timestamp || 0).getTime()
    );
  }, [anomalyWindow, eventsWithEffectiveSeverity]);

  const latestEvent = sortedEffectiveEvents[0] || null;

  return (
    <div className="page">
      <header className="page-header">
        <div>
          <h2>Anomalies &amp; Forecasts</h2>
          <p>Real-time irregularity detection and predictive monitoring.</p>
        </div>
        <div className="overview-switches">
          <div className="segmented">
            <button
              type="button"
              className={anomalyWindow === "24h" ? "active" : ""}
              onClick={() => setAnomalyWindow("24h")}
            >
              24h
            </button>
            <button
              type="button"
              className={anomalyWindow === "7d" ? "active" : ""}
              onClick={() => setAnomalyWindow("7d")}
            >
              7d
            </button>
            <button
              type="button"
              className={anomalyWindow === "30d" ? "active" : ""}
              onClick={() => setAnomalyWindow("30d")}
            >
              30d
            </button>
          </div>
        </div>
      </header>

      <section className="grid fourths">
        <KpiCard
          label="Critical Anomalies"
          value={String(criticalCount)}
          trend={`${filteredEvents.length} total`}
          trendType={criticalCount > 0 ? "negative" : "positive"}
          icon="warning"
        />
        <KpiCard
          label="Elevated Variance"
          value={String(mediumCount)}
          trend="severity: medium"
          trendType={mediumCount > 0 ? "warning" : "positive"}
          icon="error"
        />
        <KpiCard
          label="Forecast Confidence"
          value={`${confidence.toFixed(1)}%`}
          trend="derived from anomaly score"
          trendType={confidence > 85 ? "positive" : "warning"}
          icon="online_prediction"
        />
        <KpiCard
          label="Vectors Monitored"
          value={String(liquiditySeries.length)}
          trend={latestEvent ? formatRelativeTime(latestEvent.timestamp) : "waiting"}
          trendType="neutral"
          icon="model_training"
        />
      </section>

      <section className="grid two-third">
        <Panel
          title="Global Liquidity Vector"
          subtitle={`Historical variance in selected ${anomalyWindow} window`}
        >
          <RealtimeLineChart
            data={liquiditySeries}
            height={280}
            yDomain={liquidityDomain}
            lines={[
              { dataKey: "total", color: "#55d7ed", strokeWidth: 2.4, type: "linear" },
              { dataKey: "baseline", color: "#bdc9ca", strokeWidth: 1.6, type: "linear" },
            ]}
          />
        </Panel>

        <Panel
          title="Live Anomalies"
          subtitle={`${filteredEvents.length} events in selected ${anomalyWindow} window`}
          actions={<span className="pill danger">Live</span>}
        >
          <SeverityBarChart data={anomalySeries.slice(-30)} height={140} />
          <div className="stack">
            {filteredEvents.length === 0 ? (
              <div className="chart-empty">No anomaly events detected in {anomalyWindow} window.</div>
            ) : null}
            {sortedEffectiveEvents.slice(0, 6).map((event) => {
              return (
              <article key={event.id} className={`alert-item ${event.effectiveSeverity || event.severity}`}>
                <h4>
                  {event.symbol} • {event.type}
                </h4>
                <p>
                  score={(event.score ?? 0).toFixed(2)} • source={event.source}
                </p>
                <small>{formatRelativeTime(event.timestamp)}</small>
              </article>
              );
            })}
          </div>
        </Panel>
      </section>
    </div>
  );
}
