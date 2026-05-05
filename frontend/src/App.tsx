import { useEffect, useRef, useState } from "react";

import { ActivityDrawer } from "./components/ActivityDrawer";
import { AuditFeed } from "./components/AuditFeed";
import { InventorySidebar } from "./components/InventorySidebar";
import { OwnedCollectionPanel } from "./components/OwnedCollectionPanel";
import { PanelState } from "./components/ui/PanelState";
import { SearchPanel } from "./components/SearchPanel";
import { StickyWorkspaceControls } from "./components/StickyWorkspaceControls";
import { NoticeBanner } from "./components/ui/NoticeBanner";
import { NoticeToast } from "./components/ui/NoticeToast";
import { useCardSearch } from "./hooks/useCardSearch";
import { useCollectionViewState } from "./hooks/useCollectionViewState";
import { useInventoryOverview } from "./hooks/useInventoryOverview";
import { useInventoryTablePage } from "./hooks/useInventoryTablePage";
import { useInventoryMutations } from "./hooks/useInventoryMutations";
import {
  canCopyFromInventory,
  canExportInventory,
  canMoveFromInventory,
  getAvailableTransferTargetInventories,
  getTransferTargetInventories,
  getWritableInventories,
  isWritableInventory,
} from "./inventoryCapabilities";
import { decimalToNumber } from "./uiHelpers";
import type { AppShellState } from "./uiTypes";
import type { AccessSummaryResponse } from "./types";

