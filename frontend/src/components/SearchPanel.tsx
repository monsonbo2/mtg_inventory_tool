import { useEffect, useId, useRef, useState } from "react";
import type {
  AddInventoryItemRequest,
  CatalogNameSearchRow,
  CatalogPrintingLookupRow,
  InventorySummary,
} from "../types";
import {
  summarizeSearchGroup,
  type SearchCardGroup,
} from "../searchResultHelpers";
import type { AsyncStatus, NoticeTone } from "../uiTypes";
import { SearchAutocomplete } from "./SearchAutocomplete";
import { PanelState } from "./ui/PanelState";
import { SearchResultCard } from "./SearchResultCard";
import { CardThumbnail } from "./ui/CardThumbnail";

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
  activeSearchGroupId: string | null;
  busyAddCardId: string | null;
  searchResultsVisible: boolean;
  searchWorkspaceMode: "browse" | "focus";
  search: {
    canLoadMore: boolean;
    error: string | null;
    groups: SearchCardGroup[];
    hiddenResultCount: number;
    loadedHiddenResultCount: number;
    isLoadingMore: boolean;
    query: string;
    status: AsyncStatus;
    totalCount: number;
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
  onSearchGroupSelect: (groupId: string) => void;
  onSearchResultsLoadMore: () => void;
  onSearchResultsDismiss: () => void;
  onSearchSubmit: (event: React.FormEvent<HTMLFormElement>) => void;
  onSearchWorkspaceBrowse: () => void;
  onLoadPrintings: (group: SearchCardGroup) => Promise<CatalogPrintingLookupRow[]>;
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
  const searchResultRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const searchResultsPanelRef = useRef<HTMLDivElement | null>(null);
  const searchWorkspaceDetailRef = useRef<HTMLDivElement | null>(null);
  const autocompleteListId = useId();
  const autocompleteStatusId = `${autocompleteListId}-status`;
  const [searchResultsPanelHeight, setSearchResultsPanelHeight] = useState<number | null>(null);
  const hasSearchResults = props.state.search.groups.length > 0;
  const showSearchResults = props.state.searchResultsVisible && hasSearchResults;
  const showAutocomplete = props.state.suggestions.isOpen && !showSearchResults;
  const activeSearchGroup =
    props.state.search.groups.find((group) => group.groupId === props.state.activeSearchGroupId) ||
    props.state.search.groups[0] ||
    null;
  const showSearchMatches =
    showSearchResults &&
    props.state.searchWorkspaceMode === "browse" &&
    props.state.search.groups.length > 1;
  const searchQueryLabel = props.state.search.query.trim() || activeSearchGroup?.name || "Search";
  const searchResultCount = props.state.search.totalCount || props.state.search.groups.length;
  const searchResultCountLabel = `${searchResultCount} matching card${
    searchResultCount === 1 ? "" : "s"
  }`;
  const nextSearchMatchCount = Math.min(
    10,
    props.state.search.loadedHiddenResultCount > 0
      ? props.state.search.loadedHiddenResultCount
      : props.state.search.hiddenResultCount || 10,
  );
  const searchResultsLoadMoreLabel = props.state.search.isLoadingMore
    ? "Loading more matches..."
    : props.state.search.loadedHiddenResultCount > 0
      ? `Show ${nextSearchMatchCount} more of ${props.state.search.hiddenResultCount} additional matches`
      : `Load ${nextSearchMatchCount} more matches`;
  const activeSuggestionId =
    showAutocomplete && props.state.suggestions.highlightedIndex >= 0
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

  useEffect(() => {
    if (!showSearchMatches || !activeSearchGroup) {
      return;
    }

    const activeNode = searchResultRefs.current[activeSearchGroup.groupId];
    if (typeof activeNode?.scrollIntoView === "function") {
      activeNode.scrollIntoView({ block: "nearest", inline: "nearest" });
    }

    const activeIndex = props.state.search.groups.findIndex(
      (group) => group.groupId === activeSearchGroup.groupId,
    );
    const nextGroup = props.state.search.groups[activeIndex + 1];
    const nextNode = nextGroup ? searchResultRefs.current[nextGroup.groupId] : null;
    if (typeof nextNode?.scrollIntoView === "function") {
      nextNode.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }, [activeSearchGroup, props.state.search.groups, showSearchMatches]);

  useEffect(() => {
    if (!showSearchMatches) {
      setSearchResultsPanelHeight(null);
      return;
    }

    function updateSearchResultsPanelHeight() {
      const resultsPanelNode = searchResultsPanelRef.current;
      const detailNode = searchWorkspaceDetailRef.current;
      if (!resultsPanelNode || !detailNode) {
        return;
      }

      const resultsRect = resultsPanelNode.getBoundingClientRect();
      const detailRect = detailNode.getBoundingClientRect();
      const isStackedLayout = Math.abs(resultsRect.top - detailRect.top) > 8;
      if (isStackedLayout) {
        setSearchResultsPanelHeight(null);
        return;
      }

      setSearchResultsPanelHeight(Math.max(0, Math.round(detailRect.height)));
    }

    updateSearchResultsPanelHeight();

    const resizeObserver =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            updateSearchResultsPanelHeight();
          });

    if (resizeObserver) {
      if (searchResultsPanelRef.current) {
        resizeObserver.observe(searchResultsPanelRef.current);
      }
      if (searchWorkspaceDetailRef.current) {
        resizeObserver.observe(searchWorkspaceDetailRef.current);
      }
    }

    window.addEventListener("resize", updateSearchResultsPanelHeight);
    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", updateSearchResultsPanelHeight);
    };
  }, [activeSearchGroup?.groupId, showSearchMatches]);

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
              aria-expanded={showAutocomplete}
              aria-haspopup="listbox"
              className="text-input"
              onChange={(event) => props.actions.onSearchQueryChange(event.target.value)}
              onClick={() => {
                if (!showSearchResults) {
                  props.actions.onSearchFieldFocus();
                }
              }}
              onFocus={() => {
                if (!showSearchResults) {
                  props.actions.onSearchFieldFocus();
                }
              }}
              onKeyDown={props.actions.onSearchInputKeyDown}
              placeholder="e.g. Lightning Bolt"
              role="combobox"
              value={props.state.search.query}
            />
            <SearchAutocomplete
              error={props.state.suggestions.error}
              highlightedIndex={props.state.suggestions.highlightedIndex}
              isOpen={showAutocomplete}
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
          {props.state.selectedInventoryRow.display_name} is ready for its first cards. Use search
          results below to get started.
        </p>
      ) : null}

      {props.state.search.status === "loading" && !hasSearchResults ? (
        <PanelState
          body="Looking through matching cards and printings."
          eyebrow="Search"
          title="Searching cards"
          variant="loading"
        />
      ) : props.state.search.status === "error" ? (
        <PanelState
          body="Card search is temporarily unavailable. Try again in a moment."
          eyebrow="Search"
          title="Search unavailable"
          variant="error"
        />
      ) : props.state.search.status === "ready" && !hasSearchResults ? (
        <PanelState
          body="Try a broader card name, a simpler spelling, or fewer extra terms."
          eyebrow="Search"
          title="No matching cards"
        />
      ) : !hasSearchResults ? (
        <PanelState
          body="Search by card name, then choose the printing you want to add."
          eyebrow="Search"
          title="Run a search"
        />
      ) : null}

      {showSearchResults && activeSearchGroup ? (
        <div className="search-workspace">
          <div className="search-workspace-header">
            <div className="search-workspace-header-copy">
              <p className="section-kicker">Search Results</p>
              <p className="search-workspace-title">{searchQueryLabel}</p>
              <p className="search-workspace-summary">
                {showSearchMatches
                  ? `${searchResultCountLabel}. Pick a card on the left, then confirm the printing and details on the right.`
                  : "Selected card ready. Confirm the printing and details below."}
              </p>
            </div>
            <div className="search-workspace-header-actions">
              {props.state.search.groups.length > 1 ? (
                props.state.searchWorkspaceMode === "focus" ? (
                  <button
                    className="secondary-button search-workspace-toggle"
                    onClick={props.actions.onSearchWorkspaceBrowse}
                    type="button"
                  >
                    Back to matches
                  </button>
                ) : (
                  <span className="search-workspace-count">{searchResultCountLabel}</span>
                )
              ) : null}
              <button
                aria-label="Close add card pane"
                className="search-results-close"
                onClick={props.actions.onSearchResultsDismiss}
                type="button"
              >
                ×
              </button>
            </div>
          </div>

          <div
            className={
              showSearchMatches
                ? "search-workspace-grid"
                : "search-workspace-grid search-workspace-grid-focus"
            }
          >
            {showSearchMatches ? (
              <div
                className="search-workspace-results"
                ref={searchResultsPanelRef}
                style={
                  searchResultsPanelHeight
                    ? { height: `${searchResultsPanelHeight}px` }
                    : undefined
                }
              >
                <div className="search-workspace-results-header">
                  <strong>Matching cards</strong>
                  <span>Select a card to review printings.</span>
                </div>

                <div className="search-workspace-result-list">
                  {props.state.search.groups.map((group) => {
                    const isActive = group.groupId === activeSearchGroup.groupId;

                    return (
                    <button
                      aria-pressed={isActive}
                      className={
                        isActive
                          ? "search-workspace-result search-workspace-result-active"
                          : "search-workspace-result"
                      }
                      key={group.groupId}
                      onClick={() => props.actions.onSearchGroupSelect(group.groupId)}
                      ref={(node) => {
                        searchResultRefs.current[group.groupId] = node;
                      }}
                      type="button"
                    >
                        <CardThumbnail
                          imageUrl={group.image_uri_small}
                          imageUrlLarge={group.image_uri_normal}
                          name={group.name}
                          variant="search"
                        />
                        <span className="search-workspace-result-copy">
                          <strong>{group.name}</strong>
                          <span className="search-workspace-result-meta">
                            {group.printingsCount} printing{group.printingsCount === 1 ? "" : "s"}
                          </span>
                          <span className="search-workspace-result-summary">
                            {summarizeSearchGroup(group)}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>

                {props.state.search.canLoadMore ? (
                  <div className="search-workspace-results-footer">
                    <button
                      className="secondary-button search-workspace-load-more"
                      disabled={props.state.search.isLoadingMore}
                      onClick={props.actions.onSearchResultsLoadMore}
                      type="button"
                    >
                      {searchResultsLoadMoreLabel}
                    </button>
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="search-workspace-detail" ref={searchWorkspaceDetailRef}>
              <SearchResultCard
                busyPrintingId={props.state.busyAddCardId}
                canAdd={Boolean(props.state.selectedInventoryRow)}
                group={activeSearchGroup}
                onAdd={props.actions.onAdd}
                onLoadPrintings={props.actions.onLoadPrintings}
                onNotice={props.actions.onNotice}
              />
            </div>
          </div>
        </div>
      ) : null}
    </section>
  );
}
