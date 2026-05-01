import { useEffect, useId, useRef } from "react";

import type { InventorySummary } from "../types";
import { SearchAutocomplete } from "./SearchAutocomplete";
import { SearchOptionsControl } from "./SearchOptionsControl";
import type { SearchPanelActions, SearchPanelState } from "./SearchPanel";

function getOtherInventoryCountLabel(availableCount: number) {
  if (availableCount === 0) {
    return "No other collections available";
  }

  return availableCount === 1
    ? "1 other collection available"
    : `${availableCount} other collections available`;
}

function getInventoryStatsLabel(inventory: InventorySummary) {
  return `${inventory.item_rows} entr${inventory.item_rows === 1 ? "y" : "ies"} · ${inventory.total_cards} cards`;
}

function StickyInventorySwitcherOption(props: {
  autoFocus?: boolean;
  inventory: InventorySummary;
  onSelect: (inventorySlug: string) => void;
}) {
  return (
    <button
      autoFocus={props.autoFocus}
      className="inventory-switcher-option"
      onClick={() => props.onSelect(props.inventory.slug)}
      type="button"
    >
      <strong className="inventory-focus-title">{props.inventory.display_name}</strong>
      <div className="inventory-selector-footer">
        <span>{getInventoryStatsLabel(props.inventory)}</span>
      </div>
    </button>
  );
}

