import type { InventorySummary, OwnedInventoryRow, PatchInventoryItemRequest } from "../types";
import type { AsyncStatus, FinishSupportState, ItemMutationAction, NoticeTone } from "../uiTypes";
import { decimalToNumber, formatUsd, getInventoryCollectionEmptyMessage } from "../uiHelpers";
import { OwnedItemCard } from "./OwnedItemCard";
import { PanelState } from "./ui/PanelState";
import { StatusPill } from "./ui/StatusPill";

export function OwnedCollectionPanel(props: {
  selectedInventoryRow: InventorySummary | null;
  viewStatus: AsyncStatus;
  viewError: string | null;
  items: OwnedInventoryRow[];
  finishSupportByCard: Record<string, FinishSupportState>;
  busyItem: { itemId: number; action: ItemMutationAction } | null;
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<void>;
  onDelete: (itemId: number, cardName: string) => Promise<void>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const totalEstimatedValue = props.items.reduce(
    (sum, row) => sum + decimalToNumber(row.est_value),
    0,
  );

  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Collection View</p>
          <h2>Owned Rows</h2>
        </div>
        <StatusPill status={props.viewStatus} />
      </div>

      <div className="inventory-summary-bar">
        <div className="summary-chip">
          <span>Inventory</span>
          <strong>{props.selectedInventoryRow?.display_name || "No inventory"}</strong>
        </div>
        <div className="summary-chip">
          <span>Total cards</span>
          <strong>{props.selectedInventoryRow?.total_cards ?? 0}</strong>
        </div>
        <div className="summary-chip">
          <span>Estimated value</span>
          <strong>{formatUsd(totalEstimatedValue)}</strong>
        </div>
      </div>

      {props.viewError && props.items.length ? <p className="panel-error">{props.viewError}</p> : null}

      <div className="collection-grid">
        {!props.selectedInventoryRow ? (
          <PanelState
            body="Choose an inventory on the left to load owned rows and pricing."
            title="No inventory selected"
          />
        ) : props.viewStatus === "loading" && props.items.length === 0 ? (
          <PanelState
            body="Fetching owned rows, prices, and tags for this inventory."
            title="Loading collection"
            variant="loading"
          />
        ) : props.viewStatus === "error" && props.items.length === 0 ? (
          <PanelState
            body={props.viewError || "Could not load collection rows for this inventory."}
            title="Collection unavailable"
            variant="error"
          />
        ) : props.items.length ? (
          props.items.map((item) => (
            <OwnedItemCard
              busyAction={props.busyItem?.itemId === item.item_id ? props.busyItem.action : null}
              finishSupport={props.finishSupportByCard[item.scryfall_id] || null}
              item={item}
              key={item.item_id}
              onDelete={props.onDelete}
              onNotice={props.onNotice}
              onPatch={props.onPatch}
            />
          ))
        ) : (
          <PanelState
            body={getInventoryCollectionEmptyMessage(props.selectedInventoryRow)}
            title={`${props.selectedInventoryRow.display_name} is empty`}
          />
        )}
      </div>
    </section>
  );
}
