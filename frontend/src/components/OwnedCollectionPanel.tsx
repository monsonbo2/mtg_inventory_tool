import type { ReactNode } from "react";

import type {
  BulkInventoryItemMutationRequest,
  InventoryCreateRequest,
  InventorySummary,
  InventoryTransferMode,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "../types";
import type {
  AsyncStatus,
  InventoryCreateResult,
  ItemMutationAction,
  MutationOutcome,
  NoticeTone,
} from "../uiTypes";
import { decimalToNumber, formatUsd } from "../uiHelpers";
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
  selectedInventoryCanWrite: boolean;
  collection: {
    browsePage: number;
    browsePageCount: number;
    browseVisibleLimit: number;
    browseVisibleLimitOptions: number[];
    busyItem: { itemId: number; action: ItemMutationAction } | null;
    filteredItemsCount: number;
    searchQuery: string;
    detailModalItemId: number | null;
    focusedItemId: number | null;
    items: OwnedInventoryRow[];
    visibleItems: OwnedInventoryRow[];
    view: "browse" | "table";
    viewError: string | null;
    viewStatus: AsyncStatus;
  };
  table: {
    allItemsCount: number;
    availableTargetInventories: InventorySummary[];
    availableCopyTargetInventories: InventorySummary[];
    availableMoveTargetInventories: InventorySummary[];
    bulkMutationBusy: boolean;
    canBulkEditSelectedInventory: boolean;
    canCopyFromSelectedInventory: boolean;
    canMoveFromSelectedInventory: boolean;
    createInventoryBusy: boolean;
    filterOptions: InventoryTableFilterOptions;
    filters: InventoryTableFilters;
    items: OwnedInventoryRow[];
    page: number;
    pageCount: number;
    selectedItemIds: number[];
    sort: InventoryTableSortState;
    transferBusy: InventoryTransferMode | null;
    visibleLimit: number;
    visibleLimitOptions: number[];
  };
};

type OwnedCollectionPanelActions = {
  onPatch: (
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) => Promise<MutationOutcome>;
  onDelete: (itemId: number, cardName: string) => Promise<MutationOutcome>;
  onNotice: (message: string, tone?: NoticeTone) => void;
  onCreateInventory: (
    payload: InventoryCreateRequest,
  ) => Promise<InventoryCreateResult>;
  onFocusImport: () => void;
  onFocusSearch: () => void;
  onBrowsePageChange: (nextPage: number) => void;
  onBrowseVisibleLimitChange: (nextLimit: number) => void;
  onCollectionViewChange: (nextView: "browse" | "table") => void;
  onCollectionSearchQueryChange: (nextQuery: string) => void;
  onCloseItemDetails: () => void;
  onOpenItemDetails: (itemId: number) => void;
  onTableSortChange: (nextSort: InventoryTableSortState) => void;
  onTableFiltersChange: (nextFilters: InventoryTableFilters) => void;
  onTablePageChange: (nextPage: number) => void;
  onTableVisibleLimitChange: (nextLimit: number) => void;
  onBulkMutationSubmit: (
    payload: BulkInventoryItemMutationRequest,
  ) => Promise<boolean>;
  onOpenActivity: () => void;
  onSelectTableItem: (
    itemId: number,
    options?: { additive?: boolean; range?: boolean },
  ) => void;
  onSelectAllCollectionItems: () => void;
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisibleItems: () => void;
  onTransferItems: (options: {
    mode: InventoryTransferMode;
    targetInventorySlug: string | null;
    targetInventoryLabel?: string | null;
  }) => Promise<boolean>;
  onClearVisibleSelectedItems: () => void;
  onClearSelectedItems: () => void;
};

