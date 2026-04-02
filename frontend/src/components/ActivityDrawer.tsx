import { useEffect } from "react";
import type { ReactNode } from "react";

export function ActivityDrawer(props: {
  isOpen: boolean;
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!props.isOpen) {
      return;
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        props.onClose();
      }
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [props.isOpen, props.onClose]);

  if (!props.isOpen) {
    return null;
  }

  return (
    <div
      className="activity-drawer-backdrop"
      data-testid="activity-drawer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          props.onClose();
        }
      }}
    >
      <aside
        aria-label={props.title}
        aria-modal="true"
        className="activity-drawer"
        role="dialog"
      >
        <div className="activity-drawer-header">
          <div>
            <p className="section-kicker">Recent Activity</p>
            <h2>{props.title}</h2>
            {props.subtitle ? <p className="activity-drawer-subtitle">{props.subtitle}</p> : null}
          </div>
          <button
            aria-label="Close activity drawer"
            className="secondary-button"
            onClick={props.onClose}
            type="button"
          >
            Close
          </button>
        </div>

        <div className="activity-drawer-body">{props.children}</div>
      </aside>
    </div>
  );
}
