import {
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function formatTooltipValue(value, valueMode = "price", unit = null) {
  if (value == null || !Number.isFinite(value)) {
    return "--";
  }
  if (valueMode === "percent" || String(unit || "").toUpperCase() === "PCT") {
    return `${value.toFixed(2)}%`;
  }
  if (String(unit || "").toUpperCase() === "USD") {
    return value.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatAxisValue(value, valueMode = "price", unit = null) {
  if (value == null || !Number.isFinite(value)) {
    return "";
  }
  if (valueMode === "percent" || String(unit || "").toUpperCase() === "PCT") {
    return `${value.toFixed(1)}%`;
  }
  if (String(unit || "").toUpperCase() === "USD") {
    const abs = Math.abs(value);
    if (abs >= 1_000_000_000) {
      return `$${(value / 1_000_000_000).toFixed(1)}B`;
    }
    if (abs >= 1_000_000) {
      return `$${(value / 1_000_000).toFixed(1)}M`;
    }
    if (abs >= 1_000) {
      return `$${(value / 1_000).toFixed(1)}K`;
    }
    return `$${value.toFixed(0)}`;
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function formatXAxisValue(value, asTimeSeries) {
  if (!asTimeSeries) {
    return value;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function formatTooltipLabel(value, asTimeSeries) {
  if (!asTimeSeries) {
    return value;
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString([], {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function computePercentile(sortedValues, percentile) {
  if (!Array.isArray(sortedValues) || sortedValues.length === 0) {
    return Number.NaN;
  }
  const clamped = Math.min(1, Math.max(0, percentile));
  const index = (sortedValues.length - 1) * clamped;
  const lowerIndex = Math.floor(index);
  const upperIndex = Math.ceil(index);
  const lower = sortedValues[lowerIndex];
  const upper = sortedValues[upperIndex];
  if (!Number.isFinite(lower)) {
    return Number.NaN;
  }
  if (!Number.isFinite(upper) || lowerIndex === upperIndex) {
    return lower;
  }
  const weight = index - lowerIndex;
  return lower + (upper - lower) * weight;
}

function computeYAxisDomain(data, valueMode = "price") {
  const predictedValues = data
    .map((point) => point?.predicted)
    .filter((value) => Number.isFinite(value));
  const bandValues = data
    .flatMap((point) => [point?.lower, point?.upper])
    .filter((value) => Number.isFinite(value));
  const values = [...predictedValues, ...bandValues];
  if (values.length === 0) {
    return ["auto", "auto"];
  }

  const focusValues = (predictedValues.length > 1 ? predictedValues : values).slice().sort((a, b) => a - b);
  const focusLowerQ = focusValues.length >= 8 ? 0.08 : 0;
  const focusUpperQ = focusValues.length >= 8 ? 0.92 : 1;
  const fallbackFocusMin = focusValues[0];
  const fallbackFocusMax = focusValues[focusValues.length - 1];
  const focusMin = Number.isFinite(computePercentile(focusValues, focusLowerQ))
    ? computePercentile(focusValues, focusLowerQ)
    : fallbackFocusMin;
  const focusMax = Number.isFinite(computePercentile(focusValues, focusUpperQ))
    ? computePercentile(focusValues, focusUpperQ)
    : fallbackFocusMax;
  const focusSpread = focusMax - focusMin;
  const focusScale = Math.max(Math.abs(focusMin), Math.abs(focusMax), 1);
  const minVisualSpread = valueMode === "percent" ? 1.0 : focusScale * 0.015;
  const visualSpread = Math.max(focusSpread, minVisualSpread);

  const focusPadding = visualSpread * (valueMode === "percent" ? 0.2 : 0.16);
  let lower = focusMin - focusPadding;
  let upper = focusMax + focusPadding;

  if (bandValues.length > 0) {
    const sortedBand = bandValues.slice().sort((a, b) => a - b);
    const bandLowerQ = sortedBand.length >= 10 ? 0.05 : 0;
    const bandUpperQ = sortedBand.length >= 10 ? 0.95 : 1;
    const fallbackBandMin = sortedBand[0];
    const fallbackBandMax = sortedBand[sortedBand.length - 1];
    const bandMin = Number.isFinite(computePercentile(sortedBand, bandLowerQ))
      ? computePercentile(sortedBand, bandLowerQ)
      : fallbackBandMin;
    const bandMax = Number.isFinite(computePercentile(sortedBand, bandUpperQ))
      ? computePercentile(sortedBand, bandUpperQ)
      : fallbackBandMax;
    const maxBandExtension = visualSpread * (valueMode === "percent" ? 1.0 : 0.8);
    lower = Math.min(lower, Math.max(bandMin, lower - maxBandExtension));
    upper = Math.max(upper, Math.min(bandMax, upper + maxBandExtension));
  }

  if (!Number.isFinite(lower) || !Number.isFinite(upper) || lower >= upper) {
    const focusCenter = (focusMin + focusMax) / 2;
    const nudge = valueMode === "percent" ? 0.5 : Math.max(1, focusScale * 0.01);
    return [focusCenter - nudge, focusCenter + nudge];
  }
  return [lower, upper];
}

export default function ForecastRangeChart({ data, height = 260, valueMode = "price", unit = null }) {
  if (!data || data.length === 0) {
    return <div className="chart-empty">No forecast data available yet.</div>;
  }

  const asTimeSeries = data.some((point) => Boolean(point?.timestamp));
  const xKey = asTimeSeries ? "timestamp" : "horizon";
  const chartData = data.map((point) => ({
    ...point,
    lower: Number.isFinite(point?.lower) ? point.lower : point?.predicted,
    upper: Number.isFinite(point?.upper) ? point.upper : point?.predicted,
  }));
  const yDomain = computeYAxisDomain(chartData, valueMode);
  const yTickCount = valueMode === "percent" ? 7 : 6;
  const chartUnit = chartData.find((point) => point?.unit)?.unit || unit || null;

  return (
    <div className="live-chart">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={chartData}>
          <XAxis
            dataKey={xKey}
            axisLine={false}
            tickLine={false}
            stroke="var(--chart-axis)"
            tick={{ fontSize: 11 }}
            tickFormatter={(value) => formatXAxisValue(value, asTimeSeries)}
          />
          <YAxis
            type="number"
            domain={yDomain}
            allowDataOverflow
            tickCount={yTickCount}
            axisLine={false}
            tickLine={false}
            stroke="var(--chart-axis)"
            tick={{ fontSize: 11 }}
            width={52}
            tickFormatter={(v) => formatAxisValue(v, valueMode, chartUnit)}
          />
          <Tooltip
            formatter={(value, name) => [formatTooltipValue(value, valueMode, chartUnit), name]}
            labelFormatter={(value) => formatTooltipLabel(value, asTimeSeries)}
            contentStyle={{
              background: "var(--tooltip-background)",
              border: "1px solid var(--tooltip-border)",
              borderRadius: "8px",
            }}
          />
          <Line
            type="monotone"
            dataKey="lower"
            stroke="var(--primary-muted)"
            strokeWidth={1.2}
            strokeDasharray="4 4"
            dot={false}
            animationDuration={600}
            name="Lower bound"
          />
          <Line
            type="monotone"
            dataKey="upper"
            stroke="var(--primary-muted)"
            strokeWidth={1.2}
            strokeDasharray="4 4"
            dot={false}
            animationDuration={600}
            name="Upper bound"
          />
          <Line
            type="monotone"
            dataKey="predicted"
            stroke="var(--primary)"
            strokeWidth={2.5}
            dot={false}
            animationDuration={600}
            name="Predicted"
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
