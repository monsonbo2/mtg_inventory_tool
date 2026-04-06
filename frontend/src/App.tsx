import { useEffect, useState } from "react";

import { ActivityDrawer } from "./components/ActivityDrawer";
import { AuditFeed } from "./components/AuditFeed";
import { InventorySidebar } from "./components/InventorySidebar";
import { OwnedCollectionPanel } from "./components/OwnedCollectionPanel";
import { PanelState } from "./components/ui/PanelState";
import { SearchPanel } from "./components/SearchPanel";
import { MetricCard } from "./components/ui/MetricCard";
import { NoticeBanner } from "./components/ui/NoticeBanner";
import { NoticeToast } from "./components/ui/NoticeToast";
import { useCardSearch } from "./hooks/useCardSearch";
import { useCollectionViewState } from "./hooks/useCollectionViewState";
import { useInventoryOverview } from "./hooks/useInventoryOverview";
import { useInventoryMutations } from "./hooks/useInventoryMutations";
import { decimalToNumber, formatUsd } from "./uiHelpers";
import type { AppShellState } from "./uiTypes";

function getAppShellState(options: {
  inventoryCount: number;
  inventoryStatus: "idle" | "loading" | "ready" | "error";
}): AppShellState {
  if (options.inventoryCount > 0) {
    return "ready";
  }

  if (options.inventoryStatus === "idle" || options.inventoryStatus === "loading") {
    return "loading";
  }

  if (options.inventoryStatus === "error") {
    return "error";
  }

  return "no_collections";
}

function getShellStatePanelContent(
  appShellState: Exclude<AppShellState, "ready">,
) {
  switch (appShellState) {
    case "loading":
      return {
        collection: {
          body: "Getting the space for cards, values, and tags ready.",
          eyebrow: "Collection",
          title: "Preparing collection view",
          variant: "loading" as const,
        },
        search: {
          body: "Getting card search ready so you can start adding cards in a moment.",
          eyebrow: "Search",
          title: "Preparing search",
          variant: "loading" as const,
        },
      };
    case "no_collections":
      return {
        collection: {
          body: "Once you create a collection, its entries, tags, and values will show up here.",
          eyebrow: "Collection",
          title: "Your cards will appear here",
          variant: "idle" as const,
        },
        search: {
          body: "Create a collection to start finding cards and comparing printings.",
          eyebrow: "Search",
          title: "Search is ready when you are",
          variant: "idle" as const,
        },
      };
    case "error":
      return {
        collection: {
          body: "Cards, values, and tags will appear here once collections are available.",
          eyebrow: "Collection",
          title: "Collection view not ready yet",
          variant: "error" as const,
        },
        search: {
          body: "Search tools are waiting for collections to load. Try refreshing the app.",
          eyebrow: "Search",
          title: "Search not ready yet",
          variant: "error" as const,
        },
      };
  }
}

