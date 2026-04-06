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
        <p className="panel-error">{props.viewError}</p>
      ) : null}

      <div className="audit-list">
        {!props.selectedInventoryRow ? (
          <PanelState
            body="Choose a collection to inspect its recent write activity."
            compact
            title="Pick a collection"
          />
        ) : props.viewStatus === "loading" && props.auditEvents.length === 0 ? (
          <PanelState
            body="Fetching the most recent audit entries for this collection."
            compact
            title="Loading activity"
            variant="loading"
          />
        ) : props.viewStatus === "error" && props.auditEvents.length === 0 ? (
          <PanelState
            body={props.viewError || "Could not load recent activity for this collection."}
            compact
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
              <p className="audit-meta">Actor: {formatAuditActor(event)}</p>
              <p className="audit-meta">Item: {event.item_id ? `#${event.item_id}` : "collection"}</p>
              {event.request_id ? <p className="audit-meta">Request: {event.request_id}</p> : null}
            </article>
          ))
        ) : (
          <PanelState
            body={getInventoryAuditEmptyMessage(props.selectedInventoryRow)}
            compact
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
          <h2>Audit Feed</h2>
        </div>
        <span className="muted-note">Latest 12 events</span>
      </div>

      {content}
    </section>
  );
}
