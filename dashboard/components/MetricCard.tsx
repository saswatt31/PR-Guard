export function MetricCard({
  label,
  value,
  detail,
  accent = false,
}: {
  label: string;
  value: string;
  detail?: string;
  accent?: boolean;
}) {
  return (
    <article className="metric-card">
      <p className="metric-label">{label}</p>
      <p className={`metric-value${accent ? " accent" : ""}`}>{value}</p>
      {detail ? <p className="metric-detail">{detail}</p> : null}
    </article>
  );
}
