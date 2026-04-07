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
  const [selectionAnchorItemId, setSelectionAnchorItemId] = useState<number | null>(null);
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
    setSelectionAnchorItemId(null);
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
    setSelectionAnchorItemId(itemId);
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
  const normalizedCollectionSearchQuery = tableFilters.nameQuery.trim().toLowerCase();
  const visibleCollectionItems = normalizedCollectionSearchQuery
    ? options.items.filter((item) =>
        item.name.toLowerCase().includes(normalizedCollectionSearchQuery),
      )
    : options.items;
  const tableFilterOptions = getInventoryTableFilterOptions(options.items);

  function handleCollectionSearchQueryChange(nextQuery: string) {
    setTableFilters((current) => ({
      ...current,
      nameQuery: nextQuery,
    }));
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
    detailModalItemId,
    focusedItemId,
    handleClearSelectedItems,
    handleClearVisibleSelectedItems,
    handleCollectionViewChange,
    handleCloseItemDetails,
    handleCollectionSearchQueryChange,
    handleOpenItemDetails,
    handleSelectTableItem,
    handleSelectAllVisibleItems,
    handleToggleItemSelection,
    selectedItemIds,
    setTableFilters,
    setTableSort,
    tableFilterOptions,
    tableFilters,
    tableSort,
    visibleCollectionItems,
    visibleTableItems,
  };
}
