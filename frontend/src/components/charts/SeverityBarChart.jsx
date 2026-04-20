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
          <CartesianGrid strokeDasharray="3 3" stroke="#3e494a" />
          <XAxis dataKey="timestamp" hide />
          <YAxis axisLine={false} tickLine={false} stroke="#bdc9ca" />
          <Tooltip
            contentStyle={{
              background: "#1c1b1b",
              border: "1px solid #3e494a",
              borderRadius: "8px",
            }}
          />
          <Bar dataKey="high" stackId="severity" fill="#ffb4ab" />
          <Bar dataKey="medium" stackId="severity" fill="#ffb782" />
          <Bar dataKey="low" stackId="severity" fill="#55d7ed" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
