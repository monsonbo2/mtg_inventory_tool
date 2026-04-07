import { useEffect, useState } from "react";

import {
  applyInventoryTableQuery,
  createDefaultInventoryTableFilters,
  getInventoryTableFilterOptions,
  type InventoryTableFilters,
  type InventoryTableSortState,
} from "../tableViewHelpers";
import type { OwnedInventoryRow } from "../types";

const BROWSE_VISIBLE_LIMIT_OPTIONS = [25, 50, 100] as const;
const TABLE_VISIBLE_LIMIT_OPTIONS = [50, 100, 200] as const;

function getPageCount(totalItems: number, pageSize: number) {
  return Math.max(1, Math.ceil(totalItems / pageSize));
}

export function useCollectionViewState(options: {
  items: OwnedInventoryRow[];
  selectedInventory: string | null;
}) {
  const [selectionAnchorItemId, setSelectionAnchorItemId] = useState<number | null>(null);
  const [collectionView, setCollectionView] = useState<"browse" | "table">("browse");
  const [detailModalItemId, setDetailModalItemId] = useState<number | null>(null);
  const [focusedItemId, setFocusedItemId] = useState<number | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<number[]>([]);
  const [browsePage, setBrowsePage] = useState(1);
  const [browseVisibleLimit, setBrowseVisibleLimit] = useState<number>(
    BROWSE_VISIBLE_LIMIT_OPTIONS[0],
  );
  const [tablePage, setTablePage] = useState(1);
  const [tableVisibleLimit, setTableVisibleLimit] = useState<number>(
    TABLE_VISIBLE_LIMIT_OPTIONS[0],
  );
  const [tableSort, setTableSort] = useState<InventoryTableSortState>(null);
  const [tableFilters, setTableFilters] = useState<InventoryTableFilters>(
    createDefaultInventoryTableFilters,
  );

  useEffect(() => {
    setCollectionView((currentView) => (currentView === "table" ? "table" : "browse"));
    setDetailModalItemId(null);
    setFocusedItemId(null);
    setSelectionAnchorItemId(null);
    setBrowsePage(1);
    setBrowseVisibleLimit(BROWSE_VISIBLE_LIMIT_OPTIONS[0]);
    setTablePage(1);
    setTableVisibleLimit(TABLE_VISIBLE_LIMIT_OPTIONS[0]);
    setTableSort(null);
    setTableFilters(createDefaultInventoryTableFilters());
    setSelectedItemIds([]);
  }, [options.selectedInventory]);

  useEffect(() => {
    const visibleItemIds = new Set(options.items.map((item) => item.item_id));
    setDetailModalItemId((current) =>
      current !== null && visibleItemIds.has(current) ? current : null,
    );
    setFocusedItemId((current) => (current !== null && visibleItemIds.has(current) ? current : null));
    setSelectionAnchorItemId((current) =>
      current !== null && visibleItemIds.has(current) ? current : null,
    );
    setSelectedItemIds((current) =>
      current.filter((itemId) => visibleItemIds.has(itemId)),
    );
  }, [options.items]);

  function handleCollectionViewChange(nextView: "browse" | "table") {
    setDetailModalItemId(null);
    setFocusedItemId(null);
    setCollectionView(nextView);
  }

  function handleOpenItemDetails(itemId: number) {
    setDetailModalItemId(itemId);
  }

  function handleCloseItemDetails() {
    setDetailModalItemId(null);
  }

  function handleToggleItemSelection(itemId: number) {
    setSelectionAnchorItemId(itemId);
    setSelectedItemIds((current) =>
      current.includes(itemId)
        ? current.filter((existingItemId) => existingItemId !== itemId)
        : [...current, itemId],
    );
  }

  const filteredTableItems = applyInventoryTableQuery(
    options.items,
    tableSort,
    tableFilters,
  );
  const normalizedCollectionSearchQuery = tableFilters.nameQuery.trim().toLowerCase();
  const filteredCollectionItems = normalizedCollectionSearchQuery
    ? options.items.filter((item) =>
        item.name.toLowerCase().includes(normalizedCollectionSearchQuery),
      )
    : options.items;
  const browsePageCount = getPageCount(filteredCollectionItems.length, browseVisibleLimit);
  const tablePageCount = getPageCount(filteredTableItems.length, tableVisibleLimit);
  const activeBrowsePage = Math.min(browsePage, browsePageCount);
  const activeTablePage = Math.min(tablePage, tablePageCount);
  const visibleCollectionItems = filteredCollectionItems.slice(
    (activeBrowsePage - 1) * browseVisibleLimit,
    activeBrowsePage * browseVisibleLimit,
  );
  const visibleTableItems = filteredTableItems.slice(
    (activeTablePage - 1) * tableVisibleLimit,
    activeTablePage * tableVisibleLimit,
  );
  const tableFilterOptions = getInventoryTableFilterOptions(options.items);

  useEffect(() => {
    setBrowsePage((currentPage) => Math.min(currentPage, browsePageCount));
  }, [browsePageCount]);

  useEffect(() => {
    setTablePage((currentPage) => Math.min(currentPage, tablePageCount));
  }, [tablePageCount]);

  function handleCollectionSearchQueryChange(nextQuery: string) {
    setBrowsePage(1);
    setTablePage(1);
    setTableFilters((current) => ({
      ...current,
      nameQuery: nextQuery,
    }));
  }

  function handleBrowseVisibleLimitChange(nextLimit: number) {
    if (
      !BROWSE_VISIBLE_LIMIT_OPTIONS.includes(
        nextLimit as (typeof BROWSE_VISIBLE_LIMIT_OPTIONS)[number],
      )
    ) {
      return;
    }
    setBrowsePage(1);
    setBrowseVisibleLimit(nextLimit);
  }

  function handleTableVisibleLimitChange(nextLimit: number) {
    if (
      !TABLE_VISIBLE_LIMIT_OPTIONS.includes(
        nextLimit as (typeof TABLE_VISIBLE_LIMIT_OPTIONS)[number],
      )
    ) {
      return;
    }
    setTablePage(1);
    setTableVisibleLimit(nextLimit);
  }

  function handleBrowsePageChange(nextPage: number) {
    setBrowsePage(Math.min(Math.max(nextPage, 1), browsePageCount));
  }

  function handleTablePageChange(nextPage: number) {
    setTablePage(Math.min(Math.max(nextPage, 1), tablePageCount));
  }

  function handleTableFiltersChange(nextFilters: InventoryTableFilters) {
    setTablePage(1);
    setTableFilters(nextFilters);
  }

  function handleSelectTableItem(
    itemId: number,
    options: { additive?: boolean; range?: boolean } = {},
  ) {
    const additive = options.additive ?? false;
    const range = options.range ?? false;
    const nextAnchorItemId = selectionAnchorItemId ?? itemId;

    if (range) {
      const anchorIndex = visibleTableItems.findIndex(
        (item) => item.item_id === nextAnchorItemId,
      );
      const targetIndex = visibleTableItems.findIndex((item) => item.item_id === itemId);

      if (anchorIndex === -1 || targetIndex === -1) {
        setSelectionAnchorItemId(itemId);
        setSelectedItemIds((current) =>
          additive
            ? current.includes(itemId)
              ? current
              : [...current, itemId]
            : [itemId],
        );
        return;
      }

      const rangeStart = Math.min(anchorIndex, targetIndex);
      const rangeEnd = Math.max(anchorIndex, targetIndex);
      const rangeItemIds = visibleTableItems
        .slice(rangeStart, rangeEnd + 1)
        .map((item) => item.item_id);

      setSelectionAnchorItemId(itemId);
      setSelectedItemIds((current) => {
        if (!additive) {
          return rangeItemIds;
        }

        const nextSelectedItemIds = new Set(current);
        for (const rangeItemId of rangeItemIds) {
          nextSelectedItemIds.add(rangeItemId);
        }
        return Array.from(nextSelectedItemIds);
      });
      return;
    }

    setSelectionAnchorItemId(itemId);
    setSelectedItemIds((current) => {
      if (!additive) {
        return [itemId];
      }

      return current.includes(itemId) ? current : [...current, itemId];
    });
  }

  function handleSelectAllVisibleItems() {
    const visibleItemIds = visibleTableItems.map((item) => item.item_id);
    setSelectedItemIds((current) => {
      const nextSelectedItemIds = new Set(current);
      for (const itemId of visibleItemIds) {
        nextSelectedItemIds.add(itemId);
      }
      return Array.from(nextSelectedItemIds);
    });
  }

  function handleSelectAllCollectionItems() {
    setSelectionAnchorItemId(visibleTableItems[0]?.item_id ?? options.items[0]?.item_id ?? null);
    setSelectedItemIds(options.items.map((item) => item.item_id));
  }

  function handleClearVisibleSelectedItems() {
    const visibleItemIds = new Set(visibleTableItems.map((item) => item.item_id));
    setSelectionAnchorItemId((current) =>
      current !== null && visibleItemIds.has(current) ? null : current,
    );
    setSelectedItemIds((current) =>
      current.filter((itemId) => !visibleItemIds.has(itemId)),
    );
  }

  function handleClearSelectedItems() {
    setSelectionAnchorItemId(null);
    setSelectedItemIds([]);
  }

  return {
    collectionView,
    collectionSearchQuery: tableFilters.nameQuery,
    browsePage: activeBrowsePage,
    browsePageCount,
    browseVisibleLimit,
    browseVisibleLimitOptions: [...BROWSE_VISIBLE_LIMIT_OPTIONS],
    detailModalItemId,
    filteredCollectionItemsCount: filteredCollectionItems.length,
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
    handleSelectAllCollectionItems,
    handleToggleItemSelection,
    handleTableFiltersChange,
    handleTablePageChange,
    selectedItemIds,
    setTableSort,
    tablePage: activeTablePage,
    tablePageCount,
    tableVisibleLimit,
    tableVisibleLimitOptions: [...TABLE_VISIBLE_LIMIT_OPTIONS],
    tableFilterOptions,
    tableFilters,
    tableSort,
    filteredTableItemsCount: filteredTableItems.length,
    handleTableVisibleLimitChange,
    visibleCollectionItems,
    visibleTableItems,
  };
}
