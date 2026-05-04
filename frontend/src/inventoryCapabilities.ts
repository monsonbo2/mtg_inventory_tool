import type { InventorySummary, InventoryTransferMode } from "./types";

export function isReadableInventory(inventory: InventorySummary | null): boolean {
  return Boolean(inventory?.can_read);
}

export function isWritableInventory(inventory: InventorySummary | null): boolean {
  return Boolean(inventory?.can_write);
}

export function canManageShareInventory(inventory: InventorySummary | null): boolean {
  return Boolean(inventory?.can_manage_share);
}

export function canTransferIntoInventory(inventory: InventorySummary): boolean {
  return inventory.can_transfer_to;
}

export function canCopyFromInventory(inventory: InventorySummary | null): boolean {
  return isReadableInventory(inventory);
}

export function canMoveFromInventory(inventory: InventorySummary | null): boolean {
  return isWritableInventory(inventory);
}

export function canExportInventory(inventory: InventorySummary | null): boolean {
  return isReadableInventory(inventory);
}

export function getWritableInventories(
  inventories: InventorySummary[],
): InventorySummary[] {
  return inventories.filter((inventory) => isWritableInventory(inventory));
}

export function getTransferTargetInventories(
  inventories: InventorySummary[],
  options: {
    mode: InventoryTransferMode;
    sourceInventory: InventorySummary | null;
  },
): InventorySummary[] {
  const canTransferFromSource =
    options.mode === "copy"
      ? canCopyFromInventory(options.sourceInventory)
      : canMoveFromInventory(options.sourceInventory);

  if (!canTransferFromSource) {
    return [];
  }

  return inventories.filter(
    (inventory) =>
      inventory.slug !== options.sourceInventory?.slug &&
      canTransferIntoInventory(inventory),
  );
}

export function getAvailableTransferTargetInventories(
  inventories: InventorySummary[],
  sourceInventory: InventorySummary | null,
): InventorySummary[] {
  const transferTargetInventoriesBySlug = new Map<string, InventorySummary>();

  for (const inventory of getTransferTargetInventories(inventories, {
    mode: "copy",
    sourceInventory,
  })) {
    transferTargetInventoriesBySlug.set(inventory.slug, inventory);
  }

  for (const inventory of getTransferTargetInventories(inventories, {
    mode: "move",
    sourceInventory,
  })) {
    transferTargetInventoriesBySlug.set(inventory.slug, inventory);
  }

  return Array.from(transferTargetInventoriesBySlug.values());
}