export function StickyWorkspaceControls(props: {
  actions: SearchPanelActions;
  collectionMenuOpen: boolean;
  inventories: InventorySummary[];
  onCollectionMenuOpenChange: (open: boolean) => void;
  onSelectInventory: (inventorySlug: string) => void;
  searchState: SearchPanelState;
  selectedInventory: string | null;
  selectedInventoryRow: InventorySummary | null;
}) {
  const collectionMenuId = useId();
  const collectionSwitcherRef = useRef<HTMLDivElement | null>(null);
  const autocompleteListId = useId();
  const currentInventory =
    props.selectedInventoryRow ??
    props.inventories.find((inventory) => inventory.slug === props.selectedInventory) ??
    props.inventories[0] ??
    null;
  const otherInventories = currentInventory
    ? props.inventories.filter((inventory) => inventory.slug !== currentInventory.slug)
    : props.inventories;
  const showAutocomplete =
    props.searchState.suggestions.isOpen && !props.searchState.searchResultsVisible;
  const activeSuggestionId =
    showAutocomplete && props.searchState.suggestions.highlightedIndex >= 0
      ? `${autocompleteListId}-option-${props.searchState.suggestions.highlightedIndex}`
      : undefined;

  useEffect(() => {
    if (!props.collectionMenuOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }

      if (collectionSwitcherRef.current?.contains(target)) {
        return;
      }

      props.onCollectionMenuOpenChange(false);
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [props.collectionMenuOpen]);

  function handleSelectInventory(inventorySlug: string) {
    props.onCollectionMenuOpenChange(false);
    props.onSelectInventory(inventorySlug);
  }

  return (
    <div className="sticky-workspace-controls" role="region" aria-label="Sticky collection and search controls">
      <div className="sticky-workspace-controls-shell">
        <div className="sticky-workspace-controls-grid">
          <div className="sticky-controls-collection" ref={collectionSwitcherRef}>
            {currentInventory ? (
              otherInventories.length ? (
                <>
                  <button
                    aria-controls={collectionMenuId}
                    aria-expanded={props.collectionMenuOpen}
                    className={
                      props.collectionMenuOpen
                        ? "inventory-button inventory-focus-trigger inventory-button-active"
                        : "inventory-button inventory-focus-trigger"
                    }
                    onClick={() =>
                      props.onCollectionMenuOpenChange(!props.collectionMenuOpen)
                    }
                    type="button"
                  >
                    <span className="inventory-focus-trigger-main">
                      <span className="inventory-focus-trigger-copygroup">
                        <strong className="inventory-focus-title">
                          {currentInventory.display_name}
                        </strong>
                        <span className="inventory-focus-trigger-summary">
                          {getOtherInventoryCountLabel(otherInventories.length)}
                        </span>
                      </span>
                      <span aria-hidden="true" className="inventory-focus-trigger-affordance">
                        <span className="inventory-focus-trigger-label">Switch</span>
                        <span
                          className={
                            props.collectionMenuOpen
                              ? "inventory-focus-trigger-indicator inventory-focus-trigger-indicator-open"
                              : "inventory-focus-trigger-indicator"
                          }
                        >
                          ▾
                        </span>
                      </span>
                    </span>
                  </button>

                  {props.collectionMenuOpen ? (
                    <div
                      className="inventory-switcher-list sticky-controls-collection-list"
                      id={collectionMenuId}
                    >
                      {otherInventories.map((inventory, index) => (
                        <StickyInventorySwitcherOption
                          key={inventory.slug}
                          autoFocus={index === 0}
                          inventory={inventory}
                          onSelect={handleSelectInventory}
                        />
                      ))}
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="inventory-focus-card sticky-controls-collection-card">
                  <div className="inventory-focus-card-main">
                    <strong className="inventory-focus-title">
                      {currentInventory.display_name}
                    </strong>
                    <span className="inventory-focus-trigger-summary">
                      {getOtherInventoryCountLabel(otherInventories.length)}
                    </span>
                  </div>
                </div>
              )
            ) : (
              <div className="inventory-focus-card sticky-controls-collection-card">
                <div className="inventory-focus-card-main">
                  <strong className="inventory-focus-title">No collection selected</strong>
                  <span className="inventory-focus-trigger-summary">
                    Choose a collection to start adding cards
                  </span>
                </div>
              </div>
            )}
          </div>

          <form className="search-form sticky-controls-search-form" onSubmit={props.actions.onSearchSubmit}>
            <label className="field search-field" htmlFor={`sticky-search-${autocompleteListId}`}>
              <span className="sr-only">Quick Add and Card Search</span>
              <div className="search-input-stack">
                <input
                  aria-activedescendant={activeSuggestionId}
                  aria-autocomplete="list"
                  aria-controls={autocompleteListId}
                  aria-expanded={showAutocomplete}
                  aria-haspopup="listbox"
                  className="text-input"
                  id={`sticky-search-${autocompleteListId}`}
                  onChange={(event) => props.actions.onSearchQueryChange(event.target.value)}
                  onFocus={() => {
                    if (!props.searchState.searchResultsVisible) {
                      props.actions.onSearchFieldFocus();
                    }
                  }}
                  onKeyDown={props.actions.onSearchInputKeyDown}
                  placeholder="Quick Add and Card Search"
                  role="combobox"
                  value={props.searchState.search.query}
                />
                <SearchAutocomplete
                  error={props.searchState.suggestions.error}
                  highlightedIndex={props.searchState.suggestions.highlightedIndex}
                  isOpen={showAutocomplete}
                  listboxId={autocompleteListId}
                  onHighlight={props.actions.onSuggestionHighlight}
                  onSelect={props.actions.onSuggestionSelect}
                  optionIdPrefix={autocompleteListId}
                  query={props.searchState.search.query}
                  results={props.searchState.suggestions.results}
                  status={props.searchState.suggestions.status}
                />
              </div>
            </label>
            <div className="sticky-controls-search-actions">
              <button className="primary-button" type="submit">
                {props.searchState.search.status === "loading" ? "Searching..." : "Search cards"}
              </button>
              <SearchOptionsControl
                loadAllLanguages={props.searchState.search.loadAllLanguages}
                onLoadAllLanguagesChange={props.actions.onSearchLoadAllLanguagesChange}
                onScopeChange={props.actions.onSearchScopeChange}
                placement="sticky"
                scope={props.searchState.search.scope}
              />
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