export function OwnedCollectionPanel(props: {
  actions: OwnedCollectionPanelActions;
  state: OwnedCollectionPanelState;
}) {
  const collectionDisplayState = !props.state.selectedInventoryRow
    ? "unselected"
    : props.state.collection.viewStatus === "loading" &&
        props.state.collection.items.length === 0
      ? "loading"
      : props.state.collection.viewStatus === "error" &&
          props.state.collection.items.length === 0
        ? "error"
        : props.state.collection.items.length === 0
          ? "empty"
          : props.state.collection.visibleItems.length === 0
            ? "search_empty"
            : "ready";
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
  const activeViewLimit =
    props.state.collection.view === "browse"
      ? props.state.collection.browseVisibleLimit
      : props.state.table.visibleLimit;
  const activeViewLimitOptions =
    props.state.collection.view === "browse"
      ? props.state.collection.browseVisibleLimitOptions
      : props.state.table.visibleLimitOptions;
  const activeViewCount =
    props.state.collection.view === "browse"
      ? props.state.collection.filteredItemsCount
      : props.state.table.allItemsCount;
  const activePage =
    props.state.collection.view === "browse"
      ? props.state.collection.browsePage
      : props.state.table.page;
  const activePageCount =
    props.state.collection.view === "browse"
      ? props.state.collection.browsePageCount
      : props.state.table.pageCount;
  const activeShownCount =
    props.state.collection.view === "browse"
      ? props.state.collection.visibleItems.length
      : props.state.table.items.length;
  const activeLimitLabel =
    props.state.collection.view === "browse" ? "Browse entries shown" : "Table rows shown";
  const activeLimitSummary =
    activeViewCount > activeShownCount
      ? `Showing ${activeShownCount} of ${activeViewCount} entries in ${props.state.collection.view}. Use page controls or increase the limit to see more.`
      : activeViewCount > 0
        ? `Showing all ${activeViewCount} entr${activeViewCount === 1 ? "y" : "ies"} in ${props.state.collection.view}.`
        : `No entries currently match this ${props.state.collection.view} view.`;
  const showViewControls =
    collectionDisplayState === "ready" || collectionDisplayState === "search_empty";
  const showActivityButton =
    collectionDisplayState === "ready" || collectionDisplayState === "search_empty";
  const showCollectionMetrics = showViewControls;
  const showCollectionSearchRow = showViewControls;
  const showSummaryBar = showCollectionMetrics;
  const collectionPanelTitle = props.state.selectedInventoryRow?.display_name || "No collection selected";
  let collectionContent: ReactNode;

  switch (collectionDisplayState) {
    case "unselected":
      collectionContent = (
        <PanelState
          body="Choose a collection on the left to see your cards and values."
          eyebrow="Collection"
          title="No collection selected"
        />
      );
      break;
    case "loading":
      collectionContent = (
        <PanelState
          body="Loading cards, values, and tags for this collection."
          eyebrow="Collection"
          title="Loading collection"
          variant="loading"
        />
      );
      break;
    case "error":
      collectionContent = (
        <PanelState
          body="This collection could not be loaded right now. Try refreshing and opening it again."
          eyebrow="Collection"
          title="Collection unavailable"
          variant="error"
        />
      );
      break;
    case "empty":
      if (!props.state.selectedInventoryRow) {
        collectionContent = (
          <PanelState
            body="Choose a collection on the left to see your cards and values."
            eyebrow="Collection"
            title="No collection selected"
          />
        );
        break;
      }
      const emptyCollectionBody = props.state.selectedInventoryCanWrite
        ? "Use search to add the first card to this collection, or import a list if you already have one ready."
        : "Use search to review printings, or import a list into another collection to keep building inventory.";
      collectionContent = (
        <PanelState
          actions={
            <>
              <button
                className="primary-button"
                onClick={props.actions.onFocusSearch}
                type="button"
              >
                {props.state.selectedInventoryCanWrite ? "Add first card" : "Find cards"}
              </button>
              <button
                className="secondary-button"
                onClick={props.actions.onFocusImport}
                type="button"
              >
                Import a list
              </button>
            </>
          }
          body={emptyCollectionBody}
          eyebrow="Collection"
          title={`${props.state.selectedInventoryRow.display_name} is empty`}
        />
      );
      break;
    case "search_empty":
      collectionContent = (
        <div className="collection-search-empty">
          <strong>No matching cards</strong>
          <span>
            Try a different card name or clear the collection search to bring
            entries back into view.
          </span>
        </div>
      );
      break;
    case "ready":
      collectionContent =
        props.state.collection.view === "table" ? (
          <InventoryTableView
            allItemsCount={props.state.table.allItemsCount}
            availableCopyTargetInventories={props.state.table.availableCopyTargetInventories}
            availableMoveTargetInventories={props.state.table.availableMoveTargetInventories}
            availableTargetInventories={props.state.table.availableTargetInventories}
            bulkMutationBusy={props.state.table.bulkMutationBusy}
            canBulkEditSelectedInventory={props.state.table.canBulkEditSelectedInventory}
            canCopyFromSelectedInventory={props.state.table.canCopyFromSelectedInventory}
            canMoveFromSelectedInventory={props.state.table.canMoveFromSelectedInventory}
            collectionItemCount={props.state.collection.items.length}
            createInventoryBusy={props.state.table.createInventoryBusy}
            filterOptions={props.state.table.filterOptions}
            filters={props.state.table.filters}
            items={props.state.table.items}
            onBulkMutationSubmit={props.actions.onBulkMutationSubmit}
            onClearSelection={props.actions.onClearSelectedItems}
            onClearVisibleSelection={props.actions.onClearVisibleSelectedItems}
            onCreateInventory={props.actions.onCreateInventory}
            onFiltersChange={props.actions.onTableFiltersChange}
            onOpenDetails={props.actions.onOpenItemDetails}
            onSelectAllCollection={props.actions.onSelectAllCollectionItems}
            onSelectItem={props.actions.onSelectTableItem}
            onSelectAllVisible={props.actions.onSelectAllVisibleItems}
            onSortChange={props.actions.onTableSortChange}
            onTransferItems={props.actions.onTransferItems}
            onToggleItemSelection={props.actions.onToggleItemSelection}
            selectedItemIds={props.state.table.selectedItemIds}
            sortState={props.state.table.sort}
            transferBusy={props.state.table.transferBusy}
          />
        ) : (
          <CompactInventoryList
            busyItem={props.state.collection.busyItem}
            editable={props.state.selectedInventoryCanWrite}
            items={props.state.collection.visibleItems}
            onOpenDetails={props.actions.onOpenItemDetails}
            onPatch={props.actions.onPatch}
          />
        );
      break;
  }

  return (
    <section className="panel">
      <div className="collection-panel-header">
        <div className="panel-heading collection-panel-heading">
          <div>
            <p className="section-kicker">Your Collection</p>
            <h2>{collectionPanelTitle}</h2>
          </div>
          <StatusPill status={props.state.collection.viewStatus} />
        </div>

        {showViewControls || showActivityButton ? (
          <div className="collection-header-controls">
            {showViewControls ? (
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
              </div>
            ) : null}

            {showActivityButton ? (
              <button
                className="utility-button"
                onClick={props.actions.onOpenActivity}
                type="button"
              >
                Recent Activity
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {showSummaryBar ? (
        <div className="inventory-summary-bar">
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
      ) : null}

      {showCollectionSearchRow ? (
        <div className="collection-search-row">
          <div className="collection-display-controls">
            <div className="collection-display-toolbar">
              <label className="field collection-limit-field">
                <span>{activeLimitLabel}</span>
                <select
                  className="text-input"
                  onChange={(event) => {
                    const nextLimit = Number.parseInt(event.target.value, 10);
                    if (props.state.collection.view === "browse") {
                      props.actions.onBrowseVisibleLimitChange(nextLimit);
                      return;
                    }
                    props.actions.onTableVisibleLimitChange(nextLimit);
                  }}
                  value={String(activeViewLimit)}
                >
                  {activeViewLimitOptions.map((limit) => (
                    <option key={limit} value={limit}>
                      {limit}
                    </option>
                  ))}
                </select>
              </label>

              <div aria-label={`${props.state.collection.view} pagination`} className="collection-pagination">
                <button
                  className="secondary-button"
                  disabled={activePage <= 1 || activeViewCount === 0}
                  onClick={() => {
                    if (props.state.collection.view === "browse") {
                      props.actions.onBrowsePageChange(activePage - 1);
                      return;
                    }
                    props.actions.onTablePageChange(activePage - 1);
                  }}
                  type="button"
                >
                  Previous
                </button>
                <span className="collection-page-indicator">
                  Page {activePage} of {activePageCount}
                </span>
                <button
                  className="secondary-button"
                  disabled={activePage >= activePageCount || activeViewCount === 0}
                  onClick={() => {
                    if (props.state.collection.view === "browse") {
                      props.actions.onBrowsePageChange(activePage + 1);
                      return;
                    }
                    props.actions.onTablePageChange(activePage + 1);
                  }}
                  type="button"
                >
                  Next
                </button>
              </div>
            </div>
            <p className="collection-limit-summary">{activeLimitSummary}</p>
          </div>

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

      {props.state.collection.viewError && showViewControls ? (
        <p className="panel-error">Could not refresh this collection right now.</p>
      ) : null}

      {showViewControls && !props.state.selectedInventoryCanWrite ? (
        <p className="panel-hint">
          This collection is read-only. You can browse cards and copy selected table entries, but
          edits and row removal are disabled.
        </p>
      ) : null}

      <div className="collection-grid">
        {collectionContent}
      </div>

      {detailModalItem ? (
        <ModalDialog
          isOpen
          kicker="Collection Entry"
          onClose={props.actions.onCloseItemDetails}
          size="wide"
          subtitle={
            props.state.selectedInventoryCanWrite
              ? "Review and edit this card without leaving Browse mode."
              : "Review this card without leaving Browse mode. This collection is read-only."
          }
          title="Card details"
        >
          <OwnedItemCard
            busyAction={
              props.state.collection.busyItem?.itemId === detailModalItem.item_id
                ? props.state.collection.busyItem.action
                : null
            }
            editable={props.state.selectedInventoryCanWrite}
            item={detailModalItem}
            onDelete={async (itemId: number, cardName: string) => {
              const result = await props.actions.onDelete(itemId, cardName);
              if (result !== "failed") {
                props.actions.onCloseItemDetails();
              }
              return result;
            }}
            onNotice={props.actions.onNotice}
            onPatch={props.actions.onPatch}
          />
        </ModalDialog>
      ) : null}
    </section>
  );
}
