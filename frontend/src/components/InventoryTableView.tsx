import { useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";

import type {
  BulkInventoryItemMutationRequest,
  BulkInventorySelectionRequest,
  BulkTagMutationOperation,
  ConditionCode,
  FinishValue,
  InventoryCreateRequest,
  InventorySummary,
  InventoryTransferMode,
  LanguageCode,
  OwnedInventoryRow,
} from "../types";
import type { InventoryCreateResult } from "../uiTypes";
import type {
  InventoryTableColumnKey,
  InventoryTableFilterOptions,
  InventoryTableFilters,
  InventoryTableSortState,
} from "../tableViewHelpers";
import {
  createDefaultInventoryTableFilters,
  getActiveInventoryTableFilterCount,
  getInventoryTableColumnFilterCount,
  getInventoryTableColumnLabel,
  getInventoryTableSortActionLabel,
} from "../tableViewHelpers";
import {
  decimalToNumber,
  formatFinishLabel,
  formatLanguageCode,
  getTagChipStyle,
  formatUsd,
  formatLocationLabel,
  normalizeInventorySlugInput,
  normalizeOptionalText,
  normalizeTagInputText,
  parseTags,
  summarizeInlineText,
} from "../uiHelpers";

const TABLE_COLUMNS: InventoryTableColumnKey[] = [
  "name",
  "set",
  "quantity",
  "finish",
  "condition_code",
  "language_code",
  "location",
  "tags",
  "est_value",
];

function getColumnActionHint(column: InventoryTableColumnKey) {
  switch (column) {
    case "quantity":
    case "est_value":
      return "Sort";
    case "name":
    case "set":
    case "finish":
    case "condition_code":
    case "language_code":
    case "location":
    case "tags":
      return "Sort/filter";
  }
}

type BulkEditorMode = "tags" | "location" | "notes";
type BulkSelectionScope = "selected" | "filtered" | "all_items";
type FilteredBulkSelectionRequest = Extract<
  BulkInventorySelectionRequest,
  { kind: "filtered" }
>;
type TransferTargetMode = "existing" | "create";
type ActiveTableTray = "bulk" | InventoryTransferMode | null;

function getSingleFilterValue<T>(values: T[]) {
  return values.length === 1 ? values[0] : null;
}

function buildFilteredBulkSelection(
  filters: InventoryTableFilters,
): {
  reason: string | null;
  selection: BulkInventorySelectionRequest | null;
} {
  const unsupportedFilters: string[] = [];
  const selection: FilteredBulkSelectionRequest = { kind: "filtered" };
  const normalizedQuery = filters.nameQuery.trim();
  const normalizedLocation = filters.locationQuery.trim();

  if (normalizedQuery) {
    selection.query = normalizedQuery;
  }
  if (normalizedLocation) {
    selection.location = normalizedLocation;
  }
  if (filters.tags.length > 0) {
    selection.tags = filters.tags;
  }

  if (filters.setCodes.length > 1) {
    unsupportedFilters.push("set");
  } else {
    const setCode = getSingleFilterValue(filters.setCodes);
    if (setCode) {
      selection.set_code = setCode;
    }
  }

  if (filters.finishes.length > 1) {
    unsupportedFilters.push("finish");
  } else {
    const finish = getSingleFilterValue(filters.finishes);
    if (finish) {
      selection.finish = finish;
    }
  }

  if (filters.conditionCodes.length > 1) {
    unsupportedFilters.push("condition");
  } else {
    const conditionCode = getSingleFilterValue(filters.conditionCodes);
    if (conditionCode) {
      selection.condition_code = conditionCode;
    }
  }

  if (filters.languageCodes.length > 1) {
    unsupportedFilters.push("language");
  } else {
    const languageCode = getSingleFilterValue(filters.languageCodes);
    if (languageCode) {
      selection.language_code = languageCode;
    }
  }

  if (filters.emptyLocationOnly) {
    unsupportedFilters.push("empty location");
  }

  if (unsupportedFilters.length > 0) {
    return {
      reason: `Filtered bulk edit cannot use the current ${unsupportedFilters.join(
        "/",
      )} filter state.`,
      selection: null,
    };
  }

  if (
    !selection.query &&
    !selection.set_code &&
    !selection.finish &&
    !selection.condition_code &&
    !selection.language_code &&
    !selection.location &&
    !selection.tags?.length
  ) {
    return {
      reason: "Filtered bulk edit needs at least one active filter.",
      selection: null,
    };
  }

  return { reason: null, selection };
}

export function InventoryTableView(props: {
  items: OwnedInventoryRow[];
  allItemsCount: number;
  availableTargetInventories: InventorySummary[];
  availableCopyTargetInventories: InventorySummary[];
  availableMoveTargetInventories: InventorySummary[];
  canBulkEditSelectedInventory: boolean;
  canCopyFromSelectedInventory: boolean;
  canMoveFromSelectedInventory: boolean;
  collectionItemCount: number;
  selectedItemIds: number[];
  bulkMutationBusy: boolean;
  createInventoryBusy: boolean;
  sortState: InventoryTableSortState;
  filters: InventoryTableFilters;
  filterOptions: InventoryTableFilterOptions;
  onSortChange: (nextSort: InventoryTableSortState) => void;
  onFiltersChange: (nextFilters: InventoryTableFilters) => void;
  onBulkMutationSubmit: (
    payload: BulkInventoryItemMutationRequest,
  ) => Promise<boolean>;
  onCreateInventory: (payload: InventoryCreateRequest) => Promise<InventoryCreateResult>;
  onSelectItem: (itemId: number, options?: { additive?: boolean; range?: boolean }) => void;
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisible: () => void;
  onClearVisibleSelection: () => void;
  onClearSelection: () => void;
  onOpenDetails: (itemId: number) => void;
  onTransferItems: (options: {
    mode: InventoryTransferMode;
    targetInventorySlug: string | null;
    targetInventoryLabel?: string | null;
  }) => Promise<boolean>;
  transferBusy: InventoryTransferMode | null;
}) {
  const [activeColumn, setActiveColumn] = useState<InventoryTableColumnKey | null>(null);
  const [activeTray, setActiveTray] = useState<ActiveTableTray>(null);
  const [bulkEditorMode, setBulkEditorMode] = useState<BulkEditorMode>("tags");
  const [bulkSelectionScope, setBulkSelectionScope] =
    useState<BulkSelectionScope>("selected");
  const [bulkTagsInput, setBulkTagsInput] = useState("");
  const [bulkLocationInput, setBulkLocationInput] = useState("");
  const [bulkNotesInput, setBulkNotesInput] = useState("");
  const [transferTargetMode, setTransferTargetMode] = useState<TransferTargetMode>(
    props.availableTargetInventories.length ? "existing" : "create",
  );
  const [transferTargetInventorySlug, setTransferTargetInventorySlug] = useState<string | null>(
    props.availableTargetInventories[0]?.slug ?? null,
  );
  const [transferCollectionName, setTransferCollectionName] = useState("");
  const [transferCollectionSlug, setTransferCollectionSlug] = useState("");
  const [transferCollectionDescription, setTransferCollectionDescription] = useState("");
  const [transferCollectionDefaultLocation, setTransferCollectionDefaultLocation] = useState("");
  const [transferCollectionDefaultTags, setTransferCollectionDefaultTags] = useState("");
  const [transferCollectionSlugTouched, setTransferCollectionSlugTouched] = useState(false);
  const [showTransferCollectionSlugField, setShowTransferCollectionSlugField] = useState(false);
  const [transferFormError, setTransferFormError] = useState<string | null>(null);
  const headerCheckboxRef = useRef<HTMLInputElement | null>(null);
  const tableViewRef = useRef<HTMLDivElement | null>(null);
  const bulkTagsHintId = "table-bulk-tags-hint";
  const selectedItemIdSet = new Set(props.selectedItemIds);
  const selectedVisibleCount = props.items.filter((item) =>
    selectedItemIdSet.has(item.item_id),
  ).length;
  const totalSelectedCount = props.selectedItemIds.length;
  const hiddenSelectedCount = Math.max(totalSelectedCount - selectedVisibleCount, 0);
  const allVisibleSelected = props.items.length > 0 && selectedVisibleCount === props.items.length;
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected;
  const activeFilterCount = getActiveInventoryTableFilterCount(props.filters);
  const filteredBulkSelection = buildFilteredBulkSelection(props.filters);
  const parsedBulkTags = parseTags(bulkTagsInput);
  const hasSelection = totalSelectedCount > 0;
  const canUseSelectedBulkScope = hasSelection;
  const canUseFilteredBulkScope =
    filteredBulkSelection.selection !== null && props.allItemsCount > 0;
  const canUseAllItemsBulkScope = props.collectionItemCount > 0;
  const hasBulkMutationTarget =
    props.canBulkEditSelectedInventory &&
    (canUseSelectedBulkScope || canUseFilteredBulkScope || canUseAllItemsBulkScope);
  const effectiveBulkSelectionScope: BulkSelectionScope | null =
    bulkSelectionScope === "selected" && canUseSelectedBulkScope
      ? "selected"
      : bulkSelectionScope === "filtered" && canUseFilteredBulkScope
        ? "filtered"
        : bulkSelectionScope === "all_items" && canUseAllItemsBulkScope
          ? "all_items"
          : canUseSelectedBulkScope
            ? "selected"
            : canUseFilteredBulkScope
              ? "filtered"
              : canUseAllItemsBulkScope
                ? "all_items"
                : null;
  const effectiveBulkSelectionCount =
    effectiveBulkSelectionScope === "selected"
      ? totalSelectedCount
      : effectiveBulkSelectionScope === "filtered"
        ? props.allItemsCount
        : effectiveBulkSelectionScope === "all_items"
          ? props.collectionItemCount
          : 0;
  const exceedsBulkSelectionLimit =
    effectiveBulkSelectionScope === "selected" && totalSelectedCount > 1000;
  const bulkEditorOpen = activeTray === "bulk";
  const activeTransferMode = activeTray === "copy" || activeTray === "move" ? activeTray : null;
  const activeTransferTargetInventories =
    activeTransferMode === "copy"
      ? props.availableCopyTargetInventories
      : activeTransferMode === "move"
        ? props.availableMoveTargetInventories
        : props.availableTargetInventories;
  const transferSubmitBusy =
    activeTransferMode !== null && props.transferBusy === activeTransferMode;
  const hasAnySelectionActions =
    props.canBulkEditSelectedInventory ||
    props.canCopyFromSelectedInventory ||
    props.canMoveFromSelectedInventory;
  const selectionCapabilityMessage =
    props.canCopyFromSelectedInventory &&
    !props.canBulkEditSelectedInventory &&
    !props.canMoveFromSelectedInventory
      ? "This collection is read-only. Bulk edit and move are disabled, but copy is available."
      : !hasAnySelectionActions
        ? "Selection is available, but bulk edit, copy, and move are unavailable for this collection."
        : null;
  const selectedCountLabel =
    totalSelectedCount === 0
      ? "No entries selected"
      : `${totalSelectedCount} entr${totalSelectedCount === 1 ? "y" : "ies"} selected`;
  const visibleRowsLabel =
    props.items.length === props.allItemsCount
      ? `Showing all ${props.allItemsCount} entr${props.allItemsCount === 1 ? "y" : "ies"}.`
      : `Showing ${props.items.length} of ${props.allItemsCount} entr${props.allItemsCount === 1 ? "y" : "ies"}.`;

  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  useEffect(() => {
    if (activeTray === "bulk" && !hasBulkMutationTarget) {
      setActiveTray(null);
      return;
    }
    if ((activeTray === "copy" || activeTray === "move") && !hasSelection) {
      setActiveTray(null);
    }
  }, [activeTray, hasBulkMutationTarget, hasSelection]);

  useEffect(() => {
    if (
      (activeTray === "bulk" && !hasBulkMutationTarget) ||
      (activeTray === "copy" && !props.canCopyFromSelectedInventory) ||
      (activeTray === "move" && !props.canMoveFromSelectedInventory)
    ) {
      setActiveTray(null);
    }
  }, [
    activeTray,
    hasBulkMutationTarget,
    props.canCopyFromSelectedInventory,
    props.canMoveFromSelectedInventory,
  ]);

  useEffect(() => {
    setTransferTargetInventorySlug((currentTargetInventorySlug) =>
      currentTargetInventorySlug &&
      activeTransferTargetInventories.some(
        (inventory) => inventory.slug === currentTargetInventorySlug,
      )
        ? currentTargetInventorySlug
        : activeTransferTargetInventories[0]?.slug ?? null,
    );

    if (!activeTransferTargetInventories.length) {
      setTransferTargetMode("create");
    }
  }, [activeTransferTargetInventories]);

  useEffect(() => {
    if (!activeColumn) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (
        tableViewRef.current &&
        event.target instanceof Node &&
        !tableViewRef.current.contains(event.target)
      ) {
        setActiveColumn(null);
      }
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setActiveColumn(null);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [activeColumn]);

  function updateFilters(nextPartial: Partial<InventoryTableFilters>) {
    props.onFiltersChange({
      ...props.filters,
      ...nextPartial,
    });
  }

  function resetTransferCreateForm() {
    setTransferCollectionName("");
    setTransferCollectionSlug("");
    setTransferCollectionDescription("");
    setTransferCollectionDefaultLocation("");
    setTransferCollectionDefaultTags("");
    setTransferCollectionSlugTouched(false);
    setShowTransferCollectionSlugField(false);
    setTransferFormError(null);
  }

  function openTray(nextTray: Exclude<ActiveTableTray, null>) {
    if (
      (nextTray === "bulk" && !hasBulkMutationTarget) ||
      (nextTray === "copy" && (!hasSelection || !props.canCopyFromSelectedInventory)) ||
      (nextTray === "move" && (!hasSelection || !props.canMoveFromSelectedInventory))
    ) {
      return;
    }

    setTransferFormError(null);
    setActiveTray((currentTray) => (currentTray === nextTray ? null : nextTray));
    if (nextTray === "copy" && !props.availableCopyTargetInventories.length) {
      setTransferTargetMode("create");
    }
    if (nextTray === "move" && !props.availableMoveTargetInventories.length) {
      setTransferTargetMode("create");
    }
  }

  function openBulkTray(nextScope: BulkSelectionScope = "selected") {
    if (!hasBulkMutationTarget) {
      return;
    }

    if (
      (nextScope === "selected" && !canUseSelectedBulkScope) ||
      (nextScope === "filtered" && !canUseFilteredBulkScope) ||
      (nextScope === "all_items" && !canUseAllItemsBulkScope)
    ) {
      return;
    }

    setBulkSelectionScope(nextScope);
    openTray("bulk");
  }

  function toggleStringValue<T extends string>(values: T[], value: T) {
    return values.includes(value)
      ? values.filter((currentValue) => currentValue !== value)
      : [...values, value];
  }

  function toggleColumn(column: InventoryTableColumnKey) {
    setActiveColumn((current) => (current === column ? null : column));
  }

  function handleRowClick(
    event: ReactMouseEvent<HTMLTableRowElement>,
    itemId: number,
  ) {
    props.onSelectItem(itemId, {
      additive: event.ctrlKey || event.metaKey,
      range: event.shiftKey,
    });
  }

  function buildBulkSelection(): BulkInventorySelectionRequest | null {
    if (effectiveBulkSelectionScope === "filtered") {
      return filteredBulkSelection.selection;
    }
    if (effectiveBulkSelectionScope === "all_items") {
      return { kind: "all_items" };
    }
    if (effectiveBulkSelectionScope === "selected") {
      return {
        kind: "items",
        item_ids: props.selectedItemIds,
      };
    }
    return null;
  }

  async function handleBulkTagAction(operation: BulkTagMutationOperation) {
    const selection = buildBulkSelection();
    if (!selection) {
      return;
    }

    const didApply = await props.onBulkMutationSubmit(
      operation === "clear_tags"
        ? {
            operation,
            selection,
          }
        : {
            operation,
            selection,
            tags: parsedBulkTags,
          },
    );
    if (didApply) {
      setBulkTagsInput("");
      setActiveTray(null);
    }
  }

  async function handleBulkLocationAction(clearLocation = false) {
    const selection = buildBulkSelection();
    if (!selection) {
      return;
    }

    const normalizedLocation = normalizeOptionalText(bulkLocationInput);
    const didApply = await props.onBulkMutationSubmit(
      clearLocation
        ? {
            operation: "set_location",
            selection,
            clear_location: true,
          }
        : {
            operation: "set_location",
            selection,
            location: normalizedLocation ?? "",
          },
    );

    if (didApply) {
      setBulkLocationInput("");
      setActiveTray(null);
    }
  }

  async function handleBulkNotesAction(clearNotes = false) {
    const selection = buildBulkSelection();
    if (!selection) {
      return;
    }

    const normalizedNotes = normalizeOptionalText(bulkNotesInput);
    const didApply = await props.onBulkMutationSubmit(
      clearNotes
        ? {
            operation: "set_notes",
            selection,
            clear_notes: true,
          }
        : {
            operation: "set_notes",
            selection,
            notes: normalizedNotes ?? "",
          },
    );

    if (didApply) {
      setBulkNotesInput("");
      setActiveTray(null);
    }
  }

  function handleTransferCollectionNameChange(value: string) {
    setTransferCollectionName(value);
    if (!transferCollectionSlugTouched) {
      setTransferCollectionSlug(normalizeInventorySlugInput(value));
    }
    if (transferFormError) {
      setTransferFormError(null);
    }
  }

  function handleTransferCollectionSlugChange(value: string) {
    setTransferCollectionSlugTouched(true);
    setTransferCollectionSlug(normalizeInventorySlugInput(value));
    if (transferFormError) {
      setTransferFormError(null);
    }
  }

  function handleTransferSubmitModeChange(nextMode: TransferTargetMode) {
    setTransferTargetMode(nextMode);
    setTransferFormError(null);
    if (nextMode === "create") {
      return;
    }
    resetTransferCreateForm();
  }

  async function handleTransferSubmit() {
    if (!activeTransferMode) {
      return;
    }

    if (transferTargetMode === "existing") {
      const targetInventory =
        activeTransferTargetInventories.find(
          (inventory) => inventory.slug === transferTargetInventorySlug,
        ) ?? null;

      if (!targetInventory) {
        setTransferFormError("Choose a destination collection before continuing.");
        return;
      }

      const didTransfer = await props.onTransferItems({
        mode: activeTransferMode,
        targetInventorySlug: targetInventory.slug,
        targetInventoryLabel: targetInventory.display_name,
      });

      if (didTransfer) {
        setActiveTray(null);
      }
      return;
    }

    const nextDisplayName = transferCollectionName.trim();
    const nextSlug = normalizeInventorySlugInput(transferCollectionSlug);
    const nextDefaultLocation = normalizeOptionalText(transferCollectionDefaultLocation);
    const nextDefaultTags = normalizeTagInputText(transferCollectionDefaultTags);

    if (!nextDisplayName) {
      setTransferFormError("Enter a collection name before creating it.");
      return;
    }

    if (!nextSlug) {
      setTransferFormError("Enter a short name using letters, numbers, or hyphens.");
      return;
    }

    const createPayload: InventoryCreateRequest = {
      display_name: nextDisplayName,
      slug: nextSlug,
      description: normalizeOptionalText(transferCollectionDescription),
    };
    if (nextDefaultLocation) {
      createPayload.default_location = nextDefaultLocation;
    }
    if (nextDefaultTags) {
      createPayload.default_tags = nextDefaultTags;
    }

    const createResult = await props.onCreateInventory(createPayload);
    if (!createResult.ok) {
      if (createResult.reason === "conflict") {
        setShowTransferCollectionSlugField(true);
        setTransferFormError(
          "That collection name needs a different short name. Edit it below and try again.",
        );
      }
      return;
    }

    const didTransfer = await props.onTransferItems({
      mode: activeTransferMode,
      targetInventorySlug: createResult.inventory.slug,
      targetInventoryLabel: createResult.inventory.display_name,
    });

    if (didTransfer) {
      resetTransferCreateForm();
      setActiveTray(null);
    }
  }

  function clearColumnFilters(column: InventoryTableColumnKey) {
    switch (column) {
      case "name":
        updateFilters({ nameQuery: "" });
        break;
      case "set":
        updateFilters({ setCodes: [] });
        break;
      case "finish":
        updateFilters({ finishes: [] });
        break;
      case "condition_code":
        updateFilters({ conditionCodes: [] });
        break;
      case "language_code":
        updateFilters({ languageCodes: [] });
        break;
      case "location":
        updateFilters({ locationQuery: "", emptyLocationOnly: false });
        break;
      case "tags":
        updateFilters({ tags: [] });
        break;
      case "quantity":
      case "est_value":
        break;
    }
  }

  function renderChecklist<T extends string>(options: Array<{ value: T; label: string }>) {
    if (!activeColumn) {
      return null;
    }

    if (!options.length) {
      return (
        <p className="table-query-empty">
          No values are available for this column in the current collection.
        </p>
      );
    }

    const selectedValues = getSelectedValues(props.filters, activeColumn);

    return (
      <div className="table-filter-checklist">
        {options.map((option) => {
          const isChecked = selectedValues.includes(option.value);
          const multiSelect = activeColumn === "tags";

          return (
            <label className="table-filter-option" key={option.value}>
              <input
                checked={isChecked}
                name={`table-filter-${activeColumn}`}
                onChange={() => {
                  const nextValues = multiSelect
                    ? toggleStringValue(selectedValues, option.value)
                    : [option.value];
                  switch (activeColumn) {
                    case "set":
                      updateFilters({ setCodes: nextValues });
                      break;
                    case "finish":
                      updateFilters({ finishes: nextValues as FinishValue[] });
                      break;
                    case "condition_code":
                      updateFilters({ conditionCodes: nextValues as ConditionCode[] });
                      break;
                    case "language_code":
                      updateFilters({ languageCodes: nextValues as LanguageCode[] });
                      break;
                    case "tags":
                      updateFilters({ tags: nextValues });
                      break;
                    case "name":
                    case "location":
                    case "quantity":
                    case "est_value":
                      break;
                  }
                }}
                type={multiSelect ? "checkbox" : "radio"}
              />
              <span>{option.label}</span>
            </label>
          );
        })}
      </div>
    );
  }

  function renderActiveColumnFilters() {
    if (!activeColumn) {
      return null;
    }

    switch (activeColumn) {
      case "name":
        return (
          <label className="field table-filter-field">
            <span>Card name contains</span>
            <input
              className="text-input"
              onChange={(event) => updateFilters({ nameQuery: event.target.value })}
              placeholder="e.g. bolt"
              type="text"
              value={props.filters.nameQuery}
            />
          </label>
        );
      case "set":
        return renderChecklist(props.filterOptions.sets);
      case "finish":
        return renderChecklist(
          props.filterOptions.finishes.map((finish) => ({
            value: finish,
            label: formatFinishLabel(finish),
          })),
        );
      case "condition_code":
        return renderChecklist(
          props.filterOptions.conditionCodes.map((conditionCode) => ({
            value: conditionCode,
            label: conditionCode,
          })),
        );
      case "language_code":
        return renderChecklist(
          props.filterOptions.languageCodes.map((languageCode) => ({
            value: languageCode,
            label: formatLanguageCode(languageCode),
          })),
        );
      case "location":
        return (
          <div className="table-filter-stack">
            <label className="field table-filter-field">
              <span>Location contains</span>
              <input
                className="text-input"
                onChange={(event) => updateFilters({ locationQuery: event.target.value })}
                placeholder="e.g. binder"
                type="text"
                value={props.filters.locationQuery}
              />
            </label>
          </div>
        );
      case "tags":
        return renderChecklist(
          props.filterOptions.tags.map((tag) => ({
            value: tag,
            label: tag,
          })),
        );
      case "quantity":
      case "est_value":
        return (
          <p className="table-query-empty">
            This column currently supports sorting only.
          </p>
        );
    }
  }

  function renderBulkEditor() {
    if (
      !bulkEditorOpen ||
      !props.canBulkEditSelectedInventory ||
      !effectiveBulkSelectionScope
    ) {
      return null;
    }

    const normalizedLocation = normalizeOptionalText(bulkLocationInput);
    const normalizedNotes = normalizeOptionalText(bulkNotesInput);
    const bulkScopeLabel =
      effectiveBulkSelectionScope === "selected"
        ? `Applies to ${effectiveBulkSelectionCount} selected entr${
            effectiveBulkSelectionCount === 1 ? "y" : "ies"
          }.`
        : effectiveBulkSelectionScope === "filtered"
          ? `Applies to ${effectiveBulkSelectionCount} matching entr${
              effectiveBulkSelectionCount === 1 ? "y" : "ies"
            }.`
          : `Applies to the entire collection (${effectiveBulkSelectionCount} entr${
              effectiveBulkSelectionCount === 1 ? "y" : "ies"
            }).`;

    return (
      <section aria-label="Bulk edit tray" className="table-bulk-tray">
        <div className="table-bulk-tray-header">
          <div>
            <strong>Bulk edit</strong>
            <span>{bulkScopeLabel}</span>
            {effectiveBulkSelectionScope === "selected" && hiddenSelectedCount > 0 ? (
              <span className="table-selection-summary-accent">
                {hiddenSelectedCount} selected entr
                {hiddenSelectedCount === 1 ? "y" : "ies"} not shown in the current view.
              </span>
            ) : effectiveBulkSelectionScope === "selected" ? (
              <span>
                Bulk edits apply to every selected entry, including any not shown in the current view.
              </span>
            ) : null}
            {effectiveBulkSelectionScope === "filtered" && activeFilterCount > 0 ? (
              <span>
                Uses {activeFilterCount} active filter{activeFilterCount === 1 ? "" : "s"}.
              </span>
            ) : null}
          </div>
          <button
            className="secondary-button table-bulk-tray-close"
            onClick={() => setActiveTray(null)}
            type="button"
          >
            Close
          </button>
        </div>

        <div aria-label="Bulk edit target" className="table-bulk-mode-toggle" role="group">
          <button
            aria-pressed={effectiveBulkSelectionScope === "selected"}
            className={
              effectiveBulkSelectionScope === "selected"
                ? "secondary-button table-bulk-mode-button table-bulk-mode-button-active"
                : "secondary-button table-bulk-mode-button"
            }
            disabled={!canUseSelectedBulkScope || props.bulkMutationBusy}
            onClick={() => setBulkSelectionScope("selected")}
            type="button"
          >
            Selected rows
          </button>
          <button
            aria-pressed={effectiveBulkSelectionScope === "filtered"}
            className={
              effectiveBulkSelectionScope === "filtered"
                ? "secondary-button table-bulk-mode-button table-bulk-mode-button-active"
                : "secondary-button table-bulk-mode-button"
            }
            disabled={!canUseFilteredBulkScope || props.bulkMutationBusy}
            onClick={() => setBulkSelectionScope("filtered")}
            type="button"
          >
            Matching filters
          </button>
          <button
            aria-pressed={effectiveBulkSelectionScope === "all_items"}
            className={
              effectiveBulkSelectionScope === "all_items"
                ? "secondary-button table-bulk-mode-button table-bulk-mode-button-active"
                : "secondary-button table-bulk-mode-button"
            }
            disabled={!canUseAllItemsBulkScope || props.bulkMutationBusy}
            onClick={() => setBulkSelectionScope("all_items")}
            type="button"
          >
            Entire collection
          </button>
        </div>

        {filteredBulkSelection.reason &&
        activeFilterCount > 0 &&
        !canUseFilteredBulkScope ? (
          <span className="table-selection-summary-accent">
            {filteredBulkSelection.reason}
          </span>
        ) : null}

        <div aria-label="Bulk edit mode" className="table-bulk-mode-toggle" role="group">
          {([
            ["tags", "Tags"],
            ["location", "Location"],
            ["notes", "Notes"],
          ] as Array<[BulkEditorMode, string]>).map(([mode, label]) => (
            <button
              aria-pressed={bulkEditorMode === mode}
              className={
                bulkEditorMode === mode
                  ? "secondary-button table-bulk-mode-button table-bulk-mode-button-active"
                  : "secondary-button table-bulk-mode-button"
              }
              key={mode}
              onClick={() => setBulkEditorMode(mode)}
              type="button"
            >
              {label}
            </button>
          ))}
        </div>

        {bulkEditorMode === "tags" ? (
          <div className="table-bulk-pane">
            <label className="field table-bulk-field">
              <span>Tag list</span>
              <input
                aria-describedby={bulkTagsHintId}
                className="text-input"
                disabled={props.bulkMutationBusy}
                onChange={(event) => setBulkTagsInput(event.target.value)}
                placeholder="e.g. burn, trade"
                type="text"
                value={bulkTagsInput}
              />
            </label>
            <span className="field-hint field-hint-info" id={bulkTagsHintId}>
              Add, remove, replace, or clear tags on every targeted entry.
            </span>
            <div className="table-bulk-action-buttons">
              <button
                className="secondary-button"
                disabled={
                  props.bulkMutationBusy ||
                  exceedsBulkSelectionLimit ||
                  parsedBulkTags.length === 0
                }
                onClick={() => void handleBulkTagAction("add_tags")}
                type="button"
              >
                Add tags
              </button>
              <button
                className="secondary-button"
                disabled={
                  props.bulkMutationBusy ||
                  exceedsBulkSelectionLimit ||
                  parsedBulkTags.length === 0
                }
                onClick={() => void handleBulkTagAction("remove_tags")}
                type="button"
              >
                Remove tags
              </button>
              <button
                className="secondary-button"
                disabled={
                  props.bulkMutationBusy ||
                  exceedsBulkSelectionLimit ||
                  parsedBulkTags.length === 0
                }
                onClick={() => void handleBulkTagAction("set_tags")}
                type="button"
              >
                Replace tags
              </button>
              <button
                className="secondary-button"
                disabled={props.bulkMutationBusy || exceedsBulkSelectionLimit}
                onClick={() => void handleBulkTagAction("clear_tags")}
                type="button"
              >
                Clear tags
              </button>
            </div>
          </div>
        ) : null}

        {bulkEditorMode === "location" ? (
          <div className="table-bulk-pane">
            <label className="field table-bulk-field">
              <span>Location</span>
              <input
                className="text-input"
                disabled={props.bulkMutationBusy}
                onChange={(event) => setBulkLocationInput(event.target.value)}
                placeholder="e.g. Trade Binder"
                type="text"
                value={bulkLocationInput}
              />
            </label>
            <span className="field-hint field-hint-info">
              Set the targeted entries to a new location, or clear their current location.
            </span>
            <div className="table-bulk-pane-actions">
              <button
                className="secondary-button"
                disabled={
                  props.bulkMutationBusy ||
                  exceedsBulkSelectionLimit ||
                  !normalizedLocation
                }
                onClick={() => void handleBulkLocationAction(false)}
                type="button"
              >
                Set location
              </button>
              <button
                className="secondary-button"
                disabled={props.bulkMutationBusy || exceedsBulkSelectionLimit}
                onClick={() => void handleBulkLocationAction(true)}
                type="button"
              >
                Clear location
              </button>
            </div>
          </div>
        ) : null}

        {bulkEditorMode === "notes" ? (
          <div className="table-bulk-pane">
            <label className="field table-bulk-field">
              <span>Notes</span>
              <textarea
                className="text-input textarea-input"
                disabled={props.bulkMutationBusy}
                onChange={(event) => setBulkNotesInput(event.target.value)}
                placeholder="Notes to replace on the targeted entries"
                rows={4}
                value={bulkNotesInput}
              />
            </label>
            <span className="field-hint field-hint-info">
              Replace notes on every targeted entry, or clear them entirely.
            </span>
            <div className="table-bulk-pane-actions">
              <button
                className="secondary-button"
                disabled={
                  props.bulkMutationBusy ||
                  exceedsBulkSelectionLimit ||
                  !normalizedNotes
                }
                onClick={() => void handleBulkNotesAction(false)}
                type="button"
              >
                Replace notes
              </button>
              <button
                className="secondary-button"
                disabled={props.bulkMutationBusy || exceedsBulkSelectionLimit}
                onClick={() => void handleBulkNotesAction(true)}
                type="button"
              >
                Clear notes
              </button>
            </div>
          </div>
        ) : null}

        {exceedsBulkSelectionLimit ? (
          <span className="table-selection-summary-accent">
            Bulk edit currently supports up to 1000 selected entries per request.
          </span>
        ) : null}
      </section>
    );
  }

  function renderTransferEditor() {
    if (!hasSelection || !activeTransferMode) {
      return null;
    }

    if (
      (activeTransferMode === "copy" && !props.canCopyFromSelectedInventory) ||
      (activeTransferMode === "move" && !props.canMoveFromSelectedInventory)
    ) {
      return null;
    }

    const title =
      activeTransferMode === "copy" ? "Copy to collection" : "Move to collection";

    return (
      <section aria-label={`${title} tray`} className="table-bulk-tray table-transfer-tray">
        <div className="table-bulk-tray-header">
          <div>
            <strong>{title}</strong>
            <span>
              {activeTransferMode === "copy"
                ? `Copy ${totalSelectedCount} selected entr${
                    totalSelectedCount === 1 ? "y" : "ies"
                  } into another collection.`
                : `Move ${totalSelectedCount} selected entr${
                    totalSelectedCount === 1 ? "y" : "ies"
                  } into another collection.`}
            </span>
            {hiddenSelectedCount > 0 ? (
              <span className="table-selection-summary-accent">
                {hiddenSelectedCount} selected entr
                {hiddenSelectedCount === 1 ? "y" : "ies"} not shown in the current view.
              </span>
            ) : (
              <span>
                Matching rows in the destination will merge automatically and keep the source acquisition details.
              </span>
            )}
          </div>
          <button
            className="secondary-button table-bulk-tray-close"
            onClick={() => setActiveTray(null)}
            type="button"
          >
            Close
          </button>
        </div>

        <div aria-label="Transfer target mode" className="table-bulk-mode-toggle" role="group">
          <button
            aria-pressed={transferTargetMode === "existing"}
            className={
              transferTargetMode === "existing"
                ? "secondary-button table-bulk-mode-button table-bulk-mode-button-active"
                : "secondary-button table-bulk-mode-button"
            }
            disabled={!activeTransferTargetInventories.length}
            onClick={() => handleTransferSubmitModeChange("existing")}
            type="button"
          >
            Existing collection
          </button>
          <button
            aria-pressed={transferTargetMode === "create"}
            className={
              transferTargetMode === "create"
                ? "secondary-button table-bulk-mode-button table-bulk-mode-button-active"
                : "secondary-button table-bulk-mode-button"
            }
            onClick={() => handleTransferSubmitModeChange("create")}
            type="button"
          >
            Create new
          </button>
        </div>

        {transferTargetMode === "existing" ? (
          <div className="table-bulk-pane table-transfer-pane">
            {activeTransferTargetInventories.length ? (
              <label className="field table-bulk-field">
                <span>Destination collection</span>
                <select
                  className="text-input"
                  disabled={transferSubmitBusy}
                  onChange={(event) => {
                    setTransferTargetInventorySlug(event.target.value || null);
                    if (transferFormError) {
                      setTransferFormError(null);
                    }
                  }}
                  value={transferTargetInventorySlug ?? ""}
                >
                  {activeTransferTargetInventories.map((inventory) => (
                    <option key={inventory.slug} value={inventory.slug}>
                      {inventory.display_name}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <p className="table-query-empty">
                No other collections are available yet. Create one to continue.
              </p>
            )}

            <span className="field-hint field-hint-info">
              Copy keeps the selected entries in this collection. Move removes them here after the destination update succeeds.
            </span>

            {transferFormError ? (
              <p className="field-hint field-hint-error">{transferFormError}</p>
            ) : null}

            <div className="table-bulk-pane-actions">
              <button
                className="secondary-button"
                disabled={!activeTransferTargetInventories.length || transferSubmitBusy}
                onClick={() => void handleTransferSubmit()}
                type="button"
              >
                {transferSubmitBusy
                  ? activeTransferMode === "copy"
                    ? "Copying..."
                    : "Moving..."
                  : title}
              </button>
            </div>
          </div>
        ) : null}

        {transferTargetMode === "create" ? (
          <div className="table-bulk-pane table-transfer-pane">
            <label className="field table-bulk-field">
              <span>Collection name</span>
              <input
                className="text-input"
                disabled={props.createInventoryBusy || transferSubmitBusy}
                onChange={(event) => handleTransferCollectionNameChange(event.target.value)}
                placeholder="e.g. Archive Box"
                type="text"
                value={transferCollectionName}
              />
            </label>

            {showTransferCollectionSlugField ? (
              <label className="field table-bulk-field">
                <span>Short name</span>
                <input
                  className="text-input"
                  disabled={props.createInventoryBusy || transferSubmitBusy}
                  onChange={(event) => handleTransferCollectionSlugChange(event.target.value)}
                  placeholder="archive-box"
                  type="text"
                  value={transferCollectionSlug}
                />
                <span className="field-hint field-hint-info">
                  Used for links and quick references. Keep it short and easy to recognize.
                </span>
              </label>
            ) : null}

            <label className="field table-bulk-field">
              <span>Description (optional)</span>
              <textarea
                className="text-input textarea-input"
                disabled={props.createInventoryBusy || transferSubmitBusy}
                onChange={(event) => {
                  setTransferCollectionDescription(event.target.value);
                  if (transferFormError) {
                    setTransferFormError(null);
                  }
                }}
                placeholder="Add a short description for this collection."
                rows={3}
                value={transferCollectionDescription}
              />
            </label>

            <label className="field table-bulk-field">
              <span>Default location</span>
              <input
                className="text-input"
                disabled={props.createInventoryBusy || transferSubmitBusy}
                onChange={(event) => {
                  setTransferCollectionDefaultLocation(event.target.value);
                  if (transferFormError) {
                    setTransferFormError(null);
                  }
                }}
                placeholder="e.g. Archive Box"
                type="text"
                value={transferCollectionDefaultLocation}
              />
              <span className="field-hint field-hint-info">
                Items added to this collection will automatically use this location unless you choose another one while adding cards.
              </span>
            </label>

            <label className="field table-bulk-field">
              <span>Default tags</span>
              <input
                className="text-input"
                disabled={props.createInventoryBusy || transferSubmitBusy}
                onChange={(event) => {
                  setTransferCollectionDefaultTags(event.target.value);
                  if (transferFormError) {
                    setTransferFormError(null);
                  }
                }}
                placeholder="e.g. archive, staples"
                type="text"
                value={transferCollectionDefaultTags}
              />
              <span className="field-hint field-hint-info">
                Items added to this collection will automatically include these tags.
              </span>
            </label>

            {transferFormError ? (
              <p className="field-hint field-hint-error">{transferFormError}</p>
            ) : null}

            <div className="table-bulk-pane-actions">
              <button
                className="secondary-button"
                disabled={props.createInventoryBusy || transferSubmitBusy}
                onClick={() => void handleTransferSubmit()}
                type="button"
              >
                {props.createInventoryBusy || transferSubmitBusy
                  ? activeTransferMode === "copy"
                    ? "Copying..."
                    : "Moving..."
                  : activeTransferMode === "copy"
                    ? "Create and copy"
                    : "Create and move"}
              </button>
            </div>
          </div>
        ) : null}
      </section>
    );
  }

  return (
    <div className="inventory-table-view" ref={tableViewRef}>
      <div className="table-toolbar-shell">
        <div className="table-toolbar">
          <div className="table-toolbar-primary">
            <div className="table-selection-summary">
              <strong>{selectedCountLabel}</strong>
              <div className="table-selection-summary-meta">
                <span>{visibleRowsLabel}</span>
                {activeFilterCount > 0 ? (
                  <span>{activeFilterCount} active filter{activeFilterCount === 1 ? "" : "s"}</span>
                ) : null}
                {hiddenSelectedCount > 0 ? (
                  <span className="table-selection-summary-accent">
                    {hiddenSelectedCount} selected entr
                    {hiddenSelectedCount === 1 ? "y" : "ies"} not shown in the current view.
                  </span>
                ) : null}
                {exceedsBulkSelectionLimit ? (
                  <span className="table-selection-summary-accent">
                    Bulk edit limit: 1000 entries.
                  </span>
                ) : null}
              </div>
            </div>

            <div className="table-toolbar-actions">
              {activeFilterCount > 0 ? (
                <button
                  className="secondary-button"
                  onClick={() => {
                    props.onFiltersChange(createDefaultInventoryTableFilters());
                    setActiveColumn(null);
                  }}
                  type="button"
                >
                  Clear filters
                </button>
              ) : null}
              <button
                className="secondary-button"
                disabled={props.items.length === 0}
                onClick={props.onSelectAllVisible}
                type="button"
              >
                Select all visible
              </button>
            </div>
          </div>

          <div className="table-toolbar-selection-slot">
            {hasSelection ? (
              <div>
                <div className="table-selection-actions">
                  {props.canBulkEditSelectedInventory ? (
                    <button
                      className={
                        bulkEditorOpen
                          ? "secondary-button table-selection-action table-selection-action-active"
                          : "secondary-button table-selection-action"
                      }
                      disabled={
                        exceedsBulkSelectionLimit &&
                        !canUseFilteredBulkScope &&
                        !canUseAllItemsBulkScope
                      }
                      onClick={() => openBulkTray("selected")}
                      type="button"
                    >
                      Bulk edit
                    </button>
                  ) : null}
                  {props.canCopyFromSelectedInventory ? (
                    <button
                      className={
                        activeTransferMode === "copy"
                          ? "secondary-button table-selection-action table-selection-action-active"
                          : "secondary-button table-selection-action"
                      }
                      disabled={props.transferBusy !== null}
                      onClick={() => openTray("copy")}
                      type="button"
                    >
                      Copy to collection
                    </button>
                  ) : null}
                  {props.canMoveFromSelectedInventory ? (
                    <button
                      className={
                        activeTransferMode === "move"
                          ? "secondary-button table-selection-action table-selection-action-active"
                          : "secondary-button table-selection-action"
                      }
                      disabled={props.transferBusy !== null}
                      onClick={() => openTray("move")}
                      type="button"
                    >
                      Move to collection
                    </button>
                  ) : null}
                  <button
                    className="secondary-button table-selection-action"
                    onClick={props.onClearSelection}
                    type="button"
                  >
                    Clear selection
                  </button>
                </div>
                {selectionCapabilityMessage ? (
                  <span className="table-selection-slot-copy">
                    {selectionCapabilityMessage}
                  </span>
                ) : null}
              </div>
            ) : (
              <div>
                {props.canBulkEditSelectedInventory &&
                (canUseFilteredBulkScope || canUseAllItemsBulkScope) ? (
                  <div className="table-selection-actions">
                    {canUseFilteredBulkScope ? (
                      <button
                        className={
                          bulkEditorOpen && effectiveBulkSelectionScope === "filtered"
                            ? "secondary-button table-selection-action table-selection-action-active"
                            : "secondary-button table-selection-action"
                        }
                        disabled={props.bulkMutationBusy}
                        onClick={() => openBulkTray("filtered")}
                        type="button"
                      >
                        Bulk edit filtered
                      </button>
                    ) : null}
                    {canUseAllItemsBulkScope ? (
                      <button
                        className={
                          bulkEditorOpen && effectiveBulkSelectionScope === "all_items"
                            ? "secondary-button table-selection-action table-selection-action-active"
                            : "secondary-button table-selection-action"
                        }
                        disabled={props.bulkMutationBusy}
                        onClick={() => openBulkTray("all_items")}
                        type="button"
                      >
                        Bulk edit collection
                      </button>
                    ) : null}
                  </div>
                ) : (
                  <span className="table-selection-slot-copy">
                    Select rows for available actions.
                  </span>
                )}
                {selectionCapabilityMessage ? (
                  <span className="table-selection-slot-copy">
                    {selectionCapabilityMessage}
                  </span>
                ) : null}
              </div>
            )}
          </div>
        </div>

        {renderBulkEditor()}
        {renderTransferEditor()}
      </div>

      <div className="inventory-table-shell">
        <table className="inventory-table">
          <colgroup>
            <col className="inventory-table-col-select" />
            <col className="inventory-table-col-card" />
            <col className="inventory-table-col-set" />
            <col className="inventory-table-col-quantity" />
            <col className="inventory-table-col-finish" />
            <col className="inventory-table-col-condition" />
            <col className="inventory-table-col-language" />
            <col className="inventory-table-col-location" />
            <col className="inventory-table-col-tags" />
            <col className="inventory-table-col-value" />
          </colgroup>
          <thead>
            <tr>
              <th className="inventory-table-checkbox-column" scope="col">
                <input
                  aria-label="Select all visible entries"
                  checked={allVisibleSelected}
                  onChange={(event) => {
                    if (event.target.checked) {
                      props.onSelectAllVisible();
                      return;
                    }
                    props.onClearVisibleSelection();
                  }}
                  ref={headerCheckboxRef}
                  type="checkbox"
                />
              </th>
              {TABLE_COLUMNS.map((column) => {
                const filterCount = getInventoryTableColumnFilterCount(props.filters, column);
                const isSorted = props.sortState?.key === column;
                const isActive = activeColumn === column;
                const columnLabel = getInventoryTableColumnLabel(column);
                const actionHint = getColumnActionHint(column);

                return (
                  <th className="inventory-table-header-cell" key={column} scope="col">
                    <div className="inventory-table-header-stack">
                      <button
                        aria-expanded={isActive}
                        aria-label={columnLabel}
                        className={
                          isActive
                            ? "inventory-table-header-button inventory-table-header-button-active"
                            : "inventory-table-header-button"
                        }
                        onClick={() => toggleColumn(column)}
                        title={`${actionHint} options for ${columnLabel}`}
                        type="button"
                      >
                        <span className="inventory-table-header-copy">
                          <span className="inventory-table-header-label">{columnLabel}</span>
                          <span aria-hidden="true" className="inventory-table-header-hint">
                            {actionHint}
                          </span>
                        </span>
                        <span className="inventory-table-header-meta">
                          {isSorted ? (
                            <span className="inventory-table-header-pill">
                              {props.sortState?.direction === "asc" ? "Asc" : "Desc"}
                            </span>
                          ) : null}
                          {filterCount > 0 ? (
                            <span className="inventory-table-header-pill inventory-table-header-pill-filter">
                              {filterCount}
                            </span>
                          ) : null}
                          <span
                            aria-hidden="true"
                            className={
                              isActive
                                ? "inventory-table-header-chevron inventory-table-header-chevron-active"
                                : "inventory-table-header-chevron"
                            }
                          >
                            ▾
                          </span>
                        </span>
                      </button>

                      {isActive ? (
                        <section
                          aria-label={`${columnLabel} column options`}
                          className="inventory-table-popover"
                        >
                          <div className="inventory-table-popover-header">
                            <div>
                              <strong>{columnLabel}</strong>
                              <span>Sort or filter this column.</span>
                            </div>
                            <button
                              className="secondary-button inventory-table-popover-close"
                              onClick={() => setActiveColumn(null)}
                              type="button"
                            >
                              Close
                            </button>
                          </div>

                          <div className="inventory-table-popover-actions">
                            <button
                              aria-pressed={
                                props.sortState?.key === column &&
                                props.sortState.direction === "asc"
                              }
                              className={
                                props.sortState?.key === column &&
                                props.sortState.direction === "asc"
                                  ? "secondary-button inventory-table-popover-action inventory-table-popover-action-active"
                                  : "secondary-button inventory-table-popover-action"
                              }
                              onClick={() =>
                                props.onSortChange({
                                  key: column,
                                  direction: "asc",
                                })
                              }
                              type="button"
                            >
                              {getInventoryTableSortActionLabel(column, "asc")}
                            </button>
                            <button
                              aria-pressed={
                                props.sortState?.key === column &&
                                props.sortState.direction === "desc"
                              }
                              className={
                                props.sortState?.key === column &&
                                props.sortState.direction === "desc"
                                  ? "secondary-button inventory-table-popover-action inventory-table-popover-action-active"
                                  : "secondary-button inventory-table-popover-action"
                              }
                              onClick={() =>
                                props.onSortChange({
                                  key: column,
                                  direction: "desc",
                                })
                              }
                              type="button"
                            >
                              {getInventoryTableSortActionLabel(column, "desc")}
                            </button>
                            <button
                              className="secondary-button inventory-table-popover-action"
                              disabled={props.sortState?.key !== column}
                              onClick={() => props.onSortChange(null)}
                              type="button"
                            >
                              Clear sort
                            </button>
                            <button
                              className="secondary-button inventory-table-popover-action"
                              disabled={getInventoryTableColumnFilterCount(props.filters, column) === 0}
                              onClick={() => clearColumnFilters(column)}
                              type="button"
                            >
                              Clear column filters
                            </button>
                          </div>

                          <div className="inventory-table-popover-filter-shell">
                            {renderActiveColumnFilters()}
                          </div>
                        </section>
                      ) : null}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {props.items.length ? (
              props.items.map((item) => {
                const isSelected = selectedItemIdSet.has(item.item_id);

                return (
                  <tr
                    className={
                      isSelected
                        ? "inventory-table-row inventory-table-row-selected"
                        : "inventory-table-row"
                    }
                    key={item.item_id}
                    onClick={(event) => handleRowClick(event, item.item_id)}
                  >
                    <td className="inventory-table-checkbox-cell">
                      <input
                        aria-label={`Select ${item.name}`}
                        checked={isSelected}
                        onClick={(event) => {
                          event.stopPropagation();
                        }}
                        onChange={() => props.onToggleItemSelection(item.item_id)}
                        type="checkbox"
                      />
                    </td>
                    <td className="inventory-table-card-cell">
                      <button
                        aria-label={`Open ${item.name} details`}
                        className="inventory-table-card-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          props.onOpenDetails(item.item_id);
                        }}
                        title={item.name}
                        type="button"
                      >
                        {item.name}
                      </button>
                      {item.notes ? (
                        <div className="inventory-table-card-meta">
                          <span title={item.notes}>{summarizeInlineText(item.notes, 34)}</span>
                        </div>
                      ) : null}
                    </td>
                    <td
                      className="inventory-table-set-cell"
                      title={`${item.set_code.toUpperCase()} #${item.collector_number} · ${item.set_name}`}
                    >
                      <strong className="inventory-table-set-code">
                        {item.set_code.toUpperCase()}
                        <span className="inventory-table-collector-number">
                          #{item.collector_number}
                        </span>
                      </strong>
                      <span className="inventory-table-set-name">{item.set_name}</span>
                    </td>
                    <td className="inventory-table-number-cell">{item.quantity}</td>
                    <td className="inventory-table-inline-cell">{formatFinishLabel(item.finish)}</td>
                    <td className="inventory-table-inline-cell">{item.condition_code}</td>
                    <td className="inventory-table-inline-cell">
                      {formatLanguageCode(item.language_code)}
                    </td>
                    <td>
                      {item.location?.trim() ? (
                        <span
                          className="inventory-table-location-pill"
                          title={formatLocationLabel(item.location)}
                        >
                          {formatLocationLabel(item.location)}
                        </span>
                      ) : (
                        <span className="inventory-table-empty-value" aria-label="No location">
                          —
                        </span>
                      )}
                    </td>
                    <td>
                      {item.tags.length ? (
                        <div className="inventory-table-tag-list">
                          {item.tags.slice(0, 2).map((tag) => (
                            <span
                              className="tag-chip subdued inventory-table-tag-chip"
                              key={tag}
                              style={getTagChipStyle(tag)}
                            >
                              {tag}
                            </span>
                          ))}
                          {item.tags.length > 2 ? (
                            <span className="inventory-table-tag-more">
                              +{item.tags.length - 2}
                            </span>
                          ) : null}
                        </div>
                      ) : (
                        <span className="inventory-table-empty-value" aria-label="No tags">
                          —
                        </span>
                      )}
                    </td>
                    <td className="inventory-table-number-cell inventory-table-value-cell">
                      {formatUsd(decimalToNumber(item.est_value))}
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr className="inventory-table-empty-row">
                <td className="inventory-table-empty-cell" colSpan={10}>
                  <strong>No entries match the current filters.</strong>
                  <span>Adjust the active filters or clear them to bring entries back into view.</span>
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function getSelectedValues(
  filters: InventoryTableFilters,
  column: InventoryTableColumnKey,
) {
  switch (column) {
    case "set":
      return filters.setCodes;
    case "finish":
      return filters.finishes;
    case "condition_code":
      return filters.conditionCodes;
    case "language_code":
      return filters.languageCodes;
    case "tags":
      return filters.tags;
    case "name":
    case "location":
    case "quantity":
    case "est_value":
      return [];
  }
}