function getAppShellState(options: {
  accessSummary: AccessSummaryResponse | null;
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

  if (options.accessSummary && !options.accessSummary.has_readable_inventory) {
    return options.accessSummary.can_bootstrap ? "bootstrap_available" : "access_needed";
  }

  return "access_needed";
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
    case "bootstrap_available":
      return {
        collection: {
          body: "Once your collection exists, its entries, tags, and values will show up here.",
          eyebrow: "Collection",
          title: "Your cards will appear here",
          variant: "idle" as const,
        },
        search: {
          body: "Create your collection to start finding cards and comparing printings.",
          eyebrow: "Search",
          title: "Search is ready when you are",
          variant: "idle" as const,
        },
      };
    case "access_needed":
      return {
        collection: {
          body: "No readable collections are available for this account yet.",
          eyebrow: "Collection",
          title: "Collection access needed",
          variant: "idle" as const,
        },
        search: {
          body: "Search unlocks once you can read at least one collection.",
          eyebrow: "Search",
          title: "Search waiting for access",
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
  const [collectionMenuOpen, setCollectionMenuOpen] = useState(false);
  const [searchFocusRequest, setSearchFocusRequest] = useState<{
    target: "search" | "import";
    token: number;
  } | null>(null);
  const [stickyControlsVisible, setStickyControlsVisible] = useState(false);
  const [workspaceCreateActionHost, setWorkspaceCreateActionHost] =
    useState<HTMLDivElement | null>(null);
  const [workspaceImportActionHost, setWorkspaceImportActionHost] =
    useState<HTMLDivElement | null>(null);
  const [staleCollectionItemsInventory, setStaleCollectionItemsInventory] =
    useState<string | null>(null);
  const workspaceTopRef = useRef<HTMLDivElement | null>(null);
  const {
    accessSummary,
    auditEvents,
    describeInventory,
    inventories,
    inventoryError,
    inventoryStatus,
    items,
    loadInventoryOverview,
    refreshInventoryAudit,
    reloadInventorySummaries,
    selectedInventory,
    selectedInventoryRow,
    setSelectedInventory,
    viewError,
    viewInventorySlug,
    viewStatus,
  } = useInventoryOverview();
  const isCollectionSwitchPending =
    selectedInventory !== null && selectedInventory !== viewInventorySlug;
  const collectionItems = isCollectionSwitchPending ? [] : items;
  const collectionAuditEvents = isCollectionSwitchPending ? [] : auditEvents;
  const collectionViewError = isCollectionSwitchPending ? null : viewError;
  const collectionViewStatus = isCollectionSwitchPending ? "loading" : viewStatus;
  const selectedCollectionItemsStale =
    selectedInventory !== null && staleCollectionItemsInventory === selectedInventory;
  const {
    activeSearchGroupId,
    handleSearchFieldFocus,
    handleSearchInputKeyDown,
    handleSearchLoadAllLanguagesChange,
    handleSearchQueryChange,
    handleSearchResultsLoadMore,
    handleSearchScopeChange,
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
    searchLoadAllLanguages,
    searchLoadedHiddenResultCount,
    searchLoadMoreError,
    searchLoadMoreBusy,
    searchQuery,
    searchResultQuery,
    searchResultScope,
    searchResultsStale,
    searchResultsVisible,
    searchScope,
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
    browsePage,
    browsePageCount,
    browseVisibleLimit,
    browseVisibleLimitOptions,
    collectionView,
    collectionSearchQuery,
    detailModalItemId,
    filteredCollectionItemsCount,
    filteredTableItemsCount,
    focusedItemId,
    handleBrowsePageChange,
    handleBrowseVisibleLimitChange,
    handleClearSelectedItems,
    handleClearVisibleSelectedItems,
    handleCollectionViewChange,
    handleCloseItemDetails,
    handleCollectionSearchQueryChange,
    handleOpenItemDetails,
    handleSelectTableItem,
    handleSelectAllVisibleItems,
    handleTableFiltersChange,
    handleTablePageChange,
    handleToggleItemSelection,
    selectedItemIds,
    setTableSort,
    tablePage,
    tablePageCount,
    tableVisibleLimit,
    tableVisibleLimitOptions,
    tableFilterOptions,
    tableFilters,
    tableSort,
    handleTableVisibleLimitChange,
    visibleCollectionItems,
    visibleTableItems,
  } = useCollectionViewState({
    items: collectionItems,
    selectedInventory,
  });
  const tablePageState = useInventoryTablePage({
    enabled:
      collectionView === "table" &&
      selectedInventory !== null &&
      !isCollectionSwitchPending,
    filters: tableFilters,
    inventorySlug: selectedInventory,
    onPageOutOfRange: handleTablePageChange,
    page: tablePage,
    sort: tableSort,
    visibleLimit: tableVisibleLimit,
  });
  async function refreshStaleBrowseCollection(inventorySlug: string) {
    try {
      const refreshOutcome = await loadInventoryOverview(inventorySlug, {
        reloadInventories: false,
      });
      if (refreshOutcome === "applied") {
        setStaleCollectionItemsInventory((current) =>
          current === inventorySlug ? null : current,
        );
      }
    } catch {
      // The overview hook owns the visible error state for Browse mode.
    }
  }

  function handleCollectionViewModeChange(nextView: "browse" | "table") {
    handleCollectionViewChange(nextView);
    if (
      nextView === "browse" &&
      selectedInventory !== null &&
      selectedCollectionItemsStale
    ) {
      void refreshStaleBrowseCollection(selectedInventory);
    }
  }

  function markCollectionItemsStale(inventorySlug: string) {
    if (inventorySlug === selectedInventory) {
      setStaleCollectionItemsInventory(inventorySlug);
    }
  }

  const {
    busyAddCardId,
    bulkMutationBusy,
    busyItem,
    commitCsvImport,
    commitDeckUrlImport,
    commitDecklistImport,
    clearNotice,
    createInventoryBusy,
    exportInventoryBusy,
    handleAddCard,
    handleBulkMutation,
    handleCreateInventory,
    handleDeleteItem,
    handleExportInventoryCsv,
    handlePatchItem,
    handleTransferItems,
    notice,
    previewCsvImport,
    previewDeckUrlImport,
    previewDecklistImport,
    reportNotice,
    transferBusy,
  } = useInventoryMutations({
    activeCollectionView: collectionView,
    clearSelectedItems: handleClearSelectedItems,
    describeInventory,
    loadInventoryOverview,
    markCollectionItemsStale,
    refreshInventoryAudit,
    refreshActiveTablePage: tablePageState.refreshTablePage,
    reloadInventorySummaries,
    resetSearchWorkspace,
    selectedInventory,
    selectedInventoryItemCount:
      collectionView === "table" ? 0 : collectionItems.length,
    selectedItemIds,
  });

  useEffect(() => {
    setActivityOpen(false);
    setStaleCollectionItemsInventory(null);
  }, [selectedInventory]);

  const selectedInventoryCanWrite = isWritableInventory(selectedInventoryRow);
  const writableInventories = getWritableInventories(inventories);
  const availableCopyTargetInventories = getTransferTargetInventories(inventories, {
    mode: "copy",
    sourceInventory: selectedInventoryRow,
  });
  const availableMoveTargetInventories = getTransferTargetInventories(inventories, {
    mode: "move",
    sourceInventory: selectedInventoryRow,
  });
  const availableTransferTargetInventories = getAvailableTransferTargetInventories(
    inventories,
    selectedInventoryRow,
  );
  const activeTableItems =
    collectionView === "table" ? tablePageState.items : visibleTableItems;
  const shouldHideStaleBrowseItems =
    collectionView === "browse" && selectedCollectionItemsStale;
  const searchPanelState = {
    activeSearchGroupId,
    busyAddCardId,
    inventories,
    selectedInventoryCanWrite,
    searchResultsVisible,
    searchWorkspaceMode,
    search: {
      canLoadMore: searchCanLoadMore,
      error: searchError,
      groups: searchGroups,
      hiddenResultCount: searchHiddenResultCount,
      loadedHiddenResultCount: searchLoadedHiddenResultCount,
      isLoadingMore: searchLoadMoreBusy,
      isResultStale: searchResultsStale,
      loadMoreError: searchLoadMoreError,
      loadAllLanguages: searchLoadAllLanguages,
      query: searchQuery,
      resultQuery: searchResultQuery,
      resultScope: searchResultScope,
      scope: searchScope,
      status: searchStatus,
      totalCount: searchTotalCount,
    },
    selectedInventoryRow,
    writableInventories,
    suggestions: {
      error: suggestionError,
      highlightedIndex: highlightedSuggestionIndex,
      isOpen: suggestionOpen,
      results: suggestionResults,
      status: suggestionStatus,
    },
  };
  const searchPanelActions = {
    commitCsvImport,
    commitDeckUrlImport,
    commitDecklistImport,
    onAdd: handleAddCard,
    onCreateInventory: handleCreateInventory,
    onLoadPrintings: loadSearchGroupPrintings,
    onNotice: reportNotice,
    previewCsvImport,
    previewDeckUrlImport,
    previewDecklistImport,
    onSearchFieldFocus: handleSearchFieldFocus,
    onSearchInputKeyDown: handleSearchInputKeyDown,
    onSearchQueryChange: handleSearchQueryChange,
    onSearchGroupSelect: handleSearchGroupSelect,
    onSearchLoadAllLanguagesChange: handleSearchLoadAllLanguagesChange,
    onSearchResultsLoadMore: handleSearchResultsLoadMore,
    onSearchScopeChange: handleSearchScopeChange,
    onSearchResultsDismiss: dismissSearchResults,
    onSearchWorkspaceBrowse: handleSearchWorkspaceBrowse,
    onSearchSubmit: handleSearchSubmit,
    onSuggestionHighlight: setHighlightedSuggestionIndex,
    onSuggestionRequestClose: handleSuggestionRequestClose,
    onSuggestionSelect: handleSuggestionSelect,
  };
  const collectionPanelState = {
    collection: {
      browsePage,
      browsePageCount,
      browseVisibleLimit,
      browseVisibleLimitOptions,
      busyItem,
      filteredItemsCount: filteredCollectionItemsCount,
      searchQuery: collectionSearchQuery,
      detailModalItemId,
      focusedItemId,
      items: shouldHideStaleBrowseItems ? [] : collectionItems,
      visibleItems: shouldHideStaleBrowseItems ? [] : visibleCollectionItems,
      view: collectionView,
      viewError: shouldHideStaleBrowseItems ? null : collectionViewError,
      viewStatus: shouldHideStaleBrowseItems
        ? collectionViewStatus === "error"
          ? "error"
          : "loading"
        : collectionViewStatus,
    },
    selectedInventoryRow,
    canExportSelectedInventory: canExportInventory(selectedInventoryRow),
    exportInventoryBusy,
    selectedInventoryCanWrite,
    table: {
      allItemsCount:
        collectionView === "table" ? tablePageState.totalCount : filteredTableItemsCount,
      availableCopyTargetInventories,
      availableMoveTargetInventories,
      availableTargetInventories: availableTransferTargetInventories,
      bulkMutationBusy,
      canBulkEditSelectedInventory: selectedInventoryCanWrite,
      canCopyFromSelectedInventory: canCopyFromInventory(selectedInventoryRow),
      canMoveFromSelectedInventory: canMoveFromInventory(selectedInventoryRow),
      createInventoryBusy,
      filterOptions: tableFilterOptions,
      filters: tableFilters,
      items: collectionView === "table" ? tablePageState.items : visibleTableItems,
      page: tablePage,
      pageCount: collectionView === "table" ? tablePageState.pageCount : tablePageCount,
      selectedItemIds,
      sort: tableSort,
      transferBusy,
      viewError: tablePageState.error,
      viewStatus: tablePageState.status,
      visibleLimit: tableVisibleLimit,
      visibleLimitOptions: tableVisibleLimitOptions,
    },
  };
  const collectionPanelActions = {
    onBrowsePageChange: handleBrowsePageChange,
    onBrowseVisibleLimitChange: handleBrowseVisibleLimitChange,
    onBulkMutationSubmit: handleBulkMutation,
    onClearSelectedItems: handleClearSelectedItems,
    onClearVisibleSelectedItems: () => handleClearVisibleSelectedItems(activeTableItems),
    onCollectionViewChange: handleCollectionViewModeChange,
    onCloseItemDetails: handleCloseItemDetails,
    onCollectionSearchQueryChange: handleCollectionSearchQueryChange,
    onDelete: handleDeleteItem,
    onFocusImport: () =>
      setSearchFocusRequest((current) => ({
        target: "import",
        token: (current?.token ?? 0) + 1,
      })),
    onFocusSearch: () =>
      setSearchFocusRequest((current) => ({
        target: "search",
        token: (current?.token ?? 0) + 1,
      })),
    onExportCsv: handleExportInventoryCsv,
    onNotice: reportNotice,
    onOpenActivity: () => setActivityOpen(true),
    onOpenItemDetails: handleOpenItemDetails,
    onPatch: handlePatchItem,
    onCreateInventory: handleCreateInventory,
    onSelectTableItem: (
      itemId: number,
      options?: { additive?: boolean; range?: boolean },
    ) =>
      handleSelectTableItem(itemId, options, activeTableItems),
    onSelectAllVisibleItems: () => handleSelectAllVisibleItems(activeTableItems),
    onTransferItems: handleTransferItems,
    onTableFiltersChange: handleTableFiltersChange,
    onTablePageChange: handleTablePageChange,
    onTableSortChange: setTableSort,
    onTableVisibleLimitChange: handleTableVisibleLimitChange,
    onToggleItemSelection: handleToggleItemSelection,
  };
  const bannerNotice = notice && notice.tone !== "success" ? notice : null;
  const toastNotice = notice?.tone === "success" ? notice : null;
  const appShellState = getAppShellState({
    accessSummary,
    inventoryCount: inventories.length,
    inventoryStatus,
  });
  const shellStatePanels =
    appShellState === "ready" ? null : getShellStatePanelContent(appShellState);
  const showHeroCreateAction =
    appShellState === "ready" || appShellState === "bootstrap_available";
  const showHeroImportAction = appShellState === "ready";
  const workspaceTopGridClassName =
    appShellState === "ready" &&
    selectedInventoryCanWrite &&
    !searchResultsVisible
      ? "workspace-top-grid workspace-top-grid-controls-aligned"
      : "workspace-top-grid";

  useEffect(() => {
    setCollectionMenuOpen(false);
  }, [appShellState, selectedInventory]);

  useEffect(() => {
    if (appShellState !== "ready") {
      setStickyControlsVisible(false);
      return;
    }

    function updateStickyControlsVisibility() {
      const topSection = workspaceTopRef.current;
      if (!topSection) {
        return;
      }

      const nextVisible =
        window.scrollY > 0 && topSection.getBoundingClientRect().bottom <= 64;
      setStickyControlsVisible((current) =>
        current === nextVisible ? current : nextVisible,
      );
    }

    updateStickyControlsVisibility();
    window.addEventListener("scroll", updateStickyControlsVisibility, {
      passive: true,
    });
    window.addEventListener("resize", updateStickyControlsVisibility);
    return () => {
      window.removeEventListener("scroll", updateStickyControlsVisibility);
      window.removeEventListener("resize", updateStickyControlsVisibility);
    };
  }, [appShellState]);

  return (
    <div className="app-shell">
      {appShellState === "ready" && stickyControlsVisible ? (
        <StickyWorkspaceControls
          actions={searchPanelActions}
          collectionMenuOpen={collectionMenuOpen}
          inventories={inventories}
          onCollectionMenuOpenChange={setCollectionMenuOpen}
          onSelectInventory={setSelectedInventory}
          searchState={searchPanelState}
          selectedInventory={selectedInventory}
          selectedInventoryRow={selectedInventoryRow}
        />
      ) : null}

      <header className="hero">
        <div className="hero-copy-block">
          <p className="eyebrow">Card Collection</p>
          <h1>Stash Counter</h1>
          <p className="hero-copy">
            Search cards, compare printings, and organize your collection in one place.
          </p>
        </div>
        {showHeroCreateAction || showHeroImportAction ? (
          <div aria-label="Workspace actions" className="hero-actions">
            <div className="hero-actions-shell">
              <div className="hero-actions-list">
                {showHeroCreateAction ? (
                  <div
                    className="hero-action-slot hero-action-slot-create"
                    ref={setWorkspaceCreateActionHost}
                  />
                ) : null}
                {showHeroImportAction ? (
                  <div
                    className="hero-action-slot hero-action-slot-import"
                    ref={setWorkspaceImportActionHost}
                  />
                ) : null}
              </div>
            </div>
          </div>
        ) : null}
      </header>

      {bannerNotice ? <NoticeBanner notice={bannerNotice} /> : null}

      <div className="workspace-grid">
        <div className={workspaceTopGridClassName} ref={workspaceTopRef}>
          <aside className="sidebar-column">
            <InventorySidebar
              appShellState={appShellState}
              collectionMenuInteractionEnabled={!stickyControlsVisible}
              collectionMenuOpen={collectionMenuOpen}
              createActionHost={workspaceCreateActionHost}
              createActionHostEnabled={showHeroCreateAction}
              createInventoryBusy={createInventoryBusy}
              inventories={inventories}
              inventoryError={inventoryError}
              onCollectionMenuOpenChange={setCollectionMenuOpen}
              onCreateInventory={handleCreateInventory}
              onSelectInventory={setSelectedInventory}
              selectedInventory={selectedInventory}
              selectedInventoryRow={selectedInventoryRow}
            />
          </aside>

          <div className="workspace-search-column">
            {appShellState === "ready" ? (
              <SearchPanel
                actions={searchPanelActions}
                focusRequest={searchFocusRequest}
                importActionHost={workspaceImportActionHost}
                importActionHostEnabled={showHeroImportAction}
                state={searchPanelState}
              />
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
          auditEvents={collectionAuditEvents}
          embedded
          selectedInventoryRow={selectedInventoryRow}
          viewError={collectionViewError}
          viewStatus={collectionViewStatus}
        />
      </ActivityDrawer>

      {toastNotice ? (
        <NoticeToast notice={toastNotice} onDismiss={clearNotice} />
      ) : null}
    </div>
  );
}
