import { useEffect, useState } from "react";

import { ActivityDrawer } from "./components/ActivityDrawer";
import { AuditFeed } from "./components/AuditFeed";
import { InventorySidebar } from "./components/InventorySidebar";
import { OwnedCollectionPanel } from "./components/OwnedCollectionPanel";
import { SearchPanel } from "./components/SearchPanel";
import { MetricCard } from "./components/ui/MetricCard";
import { NoticeBanner } from "./components/ui/NoticeBanner";
import { NoticeToast } from "./components/ui/NoticeToast";
import { useCardSearch } from "./hooks/useCardSearch";
import { useCollectionViewState } from "./hooks/useCollectionViewState";
import { useInventoryOverview } from "./hooks/useInventoryOverview";
import { useInventoryMutations } from "./hooks/useInventoryMutations";
import { decimalToNumber, formatUsd } from "./uiHelpers";

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
    expandedItemId,
    handleClearSelectedItems,
    handleClearVisibleSelectedItems,
    handleCollectionViewChange,
    handleSelectAllVisibleItems,
    handleToggleItemSelection,
    selectedItemIds,
    setExpandedItemId,
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
      expandedItemId,
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
    onExpandedItemChange: setExpandedItemId,
    onNotice: reportNotice,
    onOpenActivity: () => setActivityOpen(true),
    onPatch: handlePatchItem,
    onSelectAllVisibleItems: handleSelectAllVisibleItems,
    onTableFiltersChange: setTableFilters,
    onTableSortChange: setTableSort,
    onToggleItemSelection: handleToggleItemSelection,
  };
  const bannerNotice = notice && notice.tone !== "success" ? notice : null;
  const toastNotice = notice?.tone === "success" ? notice : null;

  return (
    <div className="app-shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Local Demo Frontend</p>
          <h1>MTG Collection Studio</h1>
          <p className="hero-copy">
            A local collection workbench for the demo app. The frontend now
            tracks the current HTTP contract, supports seeded multi-collection
            states, and is ready for a final Stage 1 signoff pass.
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
              createInventoryBusy={createInventoryBusy}
              inventories={inventories}
              inventoryError={inventoryError}
              inventoryStatus={inventoryStatus}
              onCreateInventory={handleCreateInventory}
              onSelectInventory={setSelectedInventory}
              selectedInventory={selectedInventory}
              selectedInventoryRow={selectedInventoryRow}
            />
          </aside>

          <div className="workspace-search-column">
            <SearchPanel actions={searchPanelActions} state={searchPanelState} />
          </div>
        </div>

        <main className="workspace-main-row">
          <OwnedCollectionPanel
            actions={collectionPanelActions}
            state={collectionPanelState}
          />
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
