export function MetricCard(props: { label: string; value: string; accent: string }) {
  return (
    <article className="metric-card">
      <span className="metric-accent">{props.accent}</span>
      <strong>{props.value}</strong>
      <span>{props.label}</span>
    </article>
  );
}
