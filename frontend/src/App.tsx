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
  inventoryErrorStatus: number | null;
  inventoryStatus: "idle" | "loading" | "ready" | "error";
}): AppShellState {
  if (options.inventoryCount > 0) {
    return "ready";
  }

  if (options.inventoryStatus === "idle" || options.inventoryStatus === "loading") {
    return "loading";
  }

  if (options.inventoryStatus === "error") {
    if (options.inventoryErrorStatus === 401) {
      return "auth_required";
    }

    if (options.inventoryErrorStatus === 403) {
      return "forbidden";
    }

    return "error";
  }

  return "no_visible_inventories";
}

function getShellStatePanelContent(
  appShellState: Exclude<AppShellState, "ready">,
  inventoryError: string | null,
) {
  switch (appShellState) {
    case "loading":
      return {
        body: "Checking collection access and loading the workspace.",
        title: "Loading workspace",
        variant: "loading" as const,
      };
    case "auth_required":
      return {
        body: "Sign in through the shared-service deployment before loading collections or card data.",
        title: "Authentication required",
        variant: "error" as const,
      };
    case "forbidden":
      return {
        body: "This account is signed in but does not currently have permission to view any collections.",
        title: "Collection access blocked",
        variant: "error" as const,
      };
    case "no_visible_inventories":
      return {
        body: "A visible collection is required before search, collection, and activity views can load.",
        title: "No visible collections",
        variant: "idle" as const,
      };
    case "error":
      return {
        body: inventoryError || "Could not load collections right now.",
        title: "Workspace unavailable",
        variant: "error" as const,
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
    inventoryErrorStatus,
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
    handleSearchFieldFocus,
    handleSearchInputKeyDown,
    handleSearchQueryChange,
    handleSearchSubmit,
    handleSuggestionRequestClose,
    handleSuggestionSelect,
    highlightedSuggestionIndex,
    loadSearchGroupPrintings,
    resetSearchWorkspace,
    searchError,
    searchGroups,
    searchQuery,
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
    focusedItemId,
    handleClearSelectedItems,
    handleClearVisibleSelectedItems,
    handleCollectionViewChange,
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
    bootstrapInventoryBusy,
    bulkTagsBusy,
    busyItem,
    clearNotice,
    createInventoryBusy,
    handleAddCard,
    handleBootstrapInventory,
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
    busyAddCardId,
    search: {
      error: searchError,
      groups: searchGroups,
      query: searchQuery,
      status: searchStatus,
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
    onSearchSubmit: handleSearchSubmit,
    onSuggestionHighlight: setHighlightedSuggestionIndex,
    onSuggestionRequestClose: handleSuggestionRequestClose,
    onSuggestionSelect: handleSuggestionSelect,
  };
  const collectionPanelState = {
    collection: {
      busyItem,
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
    inventoryErrorStatus,
    inventoryStatus,
  });
  const shellStatePanel =
    appShellState === "ready"
      ? null
      : getShellStatePanelContent(appShellState, inventoryError);

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Shared-Service Frontend</p>
          <h1>MTG Collection Studio</h1>
          <p className="hero-copy">
            The frontend tracks the current HTTP contract and now classifies
            shared-service loading, access, and empty-workspace states before
            the next onboarding pass lands.
          </p>
        </div>
        <div className="hero-metrics">
          <MetricCard accent="Sunrise" label="Collections" value={String(inventories.length)} />
          <MetricCard accent="Lagoon" label="Rows In View" value={String(items.length)} />
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
              bootstrapInventoryBusy={bootstrapInventoryBusy}
              createInventoryBusy={createInventoryBusy}
              inventories={inventories}
              inventoryError={inventoryError}
              inventoryStatus={inventoryStatus}
              onBootstrapInventory={handleBootstrapInventory}
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
                body={shellStatePanel!.body}
                title={shellStatePanel!.title}
                variant={shellStatePanel!.variant}
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
              body={shellStatePanel!.body}
              title={shellStatePanel!.title}
              variant={shellStatePanel!.variant}
            />
          )}
        </main>
      </div>

      <ActivityDrawer
        isOpen={activityOpen}
        onClose={() => setActivityOpen(false)}
        subtitle={
          selectedInventoryRow
            ? `${selectedInventoryRow.display_name} · latest 12 events`
            : "Choose a collection to inspect its recent write activity."
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
