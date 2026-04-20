import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

function formatXAxis(value, mode = "time") {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  if (mode === "month") {
    return date.toLocaleDateString([], { month: "short", year: "2-digit" });
  }
  if (mode === "date") {
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatYAxis(value, valueMode = "number") {
  if (value == null || !Number.isFinite(value)) {
    return "";
  }
  const abs = Math.abs(value);
  if (valueMode === "currency") {
    if (abs >= 1_000_000_000) {
      return `$${(value / 1_000_000_000).toFixed(1)}B`;
    }
    if (abs >= 1_000_000) {
      return `$${(value / 1_000_000).toFixed(1)}M`;
    }
    if (abs >= 1_000) {
      return `$${(value / 1_000).toFixed(1)}K`;
    }
    if (abs < 1 && abs > 0) {
      return `$${value.toFixed(2)}`;
    }
    return `$${value.toFixed(0)}`;
  }
  if (abs >= 1_000_000_000) {
    return `${(value / 1_000_000_000).toFixed(1)}B`;
  }
  if (abs >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (abs >= 1_000) {
    return `${(value / 1_000).toFixed(1)}K`;
  }
  if (abs < 1 && abs > 0) {
    return value.toFixed(2);
  }
  return value.toFixed(0);
}

function formatTooltipLabel(value) {
  if (!value) {
    return "";
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

function formatTooltipValue(value, valueMode = "number") {
  if (value == null || !Number.isFinite(value)) {
    return "--";
  }
  if (valueMode === "currency") {
    return value.toLocaleString(undefined, {
      style: "currency",
      currency: "USD",
      maximumFractionDigits: 2,
    });
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

export default function RealtimeLineChart({
  data,
  lines,
  height = 220,
  yDomain = ["auto", "auto"],
  connectNulls = false,
  valueMode = "number",
}) {
  if (!data || data.length === 0) {
    return <div className="chart-empty">Waiting for live data...</div>;
  }

  const firstTimestamp = new Date(data[0]?.timestamp || 0).getTime();
  const lastTimestamp = new Date(data[data.length - 1]?.timestamp || 0).getTime();
  const spanMs =
    Number.isFinite(firstTimestamp) && Number.isFinite(lastTimestamp)
      ? Math.max(0, lastTimestamp - firstTimestamp)
      : 0;
  const tickMode =
    spanMs > 1000 * 60 * 60 * 24 * 365
      ? "month"
      : spanMs > 1000 * 60 * 60 * 24 * 2
        ? "date"
        : "time";

  return (
    <div className="live-chart">
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={data}>
          <XAxis
            dataKey="timestamp"
            tickFormatter={(value) => formatXAxis(value, tickMode)}
            axisLine={false}
            tickLine={false}
            minTickGap={20}
            stroke="#bdc9ca"
            tick={{ fontSize: 11 }}
          />
          <YAxis
            domain={yDomain}
            axisLine={false}
            tickLine={false}
            stroke="#bdc9ca"
            tick={{ fontSize: 11 }}
            width={52}
            tickFormatter={(value) => formatYAxis(value, valueMode)}
          />
          <Tooltip
            labelFormatter={formatTooltipLabel}
            formatter={(value) => formatTooltipValue(value, valueMode)}
            contentStyle={{
              background: "#1c1b1b",
              border: "1px solid #3e494a",
              borderRadius: "8px",
            }}
          />
          {lines.map((line) => (
            <Line
              key={line.dataKey}
              type={line.type || "monotone"}
              dataKey={line.dataKey}
              stroke={line.color}
              strokeWidth={line.strokeWidth || 2}
              connectNulls={line.connectNulls ?? connectNulls}
              dot={false}
              animationDuration={600}
              animationEasing="ease-in-out"
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
