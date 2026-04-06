import { useEffect, useEffectEvent, useId, useRef } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(", ");

function getFocusableElements(container: HTMLElement | null) {
  if (!container) {
    return [];
  }

  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) =>
      !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true",
  );
}

export function ModalDialog(props: {
  isOpen: boolean;
  kicker?: string;
  title: string;
  subtitle?: string;
  size?: "default" | "wide";
  onClose: () => void;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  const subtitleId = useId();
  const handleClose = useEffectEvent(() => {
    props.onClose();
  });

  useEffect(() => {
    if (!props.isOpen) {
      return;
    }

    previousFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        handleClose();
        return;
      }

      if (event.key !== "Tab") {
        return;
      }

      const focusableElements = getFocusableElements(dialogRef.current);
      if (!focusableElements.length) {
        event.preventDefault();
        dialogRef.current?.focus();
        return;
      }

      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      const activeElement = document.activeElement;

      if (event.shiftKey) {
        if (activeElement === firstElement || activeElement === dialogRef.current) {
          event.preventDefault();
          lastElement.focus();
        }
        return;
      }

      if (activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    function focusInitialElement() {
      const preferredFocusElement =
        dialogRef.current?.querySelector<HTMLElement>("[data-autofocus]") ?? null;
      const firstFocusableElement = getFocusableElements(dialogRef.current)[0];
      (
        preferredFocusElement ??
        firstFocusableElement ??
        closeButtonRef.current ??
        dialogRef.current
      )?.focus();
    }

    focusInitialElement();
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);

      if (previousFocusRef.current?.isConnected) {
        previousFocusRef.current.focus();
      }
    };
  }, [props.isOpen]);

  if (!props.isOpen) {
    return null;
  }

  const dialog = (
    <div
      className="modal-backdrop"
      data-testid="modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          props.onClose();
        }
      }}
    >
      <section
        aria-describedby={props.subtitle ? subtitleId : undefined}
        aria-labelledby={titleId}
        aria-modal="true"
        className={
          props.size === "wide" ? "modal-dialog modal-dialog-wide" : "modal-dialog"
        }
        role="dialog"
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="modal-dialog-header">
          <div>
            {props.kicker ? <p className="section-kicker">{props.kicker}</p> : null}
            <h2 id={titleId}>{props.title}</h2>
            {props.subtitle ? (
              <p className="modal-dialog-subtitle" id={subtitleId}>
                {props.subtitle}
              </p>
            ) : null}
          </div>
          <button
            aria-label="Close dialog"
            className="secondary-button"
            onClick={props.onClose}
            ref={closeButtonRef}
            type="button"
          >
            Close
          </button>
        </div>

        <div className="modal-dialog-body">{props.children}</div>
      </section>
    </div>
  );

  return createPortal(dialog, document.body);
}
