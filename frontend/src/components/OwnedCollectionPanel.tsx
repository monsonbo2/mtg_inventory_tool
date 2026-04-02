import type { InventorySummary, OwnedInventoryRow, PatchInventoryItemRequest } from "../types";
import type { AsyncStatus, FinishSupportState, ItemMutationAction, NoticeTone } from "../uiTypes";
import { decimalToNumber, formatUsd, getInventoryCollectionEmptyMessage } from "../uiHelpers";
import { CompactInventoryList } from "./CompactInventoryList";
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
  collectionView: "compact" | "detailed";
  onCollectionViewChange: (nextView: "compact" | "detailed") => void;
  expandedItemId: number | null;
  onExpandedItemChange: (itemId: number | null) => void;
  onOpenActivity: () => void;
}) {
  const totalEstimatedValue = props.items.reduce(
    (sum, row) => sum + decimalToNumber(row.est_value),
    0,
  );
  const totalRows = props.selectedInventoryRow?.item_rows ?? props.items.length;
  const totalCards = props.selectedInventoryRow?.total_cards ?? 0;

  return (
    <section className="panel">
      <div className="collection-panel-header">
        <div className="panel-heading collection-panel-heading">
          <div>
            <p className="section-kicker">Collection View</p>
            <h2>Owned Rows</h2>
          </div>
          <StatusPill status={props.viewStatus} />
        </div>

        <div className="collection-header-controls">
          <div aria-label="Collection view" className="view-toggle" role="group">
            <button
              aria-pressed={props.collectionView === "compact"}
              className={
                props.collectionView === "compact"
                  ? "view-toggle-button view-toggle-button-active"
                  : "view-toggle-button"
              }
              onClick={() => props.onCollectionViewChange("compact")}
              type="button"
            >
              Compact
            </button>
            <button
              aria-pressed={props.collectionView === "detailed"}
              className={
                props.collectionView === "detailed"
                  ? "view-toggle-button view-toggle-button-active"
                  : "view-toggle-button"
              }
              onClick={() => props.onCollectionViewChange("detailed")}
              type="button"
            >
              Detailed
            </button>
          </div>

          <button
            className="secondary-button"
            disabled={!props.selectedInventoryRow}
            onClick={props.onOpenActivity}
            type="button"
          >
            View Activity
          </button>
        </div>
      </div>

      <div className="inventory-summary-bar">
        <div className="summary-chip">
          <span>Inventory</span>
          <strong>{props.selectedInventoryRow?.display_name || "No inventory"}</strong>
        </div>
        <div className="summary-chip">
          <span>Total rows</span>
          <strong>{totalRows}</strong>
        </div>
        <div className="summary-chip">
          <span>Total cards</span>
          <strong>{totalCards}</strong>
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
          props.collectionView === "compact" ? (
            <CompactInventoryList
              busyItem={props.busyItem}
              expandedItemId={props.expandedItemId}
              finishSupportByCard={props.finishSupportByCard}
              items={props.items}
              onDelete={props.onDelete}
              onExpandedItemChange={props.onExpandedItemChange}
              onNotice={props.onNotice}
              onPatch={props.onPatch}
            />
          ) : (
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
          )
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
