import { useEffect, useState } from "react";

import {
  applyInventoryTableQuery,
  createDefaultInventoryTableFilters,
  getInventoryTableFilterOptions,
  type InventoryTableFilters,
  type InventoryTableSortState,
} from "../tableViewHelpers";
import type { OwnedInventoryRow } from "../types";

export function useCollectionViewState(options: {
  items: OwnedInventoryRow[];
  selectedInventory: string | null;
}) {
  const [collectionView, setCollectionView] = useState<
    "browse" | "table" | "detailed"
  >("browse");
  const [detailModalItemId, setDetailModalItemId] = useState<number | null>(null);
  const [focusedItemId, setFocusedItemId] = useState<number | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<number[]>([]);
  const [tableSort, setTableSort] = useState<InventoryTableSortState>(null);
  const [tableFilters, setTableFilters] = useState<InventoryTableFilters>(
    createDefaultInventoryTableFilters,
  );

  useEffect(() => {
    setDetailModalItemId(null);
    setFocusedItemId(null);
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
    setSelectedItemIds((current) =>
      current.filter((itemId) => visibleItemIds.has(itemId)),
    );
  }, [options.items]);

  function handleCollectionViewChange(nextView: "browse" | "table" | "detailed") {
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
    setSelectedItemIds((current) =>
      current.includes(itemId)
        ? current.filter((existingItemId) => existingItemId !== itemId)
        : [...current, itemId],
    );
  }

  const visibleTableItems = applyInventoryTableQuery(
    options.items,
    tableSort,
    tableFilters,
  );
  const tableFilterOptions = getInventoryTableFilterOptions(options.items);

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

  function handleClearVisibleSelectedItems() {
    const visibleItemIds = new Set(visibleTableItems.map((item) => item.item_id));
    setSelectedItemIds((current) =>
      current.filter((itemId) => !visibleItemIds.has(itemId)),
    );
  }

  function handleClearSelectedItems() {
    setSelectedItemIds([]);
  }

  return {
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
  };
}