export default function App() {
  const [activityOpen, setActivityOpen] = useState(false);
  const {
    auditEvents,
    describeInventory,
    inventories,
    inventoryError,
    inventoryStatus,
    items,
    loadInventoryOverview,
    reloadInventorySummaries,
    selectedInventory,
    selectedInventoryRow,
    setSelectedInventory,
    viewError,
    viewStatus,
  } = useInventoryOverview();
  const {
    activeSearchGroupId,
    handleSearchFieldFocus,
    handleSearchInputKeyDown,
    handleSearchQueryChange,
    handleSearchResultsLoadMore,
    dismissSearchResults,
    handleSearchGroupSelect,
    handleSearchWorkspaceBrowse,
    handleSearchSubmit,
    handleSuggestionRequestClose,
    handleSuggestionSelect,
    highlightedSuggestionIndex,
    loadSearchGroupPrintings,
    resetSearchWorkspace,
    searchCanLoadMore,
    searchError,
    searchGroups,
    searchHiddenResultCount,
    searchLoadedHiddenResultCount,
    searchLoadMoreBusy,
    searchQuery,
    searchResultsVisible,
    searchTotalCount,
    searchWorkspaceMode,
    searchStatus,
    setHighlightedSuggestionIndex,
    suggestionError,
    suggestionOpen,
    suggestionResults,
    suggestionStatus,
  } = useCardSearch({
    onSearchActivity() {
      clearNotice();
    },
  });
  const {
    collectionView,
    detailModalItemId,
    focusedItemId,
    handleClearSelectedItems,
    handleClearVisibleSelectedItems,
    handleCollectionViewChange,
    handleCloseItemDetails,
    handleOpenItemDetails,
    handleSelectAllVisibleItems,
    handleToggleItemSelection,
    selectedItemIds,
    setTableFilters,
    setTableSort,
    tableFilterOptions,
    tableFilters,
    tableSort,
    visibleTableItems,
  } = useCollectionViewState({
    items,
    selectedInventory,
  });
  const {
    busyAddCardId,
    bulkTagsBusy,
    busyItem,
    clearNotice,
    createInventoryBusy,
    handleAddCard,
    handleBulkTagMutation,
    handleCreateInventory,
    handleDeleteItem,
    handlePatchItem,
    notice,
    reportNotice,
  } = useInventoryMutations({
    clearSelectedItems: handleClearSelectedItems,
    describeInventory,
    loadInventoryOverview,
    reloadInventorySummaries,
    resetSearchWorkspace,
    selectedInventory,
    selectedItemIds,
  });

  useEffect(() => {
    setActivityOpen(false);
  }, [selectedInventory]);

  const totalEstimatedValue = items.reduce(
    (sum, row) => sum + decimalToNumber(row.est_value),
    0,
  );
  const searchPanelState = {
    activeSearchGroupId,
    busyAddCardId,
    searchResultsVisible,
    searchWorkspaceMode,
    search: {
      canLoadMore: searchCanLoadMore,
      error: searchError,
      groups: searchGroups,
      hiddenResultCount: searchHiddenResultCount,
      loadedHiddenResultCount: searchLoadedHiddenResultCount,
      isLoadingMore: searchLoadMoreBusy,
      query: searchQuery,
      status: searchStatus,
      totalCount: searchTotalCount,
    },
    selectedInventoryRow,
    suggestions: {
      error: suggestionError,
      highlightedIndex: highlightedSuggestionIndex,
      isOpen: suggestionOpen,
      results: suggestionResults,
      status: suggestionStatus,
    },
  };
  const searchPanelActions = {
    onAdd: handleAddCard,
    onLoadPrintings: loadSearchGroupPrintings,
    onNotice: reportNotice,
    onSearchFieldFocus: handleSearchFieldFocus,
    onSearchInputKeyDown: handleSearchInputKeyDown,
    onSearchQueryChange: handleSearchQueryChange,
    onSearchGroupSelect: handleSearchGroupSelect,
    onSearchResultsLoadMore: handleSearchResultsLoadMore,
    onSearchResultsDismiss: dismissSearchResults,
    onSearchWorkspaceBrowse: handleSearchWorkspaceBrowse,
    onSearchSubmit: handleSearchSubmit,
    onSuggestionHighlight: setHighlightedSuggestionIndex,
    onSuggestionRequestClose: handleSuggestionRequestClose,
    onSuggestionSelect: handleSuggestionSelect,
  };
  const collectionPanelState = {
    collection: {
      busyItem,
      detailModalItemId,
      focusedItemId,
      items,
      view: collectionView,
      viewError,
      viewStatus,
    },
    selectedInventoryRow,
    table: {
      bulkTagsBusy,
      filterOptions: tableFilterOptions,
      filters: tableFilters,
      items: visibleTableItems,
      selectedItemIds,
      sort: tableSort,
    },
  };
  const collectionPanelActions = {
    onBulkTagsSubmit: handleBulkTagMutation,
    onClearSelectedItems: handleClearSelectedItems,
    onClearVisibleSelectedItems: handleClearVisibleSelectedItems,
    onCollectionViewChange: handleCollectionViewChange,
    onCloseItemDetails: handleCloseItemDetails,
    onDelete: handleDeleteItem,
    onNotice: reportNotice,
    onOpenActivity: () => setActivityOpen(true),
    onOpenItemDetails: handleOpenItemDetails,
    onPatch: handlePatchItem,
    onSelectAllVisibleItems: handleSelectAllVisibleItems,
    onTableFiltersChange: setTableFilters,
    onTableSortChange: setTableSort,
    onToggleItemSelection: handleToggleItemSelection,
  };
  const bannerNotice = notice && notice.tone !== "success" ? notice : null;
  const toastNotice = notice?.tone === "success" ? notice : null;
  const appShellState = getAppShellState({
    inventoryCount: inventories.length,
    inventoryStatus,
  });
  const shellStatePanels =
    appShellState === "ready" ? null : getShellStatePanelContent(appShellState);

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Card Collection</p>
          <h1>MTG Collection Studio</h1>
          <p className="hero-copy">
            Search cards, compare printings, and organize your collection in one place.
          </p>
        </div>
        <div className="hero-metrics">
          <MetricCard accent="Sunrise" label="Collections" value={String(inventories.length)} />
          <MetricCard accent="Lagoon" label="Entries In View" value={String(items.length)} />
          <MetricCard
            accent="Paper"
            label="Est. Value"
            value={formatUsd(totalEstimatedValue)}
          />
        </div>
      </header>

      {bannerNotice ? <NoticeBanner notice={bannerNotice} /> : null}

      <div className="workspace-grid">
        <div className="workspace-top-grid">
          <aside className="sidebar-column">
            <InventorySidebar
              appShellState={appShellState}
              createInventoryBusy={createInventoryBusy}
              inventories={inventories}
              inventoryError={inventoryError}
              onCreateInventory={handleCreateInventory}
              onSelectInventory={setSelectedInventory}
              selectedInventory={selectedInventory}
              selectedInventoryRow={selectedInventoryRow}
            />
          </aside>

          <div className="workspace-search-column">
            {appShellState === "ready" ? (
              <SearchPanel actions={searchPanelActions} state={searchPanelState} />
            ) : (
              <PanelState
                body={shellStatePanels!.search.body}
                eyebrow={shellStatePanels!.search.eyebrow}
                title={shellStatePanels!.search.title}
                variant={shellStatePanels!.search.variant}
              />
            )}
          </div>
        </div>

        <main className="workspace-main-row">
          {appShellState === "ready" ? (
            <OwnedCollectionPanel
              actions={collectionPanelActions}
              state={collectionPanelState}
            />
          ) : (
            <PanelState
              body={shellStatePanels!.collection.body}
              eyebrow={shellStatePanels!.collection.eyebrow}
              title={shellStatePanels!.collection.title}
              variant={shellStatePanels!.collection.variant}
            />
          )}
        </main>
      </div>

      <ActivityDrawer
        isOpen={activityOpen}
        onClose={() => setActivityOpen(false)}
        subtitle={
          selectedInventoryRow
            ? `${selectedInventoryRow.display_name} · latest 12 changes`
            : "Choose a collection to view recent activity."
        }
        title="Collection Activity"
      >
        <AuditFeed
          auditEvents={auditEvents}
          embedded
          selectedInventoryRow={selectedInventoryRow}
          viewError={viewError}
          viewStatus={viewStatus}
        />
      </ActivityDrawer>

      {toastNotice ? (
        <NoticeToast notice={toastNotice} onDismiss={clearNotice} />
      ) : null}
    </div>
  );
}
