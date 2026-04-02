export function PanelState(props: {
  title: string;
  body: string;
  variant?: "idle" | "loading" | "error";
  compact?: boolean;
}) {
  const variant = props.variant || "idle";
  const className = props.compact
    ? `empty-state compact-empty state-block state-${variant}`
    : `empty-state state-block state-${variant}`;

  return (
    <div className={className}>
      <div className="state-block-header">
        {variant === "loading" ? <span className="state-pulse" aria-hidden="true" /> : null}
        <strong>{props.title}</strong>
      </div>
      <p>{props.body}</p>
    </div>
  );
}
