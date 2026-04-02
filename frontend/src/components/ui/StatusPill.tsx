import type { AsyncStatus } from "../../uiTypes";
import { formatStatusLabel } from "../../uiHelpers";

export function StatusPill(props: { status: AsyncStatus }) {
  return <span className={`status-pill status-${props.status}`}>{formatStatusLabel(props.status)}</span>;
}
