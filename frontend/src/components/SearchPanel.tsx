import { useEffect, useId, useRef } from "react";
import type { AddInventoryItemRequest, CatalogSearchRow, InventorySummary } from "../types";
import type { SearchCardGroup } from "../searchResultHelpers";
import type { AsyncStatus, NoticeTone } from "../uiTypes";
import { SearchAutocomplete } from "./SearchAutocomplete";
import { PanelState } from "./ui/PanelState";
import { SearchResultCard } from "./SearchResultCard";

export function SearchPanel(props: {
  selectedInventoryRow: InventorySummary | null;
  searchStatus: AsyncStatus;
  searchError: string | null;
  suggestionStatus: AsyncStatus;
  suggestionError: string | null;
  searchQuery: string;
  searchGroups: SearchCardGroup[];
  suggestionResults: CatalogSearchRow[];
  suggestionOpen: boolean;
  highlightedSuggestionIndex: number;
  busyAddCardId: string | null;
  onSearchQueryChange: (value: string) => void;
  onSearchFieldFocus: () => void;
  onSearchInputKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  onSearchSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onLoadPrintings: (group: SearchCardGroup) => Promise<CatalogSearchRow[]>;
  onSuggestionHighlight: (index: number) => void;
  onSuggestionRequestClose: () => void;
  onSuggestionSelect: (result: CatalogSearchRow) => void;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
}) {
  const searchFieldRef = useRef<HTMLLabelElement | null>(null);
  const autocompleteListId = useId();
  const activeSuggestionId =
    props.suggestionOpen && props.highlightedSuggestionIndex >= 0
      ? `${autocompleteListId}-option-${props.highlightedSuggestionIndex}`
      : undefined;

  useEffect(() => {
    if (!props.suggestionOpen) {
      return;
    }

    function handlePointerDown(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (searchFieldRef.current?.contains(target)) {
        return;
      }
      props.onSuggestionRequestClose();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [props.onSuggestionRequestClose, props.suggestionOpen]);

  return (
    <section className="panel panel-featured">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Search And Add</p>
          <h2>Card Search</h2>
        </div>
        <span className="muted-note">
          Current inventory: {props.selectedInventoryRow?.display_name || "None"}
        </span>
      </div>

      <form className="search-form" onSubmit={props.onSearchSubmit}>
        <label className="field search-field" ref={searchFieldRef}>
          <span>Search query</span>
          <div className="search-input-stack">
            <input
              aria-activedescendant={activeSuggestionId}
              aria-autocomplete="list"
              aria-controls={autocompleteListId}
              aria-expanded={props.suggestionOpen}
              aria-haspopup="listbox"
              className="text-input"
              onChange={(event) => props.onSearchQueryChange(event.target.value)}
              onClick={props.onSearchFieldFocus}
              onFocus={props.onSearchFieldFocus}
              onKeyDown={props.onSearchInputKeyDown}
              placeholder="e.g. Lightning Bolt"
              role="combobox"
              value={props.searchQuery}
            />
            <SearchAutocomplete
              error={props.suggestionError}
              highlightedIndex={props.highlightedSuggestionIndex}
              isOpen={props.suggestionOpen}
              listboxId={autocompleteListId}
              onHighlight={props.onSuggestionHighlight}
              onSelect={props.onSuggestionSelect}
              optionIdPrefix={autocompleteListId}
              query={props.searchQuery}
              results={props.suggestionResults}
              status={props.suggestionStatus}
            />
          </div>
        </label>
        <button className="primary-button" type="submit">
          {props.searchStatus === "loading" ? "Searching..." : "Search cards"}
        </button>
      </form>

      {!props.selectedInventoryRow ? (
        <p className="panel-hint">
          Search is available now. Choose an inventory to enable add actions.
        </p>
      ) : props.selectedInventoryRow.total_cards === 0 ? (
        <p className="panel-hint panel-hint-success">
          {props.selectedInventoryRow.display_name} starts empty on purpose. Use search results
          below to seed the first rows.
        </p>
      ) : null}

      <div className="search-results-grid">
        {props.searchStatus === "loading" && props.searchGroups.length === 0 ? (
          <PanelState
            body="Looking up matching cards in the local catalog."
            title="Searching cards"
            variant="loading"
          />
        ) : props.searchStatus === "error" ? (
          <PanelState
            body={props.searchError || "Card search failed."}
            title="Search unavailable"
            variant="error"
          />
        ) : props.searchGroups.length ? (
          props.searchGroups.map((group) => (
            <SearchResultCard
              busyPrintingId={props.busyAddCardId}
              canAdd={Boolean(props.selectedInventoryRow)}
              group={group}
              onAdd={props.onAdd}
              onLoadPrintings={props.onLoadPrintings}
              onNotice={props.onNotice}
              key={group.groupId}
            />
          ))
        ) : props.searchStatus === "ready" ? (
          <PanelState
            body="Try another card name, set code, or a broader search term."
            title="No matching cards"
          />
        ) : (
          <PanelState
            body="Search by card name, then choose the exact printing to add."
            title="Run a search"
          />
        )}
      </div>
    </section>
  );
}
