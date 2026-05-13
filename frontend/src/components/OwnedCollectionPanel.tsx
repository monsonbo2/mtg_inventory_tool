import { useEffect, useRef, useState } from "react";
import type { FormEvent, KeyboardEvent, ReactNode } from "react";

import type {
  BulkInventoryItemMutationRequest,
  InventoryCreateRequest,
  InventoryDuplicateRequest,
  InventoryPriceProvider,
  InventorySummary,
  InventoryTransferMode,
  InventoryTransferResponse,
  OwnedInventoryRow,
  PatchInventoryItemRequest,
} from "../types";
import type {
  AsyncStatus,
  InventoryCreateResult,
  InventoryDuplicateResult,
  ItemMutationAction,
  MutationOutcome,
  NoticeTone,
} from "../uiTypes";
import {
  PRICE_PROVIDER_OPTIONS,
  decimalToNumber,
  formatUsd,
  getCurrentRetailValueLabel,
  getPriceProviderOption,
  normalizeInventorySlugInput,
} from "../uiHelpers";
import type {
  InventoryTableFilters,
  InventoryTableFilterOptions,
  InventoryTableSortState,
} from "../tableViewHelpers";
import { CompactInventoryList } from "./CompactInventoryList";
import { InventoryAccessDialog } from "./InventoryAccessDialog";
import { InventoryTableView } from "./InventoryTableView";
import { OwnedItemCard } from "./OwnedItemCard";
import { ModalDialog } from "./ui/ModalDialog";
import { PanelState } from "./ui/PanelState";

type OwnedCollectionPanelState = {
  selectedInventoryRow: InventorySummary | null;
  canExportSelectedInventory: boolean;
  canManageShareSelectedInventory: boolean;
  duplicateInventoryBusy: boolean;
  exportInventoryBusy: boolean;
  priceProvider: InventoryPriceProvider;
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
    collectionItemCount: number;
    createInventoryBusy: boolean;
    filterOptions: InventoryTableFilterOptions;
    filters: InventoryTableFilters;
    items: OwnedInventoryRow[];
    page: number;
    pageCount: number;
    selectedItemIds: number[];
    sort: InventoryTableSortState;
    transferBusy: InventoryTransferMode | null;
    viewError: string | null;
    viewStatus: AsyncStatus;
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
  onDuplicateInventory: (
    sourceInventorySlug: string | null,
    sourceInventoryLabel: string | null | undefined,
    payload: InventoryDuplicateRequest,
  ) => Promise<InventoryDuplicateResult>;
  onExportCsv: () => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
  onCreateInventory: (
    payload: InventoryCreateRequest,
  ) => Promise<InventoryCreateResult>;
  onCreateTransferTargetInventory: (
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
  onPriceProviderChange: (nextProvider: InventoryPriceProvider) => void;
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
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisibleItems: () => void;
  onTransferItems: (options: {
    mode: InventoryTransferMode;
    targetInventorySlug: string | null;
    targetInventoryLabel?: string | null;
  }) => Promise<boolean>;
  onPreviewTransferItems: (options: {
    mode: InventoryTransferMode;
    targetInventorySlug: string | null;
    targetInventoryLabel?: string | null;
  }) => Promise<InventoryTransferResponse | null>;
  onClearVisibleSelectedItems: () => void;
  onClearSelectedItems: () => void;
  onReloadInventorySummaries: (preferredSlug?: string | null) => Promise<boolean>;
};

function normalizeDuplicateSlugDraft(value: string) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/-+/g, "-");
}

