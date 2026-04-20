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

function computeYAxisDomain(data) {
  const values = data
    .flatMap((point) => [point?.predicted, point?.lower, point?.upper])
    .filter((value) => Number.isFinite(value));
  if (values.length === 0) {
    return ["auto", "auto"];
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min;
  const scaleBase = Math.max(Math.abs(min), Math.abs(max), 1);
  const padding = spread > 0 ? Math.max(spread * 0.2, scaleBase * 0.005) : scaleBase * 0.01;
  const lower = min - padding;
  const upper = max + padding;
  if (lower === upper) {
    return [lower - 1, upper + 1];
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
  const yDomain = computeYAxisDomain(chartData);
  const chartUnit = chartData.find((point) => point?.unit)?.unit || unit || null;

  return (
    <div className="live-chart">
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={chartData}>
          <XAxis
            dataKey={xKey}
            axisLine={false}
            tickLine={false}
            stroke="#bdc9ca"
            tick={{ fontSize: 11 }}
            tickFormatter={(value) => formatXAxisValue(value, asTimeSeries)}
          />
          <YAxis
            type="number"
            domain={yDomain}
            allowDataOverflow
            axisLine={false}
            tickLine={false}
            stroke="#bdc9ca"
            tick={{ fontSize: 11 }}
            width={52}
            tickFormatter={(v) => formatAxisValue(v, valueMode, chartUnit)}
          />
          <Tooltip
            formatter={(value, name) => [formatTooltipValue(value, valueMode, chartUnit), name]}
            labelFormatter={(value) => formatTooltipLabel(value, asTimeSeries)}
            contentStyle={{
              background: "#1c1b1b",
              border: "1px solid #3e494a",
              borderRadius: "8px",
            }}
          />
          <Line
            type="monotone"
            dataKey="lower"
            stroke="rgba(85, 215, 237, 0.55)"
            strokeWidth={1.2}
            strokeDasharray="4 4"
            dot={false}
            animationDuration={600}
            name="Lower bound"
          />
          <Line
            type="monotone"
            dataKey="upper"
            stroke="rgba(85, 215, 237, 0.55)"
            strokeWidth={1.2}
            strokeDasharray="4 4"
            dot={false}
            animationDuration={600}
            name="Upper bound"
          />
          <Line
            type="monotone"
            dataKey="predicted"
            stroke="#55d7ed"
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
