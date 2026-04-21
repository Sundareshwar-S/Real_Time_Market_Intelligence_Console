import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export default function SeverityBarChart({ data, height = 220 }) {
  if (!data || data.length === 0) {
    return <div className="chart-empty">No anomaly events yet.</div>;
  }

  return (
    <div className="live-chart">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--chart-grid)" />
          <XAxis dataKey="timestamp" hide />
          <YAxis axisLine={false} tickLine={false} stroke="var(--chart-axis)" />
          <Tooltip
            contentStyle={{
              background: "var(--tooltip-background)",
              border: "1px solid var(--tooltip-border)",
              borderRadius: "8px",
            }}
          />
          <Bar dataKey="high" stackId="severity" fill="var(--danger)" />
          <Bar dataKey="medium" stackId="severity" fill="var(--warning)" />
          <Bar dataKey="low" stackId="severity" fill="var(--primary)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
