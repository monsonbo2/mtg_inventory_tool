import type {
  BulkInventoryItemMutationRequest,
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
import { ModalDialog } from "./ui/ModalDialog";
import { PanelState } from "./ui/PanelState";
import { StatusPill } from "./ui/StatusPill";

type OwnedCollectionPanelState = {
  selectedInventoryRow: InventorySummary | null;
  collection: {
    busyItem: { itemId: number; action: ItemMutationAction } | null;
    searchQuery: string;
    detailModalItemId: number | null;
    focusedItemId: number | null;
    items: OwnedInventoryRow[];
    visibleItems: OwnedInventoryRow[];
    view: "browse" | "table" | "detailed";
    viewError: string | null;
    viewStatus: AsyncStatus;
  };
  table: {
    bulkMutationBusy: boolean;
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
  onCollectionViewChange: (nextView: "browse" | "table" | "detailed") => void;
  onCollectionSearchQueryChange: (nextQuery: string) => void;
  onCloseItemDetails: () => void;
  onOpenItemDetails: (itemId: number) => void;
  onTableSortChange: (nextSort: InventoryTableSortState) => void;
  onTableFiltersChange: (nextFilters: InventoryTableFilters) => void;
  onBulkMutationSubmit: (
    payload: BulkInventoryItemMutationRequest,
  ) => Promise<boolean>;
  onOpenActivity: () => void;
  onSelectTableItem: (
    itemId: number,
    options?: { additive?: boolean; range?: boolean },
  ) => void;
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisibleItems: () => void;
  onClearVisibleSelectedItems: () => void;
  onClearSelectedItems: () => void;
};

export function OwnedCollectionPanel(props: {
  actions: OwnedCollectionPanelActions;
  state: OwnedCollectionPanelState;
}) {
  const detailModalItem =
    props.state.collection.detailModalItemId === null
      ? null
      : props.state.collection.items.find(
          (item) => item.item_id === props.state.collection.detailModalItemId,
        ) ?? null;
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
            <p className="section-kicker">Your Collection</p>
            <h2>Collection</h2>
          </div>
          <StatusPill status={props.state.collection.viewStatus} />
        </div>

        <div className="collection-header-controls">
          <div aria-label="Collection view" className="view-toggle" role="group">
            <button
              aria-pressed={props.state.collection.view === "browse"}
              className={
                props.state.collection.view === "browse"
                  ? "view-toggle-button view-toggle-button-active"
                  : "view-toggle-button"
              }
              onClick={() => props.actions.onCollectionViewChange("browse")}
              type="button"
            >
              Browse
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
            Recent Activity
          </button>
        </div>
      </div>

      <div className="inventory-summary-bar">
        <div className="summary-chip">
          <span>Collection</span>
          <strong>{props.state.selectedInventoryRow?.display_name || "No collection"}</strong>
        </div>
        <div className="summary-chip">
          <span>Entries</span>
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

      {props.state.selectedInventoryRow ? (
        <div className="collection-search-row">
          <label className="field collection-search-field">
            <span>Search this collection</span>
            <input
              className="text-input"
              onChange={(event) =>
                props.actions.onCollectionSearchQueryChange(event.target.value)
              }
              placeholder="e.g. Lightning Bolt"
              type="text"
              value={props.state.collection.searchQuery}
            />
          </label>
        </div>
      ) : null}

      {props.state.collection.viewError && props.state.collection.items.length ? (
        <p className="panel-error">Could not refresh this collection right now.</p>
      ) : null}

      <div className="collection-grid">
        {!props.state.selectedInventoryRow ? (
          <PanelState
            body="Choose a collection on the left to see your cards and values."
            eyebrow="Collection"
            title="No collection selected"
          />
        ) : props.state.collection.viewStatus === "loading" &&
          props.state.collection.items.length === 0 ? (
          <PanelState
            body="Loading cards, values, and tags for this collection."
            eyebrow="Collection"
            title="Loading collection"
            variant="loading"
          />
        ) : props.state.collection.viewStatus === "error" &&
          props.state.collection.items.length === 0 ? (
          <PanelState
            body="This collection could not be loaded right now. Try refreshing and opening it again."
            eyebrow="Collection"
            title="Collection unavailable"
            variant="error"
          />
        ) : props.state.collection.items.length ? (
          props.state.collection.visibleItems.length ? (
            props.state.collection.view === "browse" ? (
              <CompactInventoryList
                busyItem={props.state.collection.busyItem}
                items={props.state.collection.visibleItems}
                onOpenDetails={props.actions.onOpenItemDetails}
                onPatch={props.actions.onPatch}
              />
            ) : props.state.collection.view === "table" ? (
              <InventoryTableView
                allItemsCount={props.state.collection.items.length}
                bulkMutationBusy={props.state.table.bulkMutationBusy}
                filterOptions={props.state.table.filterOptions}
                filters={props.state.table.filters}
                items={props.state.table.items}
                onBulkMutationSubmit={props.actions.onBulkMutationSubmit}
                onClearSelection={props.actions.onClearSelectedItems}
                onClearVisibleSelection={props.actions.onClearVisibleSelectedItems}
                onFiltersChange={props.actions.onTableFiltersChange}
                onOpenDetails={props.actions.onOpenItemDetails}
                onSelectItem={props.actions.onSelectTableItem}
                onSelectAllVisible={props.actions.onSelectAllVisibleItems}
                onSortChange={props.actions.onTableSortChange}
                onToggleItemSelection={props.actions.onToggleItemSelection}
                selectedItemIds={props.state.table.selectedItemIds}
                sortState={props.state.table.sort}
              />
            ) : (
              props.state.collection.visibleItems.map((item) => (
                <OwnedItemCard
                  busyAction={
                    props.state.collection.busyItem?.itemId === item.item_id
                      ? props.state.collection.busyItem.action
                      : null
                  }
                  item={item}
                  key={item.item_id}
                  focused={props.state.collection.focusedItemId === item.item_id}
                  onDelete={props.actions.onDelete}
                  onNotice={props.actions.onNotice}
                  onPatch={props.actions.onPatch}
                />
              ))
            )
          ) : (
            <div className="collection-search-empty">
              <strong>No matching cards</strong>
              <span>
                Try a different card name or clear the collection search to bring
                entries back into view.
              </span>
            </div>
          )
        ) : (
          <PanelState
            body={getInventoryCollectionEmptyMessage(props.state.selectedInventoryRow)}
            eyebrow="Collection"
            title={`${props.state.selectedInventoryRow.display_name} is empty`}
          />
        )}
      </div>

      {detailModalItem ? (
        <ModalDialog
          isOpen
          kicker="Collection Entry"
          onClose={props.actions.onCloseItemDetails}
          size="wide"
          subtitle="Review and edit this card without leaving Browse mode."
          title="Card details"
        >
          <OwnedItemCard
            busyAction={
              props.state.collection.busyItem?.itemId === detailModalItem.item_id
                ? props.state.collection.busyItem.action
                : null
            }
            item={detailModalItem}
            onDelete={async (itemId, cardName) => {
              await props.actions.onDelete(itemId, cardName);
              props.actions.onCloseItemDetails();
            }}
            onNotice={props.actions.onNotice}
            onPatch={props.actions.onPatch}
          />
        </ModalDialog>
      ) : null}
    </section>
  );
}
