export function PanelState(props: {
  title: string;
  body: string;
  variant?: "idle" | "loading" | "error";
  compact?: boolean;
  eyebrow?: string;
}) {
  const variant = props.variant || "idle";
  const className = props.compact
    ? `empty-state compact-empty state-block state-${variant}`
    : `empty-state state-block state-${variant}`;

  return (
    <div className={className}>
      <div className="state-block-ornament" aria-hidden="true">
        {variant === "loading" ? (
          <span className="state-pulse" />
        ) : (
          <span className="state-block-glyph" />
        )}
      </div>
      <div className="state-block-copy">
        {props.eyebrow ? <p className="state-block-eyebrow">{props.eyebrow}</p> : null}
        <div className="state-block-header">
          <strong>{props.title}</strong>
        </div>
        <p>{props.body}</p>
      </div>
    </div>
  );
}
