type MetricAccent = "Sunrise" | "Lagoon" | "Paper";

export function MetricCard(props: { label: string; value: string; accent: MetricAccent }) {
  const accentClassName = `metric-card-${props.accent.toLowerCase()}`;

  return (
    <article className={`metric-card ${accentClassName}`}>
      <span className={`metric-accent ${accentClassName}`}>{props.accent}</span>
      <strong>{props.value}</strong>
      <span>{props.label}</span>
    </article>
  );
}
