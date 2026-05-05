import { useEffect, useId, useRef, useState } from "react";

import type { CatalogScope } from "../types";

export function SearchOptionsControl(props: {
  loadAllLanguages: boolean;
  onLoadAllLanguagesChange: (nextValue: boolean) => void;
  onScopeChange: (scope: CatalogScope) => void;
  placement?: "inline" | "sticky";
  scope: CatalogScope;
}) {
  const placement = props.placement || "inline";
  const panelId = useId();
  const shellRef = useRef<HTMLDivElement | null>(null);
  const [open, setOpen] = useState(false);
  const hasActiveOptions =
    props.scope === "all" || props.loadAllLanguages;

  useEffect(() => {
    if (!open) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (shellRef.current?.contains(target)) {
        return;
      }
      setOpen(false);
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
      }
    }

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  return (
    <div
      className={
        placement === "sticky"
          ? "search-options-control search-options-control-sticky"
          : "search-options-control"
      }
      ref={shellRef}
    >
      <button
        aria-controls={open ? panelId : undefined}
        aria-expanded={open}
        className={
          placement === "sticky"
            ? hasActiveOptions
              ? "utility-button search-options-trigger search-options-trigger-sticky search-options-trigger-active"
              : "utility-button search-options-trigger search-options-trigger-sticky"
            : hasActiveOptions
              ? "field-link-button search-options-trigger search-options-trigger-active"
              : "field-link-button search-options-trigger"
        }
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <span className="search-options-trigger-label">
          {placement === "sticky" ? "Search options" : "Additional search options"}
        </span>
      </button>

      {open ? (
        <div
          aria-label="Additional search options"
          className={
            placement === "sticky"
              ? "search-options-panel search-options-panel-sticky"
              : "search-options-panel"
          }
          id={panelId}
        >
          <label className="search-options-option">
            <input
              checked={props.scope === "all"}
              onChange={(event) =>
                props.onScopeChange(event.target.checked ? "all" : "default")
              }
              type="checkbox"
            />
            <span className="search-options-option-copy">
              <strong>Full catalog</strong>
              <span>Broaden search beyond the main add flow when you need it.</span>
            </span>
          </label>

          <label className="search-options-option">
            <input
              checked={props.loadAllLanguages}
              onChange={(event) =>
                props.onLoadAllLanguagesChange(event.target.checked)
              }
              type="checkbox"
            />
            <span className="search-options-option-copy">
              <strong>All printing languages</strong>
              <span>Load every available language when you open a selected card.</span>
            </span>
          </label>
        </div>
      ) : null}
    </div>
  );
}
