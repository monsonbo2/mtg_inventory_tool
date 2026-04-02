import { useEffect, useRef } from "react";

import type { OwnedInventoryRow } from "../types";
import {
  decimalToNumber,
  formatFinishLabel,
  formatLanguageCode,
  formatUsd,
  summarizeInlineText,
} from "../uiHelpers";

export function InventoryTableView(props: {
  items: OwnedInventoryRow[];
  selectedItemIds: number[];
  onToggleItemSelection: (itemId: number) => void;
  onSelectAllVisible: () => void;
  onClearSelection: () => void;
}) {
  const headerCheckboxRef = useRef<HTMLInputElement | null>(null);
  const selectedVisibleCount = props.items.filter((item) =>
    props.selectedItemIds.includes(item.item_id),
  ).length;
  const allVisibleSelected = props.items.length > 0 && selectedVisibleCount === props.items.length;
  const someVisibleSelected = selectedVisibleCount > 0 && !allVisibleSelected;
  const selectedCountLabel =
    selectedVisibleCount === 0
      ? "No rows selected"
      : `${selectedVisibleCount} row${selectedVisibleCount === 1 ? "" : "s"} selected`;

  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = someVisibleSelected;
    }
  }, [someVisibleSelected]);

  return (
    <div className="inventory-table-view">
      <div className="table-toolbar">
        <div className="table-selection-summary">
          <strong>{selectedCountLabel}</strong>
          <span>
            Selection is ready for future bulk tag actions once the backend bulk mutation
            endpoint lands.
          </span>
        </div>

        <div className="table-toolbar-actions">
          <button className="secondary-button" onClick={props.onSelectAllVisible} type="button">
            Select all visible
          </button>
          <button
            className="secondary-button"
            disabled={selectedVisibleCount === 0}
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
                    props.onClearSelection();
                  }}
                  ref={headerCheckboxRef}
                  type="checkbox"
                />
              </th>
              <th scope="col">Card</th>
              <th scope="col">Set</th>
              <th scope="col">Qty</th>
              <th scope="col">Finish</th>
              <th scope="col">Cond.</th>
              <th scope="col">Lang</th>
              <th scope="col">Location</th>
              <th scope="col">Tags</th>
              <th scope="col">Value</th>
            </tr>
          </thead>
          <tbody>
            {props.items.map((item) => {
              const isSelected = props.selectedItemIds.includes(item.item_id);

              return (
                <tr
                  className={isSelected ? "inventory-table-row inventory-table-row-selected" : "inventory-table-row"}
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
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
