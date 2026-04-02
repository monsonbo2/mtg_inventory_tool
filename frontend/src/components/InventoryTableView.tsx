import { useEffect, useRef, useState } from "react";

import type { ConditionCode, FinishValue, LanguageCode, OwnedInventoryRow } from "../types";
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
  formatUsd,
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

export function InventoryTableView(props: {
  items: OwnedInventoryRow[];
  allItemsCount: number;
  selectedItemIds: number[];
  sortState: InventoryTableSortState;
  filters: InventoryTableFilters;
  filterOptions: InventoryTableFilterOptions;
  onSortChange: (nextSort: InventoryTableSortState) => void;
  onFiltersChange: (nextFilters: InventoryTableFilters) => void;
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisible: () => void;
  onClearVisibleSelection: () => void;
  onClearSelection: () => void;
}) {
  const [activeColumn, setActiveColumn] = useState<InventoryTableColumnKey | null>(null);
  const headerCheckboxRef = useRef<HTMLInputElement | null>(null);
  const selectedItemIdSet = new Set(props.selectedItemIds);
  const selectedVisibleCount = props.items.filter((item) =>
    selectedItemIdSet.has(item.item_id),
  ).length;
  const totalSelectedCount = props.selectedItemIds.length;
  const hiddenSelectedCount = Math.max(totalSelectedCount - selectedVisibleCount, 0);
  const allVisibleSelected = props.items.length > 0 && selectedVisibleCount === props.items.length;
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected;
  const activeFilterCount = getActiveInventoryTableFilterCount(props.filters);
  const selectedCountLabel =
    totalSelectedCount === 0
      ? "No rows selected"
      : `${totalSelectedCount} row${totalSelectedCount === 1 ? "" : "s"} selected`;
  const visibleRowsLabel =
    props.items.length === props.allItemsCount
      ? `Showing all ${props.allItemsCount} row${props.allItemsCount === 1 ? "" : "s"}.`
      : `Showing ${props.items.length} of ${props.allItemsCount} row${props.allItemsCount === 1 ? "" : "s"}.`;

  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

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
          No values are available for this column in the current inventory.
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
              <span>Only rows without a location</span>
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

  return (
    <div className="inventory-table-view">
      <div className="table-toolbar">
        <div className="table-selection-summary">
          <strong>{selectedCountLabel}</strong>
          <span>{visibleRowsLabel}</span>
          {activeFilterCount > 0 ? (
            <span>
              {activeFilterCount} filter{activeFilterCount === 1 ? "" : "s"} active.
            </span>
          ) : null}
          {hiddenSelectedCount > 0 ? (
            <span className="table-selection-summary-accent">
              {hiddenSelectedCount} selected row{hiddenSelectedCount === 1 ? "" : "s"} hidden by
              current filters.
            </span>
          ) : (
            <span>
              Selection is ready for future bulk tag actions once the backend bulk mutation
              endpoint lands.
            </span>
          )}
        </div>

        <div className="table-toolbar-actions">
          <button
            className="secondary-button"
            disabled={activeFilterCount === 0}
            onClick={() => {
              props.onFiltersChange(createDefaultInventoryTableFilters());
              setActiveColumn(null);
            }}
            type="button"
          >
            Clear filters
          </button>
          <button
            className="secondary-button"
            disabled={props.items.length === 0}
            onClick={props.onSelectAllVisible}
            type="button"
          >
            Select all visible
          </button>
          <button
            className="secondary-button"
            disabled={totalSelectedCount === 0}
            onClick={props.onClearSelection}
            type="button"
          >
            Clear selection
          </button>
          <button className="secondary-button" disabled type="button">
            Bulk tag actions pending backend
          </button>
        </div>
      </div>

      {activeColumn ? (
        <section
          aria-label={`${getInventoryTableColumnLabel(activeColumn)} column options`}
          className="table-query-panel"
        >
          <div className="table-query-panel-header">
            <div>
              <strong>{getInventoryTableColumnLabel(activeColumn)}</strong>
              <span>Sort or filter the current table view.</span>
            </div>
            <button
              className="secondary-button table-query-close"
              onClick={() => setActiveColumn(null)}
              type="button"
            >
              Close
            </button>
          </div>

          <div className="table-query-actions">
            <button
              aria-pressed={
                props.sortState?.key === activeColumn && props.sortState.direction === "asc"
              }
              className={
                props.sortState?.key === activeColumn && props.sortState.direction === "asc"
                  ? "secondary-button table-query-action table-query-action-active"
                  : "secondary-button table-query-action"
              }
              onClick={() =>
                props.onSortChange({
                  key: activeColumn,
                  direction: "asc",
                })
              }
              type="button"
            >
              {getInventoryTableSortActionLabel(activeColumn, "asc")}
            </button>
            <button
              aria-pressed={
                props.sortState?.key === activeColumn && props.sortState.direction === "desc"
              }
              className={
                props.sortState?.key === activeColumn && props.sortState.direction === "desc"
                  ? "secondary-button table-query-action table-query-action-active"
                  : "secondary-button table-query-action"
              }
              onClick={() =>
                props.onSortChange({
                  key: activeColumn,
                  direction: "desc",
                })
              }
              type="button"
            >
              {getInventoryTableSortActionLabel(activeColumn, "desc")}
            </button>
            <button
              className="secondary-button table-query-action"
              disabled={props.sortState?.key !== activeColumn}
              onClick={() => props.onSortChange(null)}
              type="button"
            >
              Clear sort
            </button>
            <button
              className="secondary-button table-query-action"
              disabled={getInventoryTableColumnFilterCount(props.filters, activeColumn) === 0}
              onClick={() => clearColumnFilters(activeColumn)}
              type="button"
            >
              Clear column filters
            </button>
          </div>

          <div className="table-query-filter-shell">{renderActiveColumnFilters()}</div>
        </section>
      ) : null}

      <div className="inventory-table-shell">
        <table className="inventory-table">
          <thead>
            <tr>
              <th className="inventory-table-checkbox-column" scope="col">
                <input
                  aria-label="Select all visible rows"
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

                return (
                  <th key={column} scope="col">
                    <button
                      aria-expanded={isActive}
                      className={
                        isActive
                          ? "inventory-table-header-button inventory-table-header-button-active"
                          : "inventory-table-header-button"
                      }
                      onClick={() => toggleColumn(column)}
                      type="button"
                    >
                      <span>{getInventoryTableColumnLabel(column)}</span>
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
                      </span>
                    </button>
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
                  >
                    <td className="inventory-table-checkbox-cell">
                      <input
                        aria-label={`Select ${item.name}`}
                        checked={isSelected}
                        onChange={() => props.onToggleItemSelection(item.item_id)}
                        type="checkbox"
                      />
                    </td>
                    <td className="inventory-table-card-cell">
                      <strong>{item.name}</strong>
                      <span>
                        #{item.collector_number}
                        {item.notes ? ` · ${summarizeInlineText(item.notes, 26)}` : ""}
                      </span>
                    </td>
                    <td>
                      <strong>{item.set_code.toUpperCase()}</strong>
                      <span>{item.set_name}</span>
                    </td>
                    <td>{item.quantity}</td>
                    <td>{formatFinishLabel(item.finish)}</td>
                    <td>{item.condition_code}</td>
                    <td>{formatLanguageCode(item.language_code)}</td>
                    <td>{item.location || "Not set"}</td>
                    <td>{item.tags.length ? item.tags.join(", ") : "No tags"}</td>
                    <td>{formatUsd(decimalToNumber(item.est_value))}</td>
                  </tr>
                );
              })
            ) : (
              <tr className="inventory-table-empty-row">
                <td className="inventory-table-empty-cell" colSpan={10}>
                  <strong>No rows match the current table filters.</strong>
                  <span>Adjust the active filters or clear them to bring rows back into view.</span>
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
