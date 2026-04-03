import type { NoticeState } from "../../uiTypes";

export function NoticeToast(props: {
  notice: NoticeState;
  onDismiss: () => void;
}) {
  return (
    <div
      aria-live="polite"
      className={`notice-toast notice-toast-${props.notice.tone}`}
      role="status"
    >
      <p className="notice-toast-message">{props.notice.message}</p>
      <button
        aria-label="Dismiss notification"
        className="notice-toast-dismiss"
        onClick={props.onDismiss}
        type="button"
      >
        Dismiss
      </button>
    </div>
  );
}
