import type {
  BulkInventoryItemOperation,
  InventorySummary,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "../types";
import type { AsyncStatus, ItemMutationAction, NoticeTone } from "../uiTypes";
import { decimalToNumber, formatUsd, getInventoryCollectionEmptyMessage } from "../uiHelpers";
import type {
  InventoryTableFilters,
  InventoryTableFilterOptions,
  InventoryTableSortState,
} from "../tableViewHelpers";
import { CompactInventoryList } from "./CompactInventoryList";
import { InventoryTableView } from "./InventoryTableView";
import { OwnedItemCard } from "./OwnedItemCard";
import { PanelState } from "./ui/PanelState";
import { StatusPill } from "./ui/StatusPill";

type OwnedCollectionPanelState = {
  selectedInventoryRow: InventorySummary | null;
  collection: {
    busyItem: { itemId: number; action: ItemMutationAction } | null;
    expandedItemId: number | null;
    items: OwnedInventoryRow[];
    view: "compact" | "table" | "detailed";
    viewError: string | null;
    viewStatus: AsyncStatus;
  };
  table: {
    bulkTagsBusy: boolean;
    filterOptions: InventoryTableFilterOptions;
    filters: InventoryTableFilters;
    items: OwnedInventoryRow[];
    selectedItemIds: number[];
    sort: InventoryTableSortState;
  };
};

type OwnedCollectionPanelActions = {
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<void>;
  onDelete: (itemId: number, cardName: string) => Promise<void>;
  onNotice: (message: string, tone?: NoticeTone) => void;
  onCollectionViewChange: (nextView: "compact" | "table" | "detailed") => void;
  onExpandedItemChange: (itemId: number | null) => void;
  onTableSortChange: (nextSort: InventoryTableSortState) => void;
  onTableFiltersChange: (nextFilters: InventoryTableFilters) => void;
  onBulkTagsSubmit: (
    operation: BulkInventoryItemOperation,
    tags: string[],
  ) => Promise<boolean>;
  onOpenActivity: () => void;
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisibleItems: () => void;
  onClearVisibleSelectedItems: () => void;
  onClearSelectedItems: () => void;
};

export function OwnedCollectionPanel(props: {
  actions: OwnedCollectionPanelActions;
  state: OwnedCollectionPanelState;
}) {
  const totalEstimatedValue = props.state.collection.items.reduce(
    (sum, row) => sum + decimalToNumber(row.est_value),
    0,
  );
  const totalRows =
    props.state.selectedInventoryRow?.item_rows ?? props.state.collection.items.length;
  const totalCards = props.state.selectedInventoryRow?.total_cards ?? 0;

  return (
    <section className="panel">
      <div className="collection-panel-header">
        <div className="panel-heading collection-panel-heading">
          <div>
            <p className="section-kicker">Collection View</p>
            <h2>Owned Rows</h2>
          </div>
          <StatusPill status={props.state.collection.viewStatus} />
        </div>

        <div className="collection-header-controls">
          <div aria-label="Collection view" className="view-toggle" role="group">
            <button
              aria-pressed={props.state.collection.view === "compact"}
              className={
                props.state.collection.view === "compact"
                  ? "view-toggle-button view-toggle-button-active"
                  : "view-toggle-button"
              }
              onClick={() => props.actions.onCollectionViewChange("compact")}
              type="button"
            >
              Compact
            </button>
            <button
              aria-pressed={props.state.collection.view === "table"}
              className={
                props.state.collection.view === "table"
                  ? "view-toggle-button view-toggle-button-active"
                  : "view-toggle-button"
              }
              onClick={() => props.actions.onCollectionViewChange("table")}
              type="button"
            >
              Table
            </button>
            <button
              aria-pressed={props.state.collection.view === "detailed"}
              className={
                props.state.collection.view === "detailed"
                  ? "view-toggle-button view-toggle-button-active"
                  : "view-toggle-button"
              }
              onClick={() => props.actions.onCollectionViewChange("detailed")}
              type="button"
            >
              Detailed
            </button>
          </div>

          <button
            className="secondary-button"
            disabled={!props.state.selectedInventoryRow}
            onClick={props.actions.onOpenActivity}
            type="button"
          >
            View Activity
          </button>
        </div>
      </div>

      <div className="inventory-summary-bar">
        <div className="summary-chip">
          <span>Collection</span>
          <strong>{props.state.selectedInventoryRow?.display_name || "No collection"}</strong>
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

      {props.state.collection.viewError && props.state.collection.items.length ? (
        <p className="panel-error">{props.state.collection.viewError}</p>
      ) : null}

      <div className="collection-grid">
        {!props.state.selectedInventoryRow ? (
          <PanelState
            body="Choose a collection on the left to load owned rows and pricing."
            title="No collection selected"
          />
        ) : props.state.collection.viewStatus === "loading" &&
          props.state.collection.items.length === 0 ? (
          <PanelState
            body="Fetching owned rows, prices, and tags for this collection."
            title="Loading collection"
            variant="loading"
          />
        ) : props.state.collection.viewStatus === "error" &&
          props.state.collection.items.length === 0 ? (
          <PanelState
            body={
              props.state.collection.viewError ||
              "Could not load collection rows for this collection."
            }
            title="Collection unavailable"
            variant="error"
          />
        ) : props.state.collection.items.length ? (
          props.state.collection.view === "compact" ? (
            <CompactInventoryList
              busyItem={props.state.collection.busyItem}
              expandedItemId={props.state.collection.expandedItemId}
              items={props.state.collection.items}
              onDelete={props.actions.onDelete}
              onExpandedItemChange={props.actions.onExpandedItemChange}
              onNotice={props.actions.onNotice}
              onPatch={props.actions.onPatch}
            />
          ) : props.state.collection.view === "table" ? (
            <InventoryTableView
              allItemsCount={props.state.collection.items.length}
              bulkTagsBusy={props.state.table.bulkTagsBusy}
              filterOptions={props.state.table.filterOptions}
              filters={props.state.table.filters}
              items={props.state.table.items}
              onBulkTagsSubmit={props.actions.onBulkTagsSubmit}
              onClearSelection={props.actions.onClearSelectedItems}
              onClearVisibleSelection={props.actions.onClearVisibleSelectedItems}
              onFiltersChange={props.actions.onTableFiltersChange}
              onSelectAllVisible={props.actions.onSelectAllVisibleItems}
              onSortChange={props.actions.onTableSortChange}
              onToggleItemSelection={props.actions.onToggleItemSelection}
              selectedItemIds={props.state.table.selectedItemIds}
              sortState={props.state.table.sort}
            />
          ) : (
            props.state.collection.items.map((item) => (
              <OwnedItemCard
                busyAction={
                  props.state.collection.busyItem?.itemId === item.item_id
                    ? props.state.collection.busyItem.action
                    : null
                }
                item={item}
                key={item.item_id}
                onDelete={props.actions.onDelete}
                onNotice={props.actions.onNotice}
                onPatch={props.actions.onPatch}
              />
            ))
          )
        ) : (
          <PanelState
            body={getInventoryCollectionEmptyMessage(props.state.selectedInventoryRow)}
            title={`${props.state.selectedInventoryRow.display_name} is empty`}
          />
        )}
      </div>
    </section>
  );
}
