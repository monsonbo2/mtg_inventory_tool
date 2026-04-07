import { useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";

import type {
  BulkInventoryItemMutationRequest,
  BulkTagMutationOperation,
  ConditionCode,
  FinishValue,
  LanguageCode,
  OwnedInventoryRow,
} from "../types";
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
  normalizeOptionalText,
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

export function InventoryTableView(props: {
  items: OwnedInventoryRow[];
  allItemsCount: number;
  selectedItemIds: number[];
  bulkMutationBusy: boolean;
  sortState: InventoryTableSortState;
  filters: InventoryTableFilters;
  filterOptions: InventoryTableFilterOptions;
  onSortChange: (nextSort: InventoryTableSortState) => void;
  onFiltersChange: (nextFilters: InventoryTableFilters) => void;
  onBulkMutationSubmit: (
    payload: BulkInventoryItemMutationRequest,
  ) => Promise<boolean>;
  onSelectItem: (itemId: number, options?: { additive?: boolean; range?: boolean }) => void;
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisible: () => void;
  onClearVisibleSelection: () => void;
  onClearSelection: () => void;
  onOpenDetails: (itemId: number) => void;
}) {
  const [activeColumn, setActiveColumn] = useState<InventoryTableColumnKey | null>(null);
  const [bulkEditorOpen, setBulkEditorOpen] = useState(false);
  const [bulkEditorMode, setBulkEditorMode] = useState<BulkEditorMode>("tags");
  const [bulkTagsInput, setBulkTagsInput] = useState("");
  const [bulkLocationInput, setBulkLocationInput] = useState("");
  const [bulkNotesInput, setBulkNotesInput] = useState("");
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
  const parsedBulkTags = parseTags(bulkTagsInput);
  const exceedsBulkSelectionLimit = totalSelectedCount > 200;
  const hasSelection = totalSelectedCount > 0;
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
    if (!hasSelection) {
      setBulkEditorOpen(false);
    }
  }, [hasSelection]);

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

  async function handleBulkTagAction(operation: BulkTagMutationOperation) {
    const didApply = await props.onBulkMutationSubmit(
      operation === "clear_tags"
        ? {
            item_ids: props.selectedItemIds,
            operation,
          }
        : {
            item_ids: props.selectedItemIds,
            operation,
            tags: parsedBulkTags,
          },
    );
    if (didApply) {
      setBulkTagsInput("");
      setBulkEditorOpen(false);
    }
  }

  async function handleBulkLocationAction(clearLocation = false) {
    const normalizedLocation = normalizeOptionalText(bulkLocationInput);
    const didApply = await props.onBulkMutationSubmit(
      clearLocation
        ? {
            item_ids: props.selectedItemIds,
            operation: "set_location",
            clear_location: true,
          }
        : {
            item_ids: props.selectedItemIds,
            operation: "set_location",
            location: normalizedLocation ?? "",
          },
    );

    if (didApply) {
      setBulkLocationInput("");
      setBulkEditorOpen(false);
    }
  }

  async function handleBulkNotesAction(clearNotes = false) {
    const normalizedNotes = normalizeOptionalText(bulkNotesInput);
    const didApply = await props.onBulkMutationSubmit(
      clearNotes
        ? {
            item_ids: props.selectedItemIds,
            operation: "set_notes",
            clear_notes: true,
          }
        : {
            item_ids: props.selectedItemIds,
            operation: "set_notes",
            notes: normalizedNotes ?? "",
          },
    );

    if (didApply) {
      setBulkNotesInput("");
      setBulkEditorOpen(false);
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

          return (
            <label className="table-filter-option" key={option.value}>
              <input
                checked={isChecked}
                onChange={() => {
                  const nextValues = toggleStringValue(selectedValues, option.value);
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
                type="checkbox"
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
            <label className="table-filter-option">
              <input
                checked={props.filters.emptyLocationOnly}
                onChange={(event) => updateFilters({ emptyLocationOnly: event.target.checked })}
                type="checkbox"
              />
              <span>Only entries without a location</span>
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
    if (!hasSelection || !bulkEditorOpen) {
      return null;
    }

    const normalizedLocation = normalizeOptionalText(bulkLocationInput);
    const normalizedNotes = normalizeOptionalText(bulkNotesInput);

    return (
      <section aria-label="Bulk edit tray" className="table-bulk-tray">
        <div className="table-bulk-tray-header">
          <div>
            <strong>Bulk edit</strong>
            <span>
              Applies to {totalSelectedCount} selected entr
              {totalSelectedCount === 1 ? "y" : "ies"}.
            </span>
            {hiddenSelectedCount > 0 ? (
              <span className="table-selection-summary-accent">
                {hiddenSelectedCount} selected entr
                {hiddenSelectedCount === 1 ? "y" : "ies"} hidden by current filters.
              </span>
            ) : (
              <span>
                Bulk edits apply to every selected entry, including any hidden by filters.
              </span>
            )}
          </div>
          <button
            className="secondary-button table-bulk-tray-close"
            onClick={() => setBulkEditorOpen(false)}
            type="button"
          >
            Close
          </button>
        </div>

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
              Add, remove, replace, or clear tags on every selected entry.
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
              Set the selected entries to a new location, or clear their current location.
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
                placeholder="Notes to replace on the selected entries"
                rows={4}
                value={bulkNotesInput}
              />
            </label>
            <span className="field-hint field-hint-info">
              Replace notes on every selected entry, or clear them entirely.
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
            Bulk edit currently supports up to 200 selected entries per request.
          </span>
        ) : null}
      </section>
    );
  }

  return (
    <div className="inventory-table-view" ref={tableViewRef}>
      <div className="table-toolbar-shell">
        <div className="table-toolbar">
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
                  {hiddenSelectedCount === 1 ? "y" : "ies"} hidden by current filters.
                </span>
              ) : null}
              {exceedsBulkSelectionLimit ? (
                <span className="table-selection-summary-accent">
                  Bulk edit limit: 200 entries.
                </span>
              ) : null}
            </div>
          </div>

          <div className="table-toolbar-controls">
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

            {hasSelection ? (
              <div className="table-selection-actions">
                <button
                  className={
                    bulkEditorOpen
                      ? "secondary-button table-selection-action table-selection-action-active"
                      : "secondary-button table-selection-action"
                  }
                  disabled={exceedsBulkSelectionLimit}
                  onClick={() => setBulkEditorOpen((current) => !current)}
                  type="button"
                >
                  Bulk edit
                </button>
                <button
                  className="secondary-button table-selection-action"
                  onClick={props.onClearSelection}
                  type="button"
                >
                  Clear selection
                </button>
              </div>
            ) : null}
          </div>
        </div>

        {renderBulkEditor()}
      </div>

      <div className="inventory-table-shell">
        <table className="inventory-table">
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
                        type="button"
                      >
                        {item.name}
                      </button>
                      <div className="inventory-table-card-meta">
                        <span>#{item.collector_number}</span>
                        {item.notes ? <span>{summarizeInlineText(item.notes, 26)}</span> : null}
                      </div>
                    </td>
                    <td className="inventory-table-set-cell">
                      <strong>{item.set_code.toUpperCase()}</strong>
                      <span>{item.set_name}</span>
                    </td>
                    <td className="inventory-table-number-cell">{item.quantity}</td>
                    <td className="inventory-table-inline-cell">{formatFinishLabel(item.finish)}</td>
                    <td className="inventory-table-inline-cell">{item.condition_code}</td>
                    <td className="inventory-table-inline-cell">
                      {formatLanguageCode(item.language_code)}
                    </td>
                    <td>
                      <span className="inventory-table-location-pill">
                        {formatLocationLabel(item.location)}
                      </span>
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
                        <span className="inventory-table-empty-value">No tags</span>
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
