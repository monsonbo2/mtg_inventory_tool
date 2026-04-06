import type { InventoryAuditEvent, InventorySummary } from "../types";
import type { AsyncStatus } from "../uiTypes";
import { formatAuditAction, formatAuditActor, formatTimestamp, getInventoryAuditEmptyMessage } from "../uiHelpers";
import { PanelState } from "./ui/PanelState";

export function AuditFeed(props: {
  selectedInventoryRow: InventorySummary | null;
  viewStatus: AsyncStatus;
  viewError: string | null;
  auditEvents: InventoryAuditEvent[];
  embedded?: boolean;
}) {
  const content = (
    <>
      {props.viewError && props.auditEvents.length ? (
        <p className="panel-error">Could not refresh recent activity right now.</p>
      ) : null}

      <div className="audit-list">
        {!props.selectedInventoryRow ? (
          <PanelState
            body="Choose a collection to view its recent changes."
            compact
            eyebrow="Activity"
            title="Pick a collection"
          />
        ) : props.viewStatus === "loading" && props.auditEvents.length === 0 ? (
          <PanelState
            body="Loading recent activity for this collection."
            compact
            eyebrow="Activity"
            title="Loading activity"
            variant="loading"
          />
        ) : props.viewStatus === "error" && props.auditEvents.length === 0 ? (
          <PanelState
            body="Recent activity could not be loaded right now. Try again in a moment."
            compact
            eyebrow="Activity"
            title="Activity unavailable"
            variant="error"
          />
        ) : props.auditEvents.length ? (
          props.auditEvents.map((event) => (
            <article className="audit-card" key={event.id}>
              <div className="audit-card-topline">
                <span className="audit-action">{formatAuditAction(event.action)}</span>
                <span className="audit-time">{formatTimestamp(event.occurred_at)}</span>
              </div>
              <p className="audit-meta">By: {formatAuditActor(event)}</p>
              <p className="audit-meta">Card: {event.item_id ? `#${event.item_id}` : "collection"}</p>
            </article>
          ))
        ) : (
          <PanelState
            body={getInventoryAuditEmptyMessage(props.selectedInventoryRow)}
            compact
            eyebrow="Activity"
            title={
              props.selectedInventoryRow.total_cards === 0
                ? "No activity yet in this collection"
                : "No recent activity"
            }
          />
        )}
      </div>
    </>
  );

  if (props.embedded) {
    return <div className="audit-feed-embedded">{content}</div>;
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Recent Activity</p>
          <h2>Activity</h2>
        </div>
        <span className="muted-note">Latest 12 changes</span>
      </div>

      {content}
    </section>
  );
}
