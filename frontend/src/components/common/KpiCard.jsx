export default function KpiCard({
  label,
  value,
  trend,
  trendType = "neutral",
  icon,
}) {
  return (
    <article className="kpi-card">
      <div className="kpi-head">
        <p>{label}</p>
        {icon ? <span className="material-symbols-outlined">{icon}</span> : null}
      </div>
      <div className="kpi-main">
        <h4>{value}</h4>
        {trend ? <span className={`trend ${trendType}`}>{trend}</span> : null}
      </div>
    </article>
  );
}
