import type { CSSProperties, RefObject } from "react";

import {
  summarizeSearchGroup,
  type SearchCardGroup,
} from "../searchResultHelpers";
import type { SearchAddAvailability, SearchSurface } from "../uiTypes";
import type { SearchPanelActions, SearchPanelState } from "./SearchPanel";
import { SearchResultCard } from "./SearchResultCard";
import { CardThumbnail } from "./ui/CardThumbnail";

function getCatalogScopeLabel(scope: SearchPanelState["search"]["scope"]) {
  return scope === "all" ? "Full catalog" : "Main catalog";
}

export function SearchWorkspace(props: {
  actions: SearchPanelActions;
  activeSearchGroup: SearchCardGroup;
  addAvailability: SearchAddAvailability;
  className?: string;
  detailRef?: RefObject<HTMLDivElement | null>;
  gridRef?: RefObject<HTMLDivElement | null>;
  headerRef?: RefObject<HTMLDivElement | null>;
  reserveHeight?: number;
  resultListRef?: RefObject<HTMLDivElement | null>;
  resultsPanelRef?: RefObject<HTMLDivElement | null>;
  resultsPanelStyle?: CSSProperties;
  setResultRef?: (groupId: string, node: HTMLButtonElement | null) => void;
  state: SearchPanelState;
  surface: SearchSurface;
  workspaceRef?: RefObject<HTMLDivElement | null>;
}) {
  const showSearchMatches =
    props.state.searchWorkspaceMode === "browse" &&
    props.state.search.groups.length > 1;
  const searchQueryLabel =
    props.state.search.resultQuery || props.activeSearchGroup.name || "Search";
  const searchResultCount =
    props.state.search.totalCount || props.state.search.groups.length;
  const searchResultCountLabel = `${searchResultCount} matching card${
    searchResultCount === 1 ? "" : "s"
  }`;
  const searchScopeLabel = getCatalogScopeLabel(props.state.search.resultScope);
  const activeSearchScopeLabel = getCatalogScopeLabel(props.state.search.scope);
  const trimmedDraftQuery = props.state.search.query.trim();
  const searchDraftNote =
    props.state.search.status === "loading"
      ? `Updating results for ${trimmedDraftQuery || "this search"} in ${activeSearchScopeLabel}.`
      : `Showing ${searchScopeLabel.toLowerCase()} results for "${searchQueryLabel}". Search to update.`;
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
  const workspaceClassName = props.className
    ? `search-workspace ${props.className}`
    : "search-workspace";

  return (
    <div className={workspaceClassName} ref={props.workspaceRef}>
      <div className="search-workspace-header" ref={props.headerRef}>
        <div className="search-workspace-header-copy">
          <p className="section-kicker">Search Results</p>
          <p className="search-workspace-title">{searchQueryLabel}</p>
          <p className="search-workspace-summary">
            {showSearchMatches
              ? `${searchResultCountLabel} in ${searchScopeLabel}. Pick a card on the left, then confirm the printing and details on the right.`
              : "Selected card ready. Confirm the printing and details below."}
          </p>
          {props.state.search.isResultStale ? (
            <p className="search-workspace-draft-note">{searchDraftNote}</p>
          ) : null}
        </div>
        <div className="search-workspace-header-actions">
          {props.state.search.groups.length > 1 ? (
            props.state.searchWorkspaceMode === "focus" ? (
              <button
                className="secondary-button search-workspace-toggle"
                onClick={() => props.actions.onSearchWorkspaceBrowse(props.surface)}
                type="button"
              >
                Back to matches
              </button>
            ) : (
              <span className="search-workspace-count">{searchResultCountLabel}</span>
            )
          ) : null}
        </div>
      </div>

      <div
        className={
          showSearchMatches
            ? "search-workspace-grid"
            : "search-workspace-grid search-workspace-grid-focus"
        }
        ref={props.gridRef}
      >
        {showSearchMatches ? (
          <div
            className="search-workspace-results"
            ref={props.resultsPanelRef}
            style={props.resultsPanelStyle}
          >
            <div className="search-workspace-results-header">
              <div>
                <strong>Matching cards</strong>
                <span>Select a card to review printings.</span>
              </div>
              <span className="search-workspace-results-count">
                Showing {props.state.search.groups.length} of {searchResultCount}
              </span>
            </div>

            <div className="search-workspace-result-list" ref={props.resultListRef}>
              {props.state.search.groups.map((group) => {
                const isActive = group.groupId === props.activeSearchGroup.groupId;

                return (
                  <button
                    aria-pressed={isActive}
                    className={
                      isActive
                        ? "search-workspace-result search-workspace-result-active"
                        : "search-workspace-result"
                    }
                    key={group.groupId}
                    onClick={() =>
                      props.actions.onSearchGroupSelect(group.groupId, props.surface)
                    }
                    ref={(node) => {
                      props.setResultRef?.(group.groupId, node);
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
                        {group.printingsCount} printing
                        {group.printingsCount === 1 ? "" : "s"}
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
                {props.state.search.loadMoreError ? (
                  <p className="search-workspace-load-more-error" role="status">
                    {props.state.search.loadMoreError}
                  </p>
                ) : null}
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

        <div className="search-workspace-detail" ref={props.detailRef}>
          <SearchResultCard
            busyPrintingId={props.state.busyAddCardId}
            addAvailability={props.addAvailability}
            autoLoadAllLanguages={props.state.search.loadAllLanguages}
            defaultLocation={props.state.selectedInventoryRow?.default_location || null}
            defaultTags={props.state.selectedInventoryRow?.default_tags || null}
            group={props.activeSearchGroup}
            onAdd={props.actions.onAdd}
            onClose={() => props.actions.onSearchResultsDismiss(props.surface)}
            onLoadPrintings={props.actions.onLoadPrintings}
            onNotice={props.actions.onNotice}
          />
        </div>
      </div>
      {props.reserveHeight && props.reserveHeight > 0 ? (
        <div
          aria-hidden="true"
          className="search-workspace-reserve"
          data-search-workspace-reserve="true"
          style={{ height: `${props.reserveHeight}px` }}
        />
      ) : null}
    </div>
  );
}
