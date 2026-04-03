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
    "compact" | "table" | "detailed"
  >("compact");
  const [expandedItemId, setExpandedItemId] = useState<number | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<number[]>([]);
  const [tableSort, setTableSort] = useState<InventoryTableSortState>(null);
  const [tableFilters, setTableFilters] = useState<InventoryTableFilters>(
    createDefaultInventoryTableFilters,
  );

  useEffect(() => {
    setTableSort(null);
    setTableFilters(createDefaultInventoryTableFilters());
    setExpandedItemId(null);
    setSelectedItemIds([]);
  }, [options.selectedInventory]);

  useEffect(() => {
    const visibleItemIds = new Set(options.items.map((item) => item.item_id));
    setSelectedItemIds((current) =>
      current.filter((itemId) => visibleItemIds.has(itemId)),
    );
  }, [options.items]);

  function handleCollectionViewChange(nextView: "compact" | "table" | "detailed") {
    setCollectionView(nextView);
    if (nextView !== "compact") {
      setExpandedItemId(null);
    }
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
  };
}
