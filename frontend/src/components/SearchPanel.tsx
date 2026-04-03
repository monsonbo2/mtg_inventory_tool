import { useEffect, useId, useRef } from "react";
import type { AddInventoryItemRequest, CatalogNameSearchRow, CatalogSearchRow, InventorySummary } from "../types";
import type { SearchCardGroup } from "../searchResultHelpers";
import type { AsyncStatus, NoticeTone } from "../uiTypes";
import { SearchAutocomplete } from "./SearchAutocomplete";
import { PanelState } from "./ui/PanelState";
import { SearchResultCard } from "./SearchResultCard";

function getSuggestionStatusMessage(state: SearchPanelState) {
  const trimmedQuery = state.search.query.trim();
  if (trimmedQuery.length < 2) {
    return "Type at least 2 characters to load card suggestions.";
  }

  if (state.suggestions.status === "loading") {
    return "Loading card suggestions.";
  }

  if (state.suggestions.status === "error") {
    return state.suggestions.error || "Card suggestions are unavailable right now.";
  }

  if (state.suggestions.results.length) {
    return `${state.suggestions.results.length} card suggestion${
      state.suggestions.results.length === 1 ? "" : "s"
    } available. Use the arrow keys to review and press Enter to select one.`;
  }

  if (state.suggestions.status === "ready") {
    return "No card suggestions available. Press Search cards to run the full results view.";
  }

  return "Card suggestions are hidden.";
}

type SearchPanelState = {
  selectedInventoryRow: InventorySummary | null;
  busyAddCardId: string | null;
  search: {
    error: string | null;
    groups: SearchCardGroup[];
    query: string;
    status: AsyncStatus;
  };
  suggestions: {
    error: string | null;
    highlightedIndex: number;
    isOpen: boolean;
    results: CatalogNameSearchRow[];
    status: AsyncStatus;
  };
};

type SearchPanelActions = {
  onSearchQueryChange: (value: string) => void;
  onSearchFieldFocus: () => void;
  onSearchInputKeyDown: (event: React.KeyboardEvent<HTMLInputElement>) => void;
  onSearchSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onLoadPrintings: (group: SearchCardGroup) => Promise<CatalogSearchRow[]>;
  onSuggestionHighlight: (index: number) => void;
  onSuggestionRequestClose: () => void;
  onSuggestionSelect: (result: CatalogNameSearchRow) => void;
  onAdd: (payload: AddInventoryItemRequest) => Promise<boolean>;
  onNotice: (message: string, tone?: NoticeTone) => void;
};

export function SearchPanel(props: {
  actions: SearchPanelActions;
  state: SearchPanelState;
}) {
  const searchFieldRef = useRef<HTMLLabelElement | null>(null);
  const autocompleteListId = useId();
  const autocompleteStatusId = `${autocompleteListId}-status`;
  const activeSuggestionId =
    props.state.suggestions.isOpen && props.state.suggestions.highlightedIndex >= 0
      ? `${autocompleteListId}-option-${props.state.suggestions.highlightedIndex}`
      : undefined;

  useEffect(() => {
    if (!props.state.suggestions.isOpen) {
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
      props.actions.onSuggestionRequestClose();
    }

    document.addEventListener("pointerdown", handlePointerDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
    };
  }, [props.actions, props.state.suggestions.isOpen]);

  return (
    <section className="panel panel-featured search-panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Search And Add</p>
          <h2>Card Search</h2>
        </div>
        <span className="muted-note">
          Current collection: {props.state.selectedInventoryRow?.display_name || "None"}
        </span>
      </div>

      <form className="search-form" onSubmit={props.actions.onSearchSubmit}>
        <label className="field search-field" ref={searchFieldRef}>
          <span>Search query</span>
          <div className="search-input-stack">
            <input
              aria-activedescendant={activeSuggestionId}
              aria-autocomplete="list"
              aria-controls={autocompleteListId}
              aria-describedby={autocompleteStatusId}
              aria-expanded={props.state.suggestions.isOpen}
              aria-haspopup="listbox"
              className="text-input"
              onChange={(event) => props.actions.onSearchQueryChange(event.target.value)}
              onClick={props.actions.onSearchFieldFocus}
              onFocus={props.actions.onSearchFieldFocus}
              onKeyDown={props.actions.onSearchInputKeyDown}
              placeholder="e.g. Lightning Bolt"
              role="combobox"
              value={props.state.search.query}
            />
            <SearchAutocomplete
              error={props.state.suggestions.error}
              highlightedIndex={props.state.suggestions.highlightedIndex}
              isOpen={props.state.suggestions.isOpen}
              listboxId={autocompleteListId}
              onHighlight={props.actions.onSuggestionHighlight}
              onSelect={props.actions.onSuggestionSelect}
              optionIdPrefix={autocompleteListId}
              query={props.state.search.query}
              results={props.state.suggestions.results}
              status={props.state.suggestions.status}
            />
          </div>
        </label>
        <button className="primary-button" type="submit">
          {props.state.search.status === "loading" ? "Searching..." : "Search cards"}
        </button>
      </form>
      <p aria-live="polite" className="sr-only" id={autocompleteStatusId}>
        {getSuggestionStatusMessage(props.state)}
      </p>

      {!props.state.selectedInventoryRow ? (
        <p className="panel-hint">
          Search is available now. Choose a collection to enable add actions.
        </p>
      ) : props.state.selectedInventoryRow.total_cards === 0 ? (
        <p className="panel-hint panel-hint-success">
          {props.state.selectedInventoryRow.display_name} starts empty on purpose. Use search results
          below to seed the first rows.
        </p>
      ) : null}

      <div className="search-results-grid">
        {props.state.search.status === "loading" && props.state.search.groups.length === 0 ? (
          <PanelState
            body="Looking up matching cards in the local catalog."
            title="Searching cards"
            variant="loading"
          />
        ) : props.state.search.status === "error" ? (
          <PanelState
            body={props.state.search.error || "Card search failed."}
            title="Search unavailable"
            variant="error"
          />
        ) : props.state.search.groups.length ? (
          props.state.search.groups.map((group) => (
            <SearchResultCard
              busyPrintingId={props.state.busyAddCardId}
              canAdd={Boolean(props.state.selectedInventoryRow)}
              group={group}
              onAdd={props.actions.onAdd}
              onLoadPrintings={props.actions.onLoadPrintings}
              onNotice={props.actions.onNotice}
              key={group.groupId}
            />
          ))
        ) : props.state.search.status === "ready" ? (
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