export function OwnedCollectionPanel(props: {
  actions: OwnedCollectionPanelActions;
  state: OwnedCollectionPanelState;
}) {
  const [accessDialogOpen, setAccessDialogOpen] = useState(false);
  const [duplicateDialogOpen, setDuplicateDialogOpen] = useState(false);
  const [duplicateDisplayName, setDuplicateDisplayName] = useState("");
  const [duplicateSlug, setDuplicateSlug] = useState("");
  const [duplicateDescription, setDuplicateDescription] = useState("");
  const [duplicateSlugTouched, setDuplicateSlugTouched] = useState(false);
  const [showDuplicateSlugField, setShowDuplicateSlugField] = useState(false);
  const [duplicateFormError, setDuplicateFormError] = useState<string | null>(null);
  const [priceProviderMenuOpen, setPriceProviderMenuOpen] = useState(false);
  const priceProviderMenuRef = useRef<HTMLDivElement | null>(null);
  const priceProviderTriggerRef = useRef<HTMLButtonElement | null>(null);
  const priceProviderOptionRefs = useRef<Array<HTMLButtonElement | null>>([]);
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
  const detailModalItems =
    props.state.collection.view === "table"
      ? [props.state.table.items, props.state.collection.items]
      : [props.state.collection.items, props.state.table.items];
  const detailModalItem =
    props.state.collection.detailModalItemId === null
      ? null
      : detailModalItems
          .flat()
          .find((item) => item.item_id === props.state.collection.detailModalItemId) ??
        null;
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
  const showExportButton =
    props.state.selectedInventoryRow !== null && props.state.canExportSelectedInventory;
  const showDuplicateButton =
    props.state.selectedInventoryRow !== null && showActivityButton;
  const showCollectionMetrics = showViewControls;
  const showCollectionSearchRow =
    showViewControls && props.state.collection.view === "browse";
  const showSummaryBar = showCollectionMetrics;
  const collectionPanelTitle = props.state.selectedInventoryRow?.display_name || "No collection selected";
  const selectedPriceProviderOption = getPriceProviderOption(
    props.state.priceProvider,
  );
  const selectedPriceProviderIndex = Math.max(
    PRICE_PROVIDER_OPTIONS.findIndex(
      (option) => option.value === props.state.priceProvider,
    ),
    0,
  );
  let collectionContent: ReactNode;

  useEffect(() => {
    if (!priceProviderMenuOpen) {
      return;
    }

    function handleDocumentPointerDown(event: PointerEvent) {
      if (
        priceProviderMenuRef.current?.contains(event.target as Node | null)
      ) {
        return;
      }
      setPriceProviderMenuOpen(false);
    }

    document.addEventListener("pointerdown", handleDocumentPointerDown);
    return () => {
      document.removeEventListener("pointerdown", handleDocumentPointerDown);
    };
  }, [priceProviderMenuOpen]);

  useEffect(() => {
    if (!showViewControls && priceProviderMenuOpen) {
      setPriceProviderMenuOpen(false);
    }
  }, [priceProviderMenuOpen, showViewControls]);

  function resetDuplicateDialogState() {
    setDuplicateDisplayName("");
    setDuplicateSlug("");
    setDuplicateDescription("");
    setDuplicateSlugTouched(false);
    setShowDuplicateSlugField(false);
    setDuplicateFormError(null);
  }

  function openDuplicateDialog() {
    const sourceInventory = props.state.selectedInventoryRow;
    if (!sourceInventory || !props.state.selectedInventoryCanWrite) {
      return;
    }

    const nextDisplayName = `${sourceInventory.display_name} Copy`;
    setDuplicateDisplayName(nextDisplayName);
    setDuplicateSlug(normalizeInventorySlugInput(nextDisplayName));
    setDuplicateDescription(sourceInventory.description || "");
    setDuplicateSlugTouched(false);
    setShowDuplicateSlugField(false);
    setDuplicateFormError(null);
    setDuplicateDialogOpen(true);
  }

  function closeDuplicateDialog() {
    if (props.state.duplicateInventoryBusy) {
      return;
    }
    setDuplicateDialogOpen(false);
    resetDuplicateDialogState();
  }

  function handleDuplicateDisplayNameChange(value: string) {
    setDuplicateDisplayName(value);
    if (!duplicateSlugTouched) {
      setDuplicateSlug(normalizeInventorySlugInput(value));
    }
    if (duplicateFormError) {
      setDuplicateFormError(null);
    }
  }

  function handleDuplicateSlugChange(value: string) {
    setDuplicateSlugTouched(true);
    setDuplicateSlug(normalizeDuplicateSlugDraft(value));
    if (duplicateFormError) {
      setDuplicateFormError(null);
    }
  }

  function handleDuplicateDescriptionChange(value: string) {
    setDuplicateDescription(value);
    if (duplicateFormError) {
      setDuplicateFormError(null);
    }
  }

  async function handleDuplicateSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const sourceInventory = props.state.selectedInventoryRow;
    if (!sourceInventory || props.state.duplicateInventoryBusy) {
      return;
    }

    const nextDisplayName = duplicateDisplayName.trim();
    const nextSlug = normalizeInventorySlugInput(duplicateSlug);
    const nextDescription = duplicateDescription.trim();

    if (!nextDisplayName) {
      setDuplicateFormError("Enter a collection name before duplicating.");
      return;
    }

    if (!nextSlug) {
      setShowDuplicateSlugField(true);
      setDuplicateFormError("Enter a short name using letters, numbers, or hyphens.");
      return;
    }

    const duplicateResult = await props.actions.onDuplicateInventory(
      sourceInventory.slug,
      sourceInventory.display_name,
      {
        target_description: nextDescription || null,
        target_display_name: nextDisplayName,
        target_slug: nextSlug,
      },
    );

    if (duplicateResult.ok) {
      closeDuplicateDialog();
      return;
    }

    if (duplicateResult.reason === "conflict") {
      setShowDuplicateSlugField(true);
      setDuplicateFormError(
        "That collection name needs a different short name. Edit it below and try again.",
      );
    }
  }

  function focusPriceProviderOption(index: number) {
    const optionCount = PRICE_PROVIDER_OPTIONS.length;
    const boundedIndex = ((index % optionCount) + optionCount) % optionCount;
    window.requestAnimationFrame(() => {
      priceProviderOptionRefs.current[boundedIndex]?.focus();
    });
  }

  function openPriceProviderMenu(focusIndex = selectedPriceProviderIndex) {
    setPriceProviderMenuOpen(true);
    focusPriceProviderOption(focusIndex);
  }

  function closePriceProviderMenu(options: { restoreFocus?: boolean } = {}) {
    setPriceProviderMenuOpen(false);
    if (options.restoreFocus) {
      window.requestAnimationFrame(() => {
        priceProviderTriggerRef.current?.focus();
      });
    }
  }

  function handlePriceProviderTriggerKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
  ) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      openPriceProviderMenu(selectedPriceProviderIndex);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      openPriceProviderMenu(selectedPriceProviderIndex);
    }
  }

  function handlePriceProviderOptionKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    optionIndex: number,
  ) {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        focusPriceProviderOption(optionIndex + 1);
        break;
      case "ArrowUp":
        event.preventDefault();
        focusPriceProviderOption(optionIndex - 1);
        break;
      case "Home":
        event.preventDefault();
        focusPriceProviderOption(0);
        break;
      case "End":
        event.preventDefault();
        focusPriceProviderOption(PRICE_PROVIDER_OPTIONS.length - 1);
        break;
      case "Escape":
        event.preventDefault();
        closePriceProviderMenu({ restoreFocus: true });
        break;
    }
  }

  function handlePriceProviderSelect(nextProvider: InventoryPriceProvider) {
    props.actions.onPriceProviderChange(nextProvider);
    closePriceProviderMenu({ restoreFocus: true });
  }

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
          props.state.table.viewStatus === "error" ? (
            <PanelState
              body={
                props.state.table.viewError ||
                "The current page of table rows could not be loaded right now."
              }
              eyebrow="Table"
              title="Table rows unavailable"
              variant="error"
            />
          ) : props.state.table.viewStatus === "loading" &&
            props.state.table.items.length === 0 ? (
            <PanelState
              body="Loading the current page of table rows."
              eyebrow="Table"
              title="Loading table rows"
              variant="loading"
            />
          ) : (
            <InventoryTableView
              allItemsCount={props.state.table.allItemsCount}
              availableCopyTargetInventories={props.state.table.availableCopyTargetInventories}
              availableMoveTargetInventories={props.state.table.availableMoveTargetInventories}
              availableTargetInventories={props.state.table.availableTargetInventories}
              bulkMutationBusy={props.state.table.bulkMutationBusy}
              canBulkEditSelectedInventory={props.state.table.canBulkEditSelectedInventory}
              canCopyFromSelectedInventory={props.state.table.canCopyFromSelectedInventory}
              canMoveFromSelectedInventory={props.state.table.canMoveFromSelectedInventory}
              collectionItemCount={props.state.table.collectionItemCount}
              createInventoryBusy={props.state.table.createInventoryBusy}
              filterOptions={props.state.table.filterOptions}
              filters={props.state.table.filters}
              items={props.state.table.items}
              onBulkMutationSubmit={props.actions.onBulkMutationSubmit}
              onClearSelection={props.actions.onClearSelectedItems}
              onClearVisibleSelection={props.actions.onClearVisibleSelectedItems}
              onCreateTransferTargetInventory={props.actions.onCreateTransferTargetInventory}
              onFiltersChange={props.actions.onTableFiltersChange}
              onOpenDetails={props.actions.onOpenItemDetails}
              onPageChange={props.actions.onTablePageChange}
              onPreviewTransferItems={props.actions.onPreviewTransferItems}
              onSelectItem={props.actions.onSelectTableItem}
              onSelectAllVisible={props.actions.onSelectAllVisibleItems}
              onSortChange={props.actions.onTableSortChange}
              onTransferItems={props.actions.onTransferItems}
              onToggleItemSelection={props.actions.onToggleItemSelection}
              onVisibleLimitChange={props.actions.onTableVisibleLimitChange}
              page={props.state.table.page}
              pageCount={props.state.table.pageCount}
              priceProvider={props.state.priceProvider}
              selectedItemIds={props.state.table.selectedItemIds}
              sortState={props.state.table.sort}
              transferBusy={props.state.table.transferBusy}
              visibleLimit={props.state.table.visibleLimit}
              visibleLimitOptions={props.state.table.visibleLimitOptions}
            />
          )
        ) : (
          <CompactInventoryList
            busyItem={props.state.collection.busyItem}
            editable={props.state.selectedInventoryCanWrite}
            items={props.state.collection.visibleItems}
            onOpenDetails={props.actions.onOpenItemDetails}
            onPatch={props.actions.onPatch}
            priceProvider={props.state.priceProvider}
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
        </div>

        {showViewControls || showActivityButton || showExportButton ? (
          <div className="collection-header-controls">
            {showViewControls ? (
              <div className="collection-view-controls">
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

                <div
                  className="collection-price-provider-menu"
                  ref={priceProviderMenuRef}
                >
                  <button
                    aria-expanded={priceProviderMenuOpen}
                    aria-haspopup="listbox"
                    aria-label={`Price Source: ${selectedPriceProviderOption.label}`}
                    className="collection-price-provider-trigger"
                    onClick={() => {
                      if (priceProviderMenuOpen) {
                        closePriceProviderMenu();
                        return;
                      }
                      openPriceProviderMenu();
                    }}
                    onKeyDown={handlePriceProviderTriggerKeyDown}
                    ref={priceProviderTriggerRef}
                    type="button"
                  >
                    <span className="collection-price-provider-label">
                      Price Source:
                    </span>
                    <span className="collection-price-provider-value">
                      {selectedPriceProviderOption.label}
                    </span>
                    <span
                      aria-hidden="true"
                      className="collection-price-provider-chevron"
                    />
                  </button>

                  {priceProviderMenuOpen ? (
                    <div
                      aria-label="Price Source"
                      className="collection-price-provider-list"
                      role="listbox"
                    >
                      {PRICE_PROVIDER_OPTIONS.map((option, optionIndex) => (
                        <button
                          aria-selected={option.value === props.state.priceProvider}
                          className={
                            option.value === props.state.priceProvider
                              ? "collection-price-provider-option collection-price-provider-option-active"
                              : "collection-price-provider-option"
                          }
                          key={option.value}
                          onClick={() => handlePriceProviderSelect(option.value)}
                          onKeyDown={(event) =>
                            handlePriceProviderOptionKeyDown(event, optionIndex)
                          }
                          ref={(node) => {
                            priceProviderOptionRefs.current[optionIndex] = node;
                          }}
                          role="option"
                          type="button"
                        >
                          {option.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            {showActivityButton || showDuplicateButton || showExportButton ? (
              <div className="collection-action-controls">
                {showActivityButton ? (
                  <button
                    className="utility-button"
                    onClick={props.actions.onOpenActivity}
                    type="button"
                  >
                    Recent Activity
                  </button>
                ) : null}

                {showDuplicateButton ? (
                  <button
                    className="utility-button"
                    disabled={
                      !props.state.selectedInventoryCanWrite ||
                      props.state.duplicateInventoryBusy
                    }
                    onClick={openDuplicateDialog}
                    title={
                      !props.state.selectedInventoryCanWrite
                        ? "Duplicate requires editor access to the source collection."
                        : undefined
                    }
                    type="button"
                  >
                    {props.state.duplicateInventoryBusy ? "Duplicating..." : "Duplicate"}
                  </button>
                ) : null}

                {props.state.selectedInventoryRow &&
                props.state.canManageShareSelectedInventory ? (
                  <button
                    className="utility-button"
                    onClick={() => setAccessDialogOpen(true)}
                    type="button"
                  >
                    Manage access
                  </button>
                ) : null}

                {showExportButton ? (
                  <button
                    className="utility-button"
                    disabled={props.state.exportInventoryBusy}
                    onClick={() => void props.actions.onExportCsv()}
                    type="button"
                  >
                    {props.state.exportInventoryBusy
                      ? "Exporting CSV..."
                      : "Export collection CSV"}
                  </button>
                ) : null}
              </div>
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
            <span>{getCurrentRetailValueLabel(props.state.priceProvider)}</span>
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
            priceProvider={props.state.priceProvider}
          />
        </ModalDialog>
      ) : null}

      {duplicateDialogOpen && props.state.selectedInventoryRow ? (
        <ModalDialog
          isOpen
          kicker="Collection Duplicate"
          onClose={closeDuplicateDialog}
          subtitle={`Copy every row from ${props.state.selectedInventoryRow.display_name} into a new collection.`}
          title="Duplicate collection"
        >
          <form className="form-section" onSubmit={handleDuplicateSubmit}>
            <label className="field">
              <span>Collection name</span>
              <input
                className="text-input"
                data-autofocus
                disabled={props.state.duplicateInventoryBusy}
                onChange={(event) =>
                  handleDuplicateDisplayNameChange(event.target.value)
                }
                placeholder="e.g. Personal Collection Copy"
                value={duplicateDisplayName}
              />
            </label>

            {showDuplicateSlugField ? (
              <label className="field">
                <span>Short name</span>
                <input
                  className="text-input"
                  disabled={props.state.duplicateInventoryBusy}
                  onChange={(event) => handleDuplicateSlugChange(event.target.value)}
                  placeholder="personal-collection-copy"
                  value={duplicateSlug}
                />
                <span className="field-hint field-hint-info">
                  Used for links and quick references. Keep it short and easy to recognize.
                </span>
              </label>
            ) : null}

            <label className="field">
              <span>Description (optional)</span>
              <textarea
                className="text-area"
                disabled={props.state.duplicateInventoryBusy}
                onChange={(event) =>
                  handleDuplicateDescriptionChange(event.target.value)
                }
                placeholder="Add a short description for this duplicate."
                value={duplicateDescription}
              />
            </label>

            {duplicateFormError ? (
              <p className="field-hint field-hint-error">{duplicateFormError}</p>
            ) : null}

            <div className="search-import-actions">
              <button
                className="primary-button"
                disabled={props.state.duplicateInventoryBusy}
                type="submit"
              >
                {props.state.duplicateInventoryBusy
                  ? "Duplicating..."
                  : "Duplicate collection"}
              </button>
              <button
                className="secondary-button"
                disabled={props.state.duplicateInventoryBusy}
                onClick={closeDuplicateDialog}
                type="button"
              >
                Cancel
              </button>
            </div>
          </form>
        </ModalDialog>
      ) : null}

      {accessDialogOpen && props.state.selectedInventoryRow ? (
        <InventoryAccessDialog
          canManageShare={props.state.canManageShareSelectedInventory}
          inventory={props.state.selectedInventoryRow}
          onClose={() => setAccessDialogOpen(false)}
          onNotice={props.actions.onNotice}
          onPermissionsChanged={props.actions.onReloadInventorySummaries}
        />
      ) : null}
    </section>
  );
}
