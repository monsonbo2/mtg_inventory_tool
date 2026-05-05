import { describe, expect, it } from "vitest";

import {
  canCopyFromInventory,
  canExportInventory,
  canManageShareInventory,
  canMoveFromInventory,
  getAvailableTransferTargetInventories,
  getTransferTargetInventories,
  isReadableInventory,
  isWritableInventory,
} from "./inventoryCapabilities";
import type { InventorySummary } from "./types";

function buildInventory(
  overrides: Partial<InventorySummary> & Pick<InventorySummary, "slug">,
): InventorySummary {
  return {
    acquisition_currency: null,
    acquisition_price: null,
    can_manage_share: false,
    can_read: true,
    can_transfer_to: false,
    can_write: false,
    default_location: null,
    default_tags: null,
    description: null,
    display_name: overrides.slug,
    item_rows: 0,
    notes: null,
    role: "viewer",
    total_cards: 0,
    ...overrides,
  };
}

describe("inventory capability helpers", () => {
  it("treats copy and export as readable-source actions", () => {
    const viewerInventory = buildInventory({
      slug: "viewer-source",
      can_read: true,
      can_write: false,
      role: "viewer",
    });

    expect(isReadableInventory(viewerInventory)).toBe(true);
    expect(isWritableInventory(viewerInventory)).toBe(false);
    expect(canCopyFromInventory(viewerInventory)).toBe(true);
    expect(canExportInventory(viewerInventory)).toBe(true);
    expect(canMoveFromInventory(viewerInventory)).toBe(false);
  });

  it("keeps move source eligibility write-based", () => {
    const writableInventory = buildInventory({
      slug: "writable-source",
      can_read: true,
      can_write: true,
      role: "editor",
    });

    expect(canCopyFromInventory(writableInventory)).toBe(true);
    expect(canExportInventory(writableInventory)).toBe(true);
    expect(canMoveFromInventory(writableInventory)).toBe(true);
  });

  it("keeps share management eligibility scoped to can_manage_share", () => {
    expect(
      canManageShareInventory(
        buildInventory({
          slug: "share-manager",
          can_manage_share: true,
          can_read: true,
          can_write: false,
          role: "owner",
        }),
      ),
    ).toBe(true);
    expect(
      canManageShareInventory(
        buildInventory({
          slug: "editor",
          can_manage_share: false,
          can_read: true,
          can_write: true,
          role: "editor",
        }),
      ),
    ).toBe(false);
    expect(canManageShareInventory(null)).toBe(false);
  });

  it("blocks source actions when an inventory is not readable", () => {
    const inaccessibleInventory = buildInventory({
      slug: "hidden-source",
      can_read: false,
      can_write: false,
      role: null,
    });

    expect(isReadableInventory(inaccessibleInventory)).toBe(false);
    expect(canCopyFromInventory(inaccessibleInventory)).toBe(false);
    expect(canExportInventory(inaccessibleInventory)).toBe(false);
    expect(canMoveFromInventory(inaccessibleInventory)).toBe(false);
  });

  it("uses can_transfer_to only for transfer destinations", () => {
    const viewerSource = buildInventory({
      slug: "viewer-source",
      can_read: true,
      can_write: false,
      role: "viewer",
    });
    const writableSource = buildInventory({
      slug: "writable-source",
      can_read: true,
      can_write: true,
      role: "editor",
    });
    const allowedTarget = buildInventory({
      slug: "allowed-target",
      can_read: true,
      can_transfer_to: true,
      can_write: true,
      role: "owner",
    });
    const blockedTarget = buildInventory({
      slug: "blocked-target",
      can_read: true,
      can_transfer_to: false,
      can_write: true,
      role: "owner",
    });
    const inventories = [viewerSource, writableSource, allowedTarget, blockedTarget];

    expect(
      getTransferTargetInventories(inventories, {
        mode: "copy",
        sourceInventory: viewerSource,
      }).map((inventory) => inventory.slug),
    ).toEqual(["allowed-target"]);
    expect(
      getTransferTargetInventories(inventories, {
        mode: "move",
        sourceInventory: viewerSource,
      }),
    ).toEqual([]);
    expect(
      getTransferTargetInventories(inventories, {
        mode: "move",
        sourceInventory: writableSource,
      }).map((inventory) => inventory.slug),
    ).toEqual(["allowed-target"]);
    expect(
      getAvailableTransferTargetInventories(inventories, viewerSource).map(
        (inventory) => inventory.slug,
      ),
    ).toEqual(["allowed-target"]);
  });
});
