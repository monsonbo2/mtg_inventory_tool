import { useEffect, useState } from "react";

import {
  addInventoryItem,
  ApiClientError,
  bulkMutateInventoryItems,
  createInventory,
  deleteInventoryItem,
  patchInventoryItem,
} from "../api";
import type {
  AddInventoryItemRequest,
  BulkTagMutationOperation,
  InventoryCreateRequest,
  PatchInventoryItemRequest,
} from "../types";
import {
  getBulkMutationSuccessMessage,
  getPatchSuccessMessage,
  toUserMessage,
} from "../uiHelpers";
import type {
  InventoryCreateResult,
  ItemMutationAction,
  ItemMutationState,
  NoticeState,
  NoticeTone,
  ViewRefreshOutcome,
} from "../uiTypes";

const BULK_MUTATION_MAX_ITEMS = 100;

type UseInventoryMutationsOptions = {
  selectedInventory: string | null;
  describeInventory: (inventorySlug: string) => string;
  loadInventoryOverview: (
    inventorySlug: string,
    options?: { reloadInventories?: boolean; showLoading?: boolean },
  ) => Promise<ViewRefreshOutcome>;
  reloadInventorySummaries: (preferredSlug?: string | null) => Promise<boolean>;
  resetSearchWorkspace: () => void;
  selectedItemIds: number[];
  clearSelectedItems: () => void;
};

export function useInventoryMutations(options: UseInventoryMutationsOptions) {
  const [busyItem, setBusyItem] = useState<ItemMutationState | null>(null);
  const [busyAddCardId, setBusyAddCardId] = useState<string | null>(null);
  const [bulkTagsBusy, setBulkTagsBusy] = useState(false);
  const [createInventoryBusy, setCreateInventoryBusy] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);

  function getAddRequestBusyId(payload: AddInventoryItemRequest) {
    if ("scryfall_id" in payload) {
      return payload.scryfall_id;
    }
    if ("oracle_id" in payload) {
      return payload.oracle_id;
    }
    if ("tcgplayer_product_id" in payload) {
      return payload.tcgplayer_product_id;
    }
    return payload.name;
  }

  useEffect(() => {
    if (!notice || notice.tone !== "success") {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setNotice((currentNotice) =>
        currentNotice === notice ? null : currentNotice,
      );
    }, 3600);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [notice]);

  async function refreshAfterMutation(inventorySlug: string, successMessage: string) {
    try {
      await options.loadInventoryOverview(inventorySlug, { reloadInventories: true });
      showNotice(successMessage, "success");
    } catch {
      showNotice(
        `${successMessage} The latest view could not refresh automatically.`,
        "error",
      );
    }
  }

  function showNotice(message: string, tone: NoticeTone = "info") {
    setNotice({ message, tone });
  }

  function reportNotice(message: string, tone: NoticeTone = "info") {
    showNotice(message, tone);
  }

  function clearNotice() {
    setNotice(null);
  }

  function requireSelectedInventory(message: string) {
    if (!options.selectedInventory) {
      showNotice(message);
      return null;
    }
    return options.selectedInventory;
  }

  async function handleAddCard(payload: AddInventoryItemRequest) {
    const inventorySlug = requireSelectedInventory(
      "Select a collection before adding a card.",
    );
    if (!inventorySlug) {
      return false;
    }

    setBusyAddCardId(getAddRequestBusyId(payload));
    clearNotice();

    try {
      const response = await addInventoryItem(inventorySlug, payload);
      await refreshAfterMutation(
        inventorySlug,
        `Added ${response.card_name} to ${options.describeInventory(inventorySlug)}.`,
      );
      options.resetSearchWorkspace();
      return true;
    } catch (error) {
      showNotice(toUserMessage(error, "Could not add the card."), "error");
      return false;
    } finally {
      setBusyAddCardId(null);
    }
  }

  async function handleCreateInventory(
    payload: InventoryCreateRequest,
  ): Promise<InventoryCreateResult> {
    setCreateInventoryBusy(true);
    clearNotice();

    try {
      const response = await createInventory(payload);
      const refreshed = await options.reloadInventorySummaries(response.slug);

      showNotice(
        refreshed
          ? `Created ${response.display_name}.`
          : `Created ${response.display_name}. The collection list could not refresh automatically.`,
        refreshed ? "success" : "error",
      );
      return { ok: true };
    } catch (error) {
      if (error instanceof ApiClientError && error.status === 409) {
        return { ok: false, reason: "conflict" };
      }
      showNotice(toUserMessage(error, "Could not create the collection."), "error");
      return { ok: false, reason: "error" };
    } finally {
      setCreateInventoryBusy(false);
    }
  }

  async function handlePatchItem(
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) {
    const inventorySlug = requireSelectedInventory(
      "Select a collection before editing collection rows.",
    );
    if (!inventorySlug) {
      return;
    }

    setBusyItem({ itemId, action });
    clearNotice();

    try {
      const response = await patchInventoryItem(inventorySlug, itemId, payload);
      await refreshAfterMutation(
        inventorySlug,
        getPatchSuccessMessage(response, options.describeInventory(inventorySlug)),
      );
    } catch (error) {
      showNotice(toUserMessage(error, "Could not save the change."), "error");
    } finally {
      setBusyItem(null);
    }
  }

  async function handleDeleteItem(itemId: number, cardName: string) {
    const inventorySlug = requireSelectedInventory(
      "Select a collection before removing collection rows.",
    );
    if (!inventorySlug) {
      return;
    }

    setBusyItem({ itemId, action: "delete" });
    clearNotice();

    try {
      const response = await deleteInventoryItem(inventorySlug, itemId);
      await refreshAfterMutation(
        inventorySlug,
        `Removed ${response.card_name || cardName} from ${options.describeInventory(inventorySlug)}.`,
      );
    } catch (error) {
      showNotice(toUserMessage(error, "Could not remove the card."), "error");
    } finally {
      setBusyItem(null);
    }
  }

  async function handleBulkTagMutation(
    operation: BulkTagMutationOperation,
    tags: string[],
  ) {
    const inventorySlug = requireSelectedInventory(
      "Select a collection before editing collection rows.",
    );
    if (!inventorySlug) {
      return false;
    }

    if (!options.selectedItemIds.length) {
      showNotice("Select at least one row before running a bulk tag action.");
      return false;
    }

    if (options.selectedItemIds.length > BULK_MUTATION_MAX_ITEMS) {
      showNotice(
        `Bulk tag actions currently support up to ${BULK_MUTATION_MAX_ITEMS} rows at a time.`,
        "error",
      );
      return false;
    }

    if (operation !== "clear_tags" && tags.length === 0) {
      showNotice("Enter at least one tag before running this bulk tag action.");
      return false;
    }

    setBulkTagsBusy(true);
    clearNotice();

    try {
      const response =
        operation === "clear_tags"
          ? await bulkMutateInventoryItems(inventorySlug, {
              operation,
              item_ids: options.selectedItemIds,
            })
          : await bulkMutateInventoryItems(inventorySlug, {
              operation,
              item_ids: options.selectedItemIds,
              tags,
            });
      await refreshAfterMutation(
        inventorySlug,
        getBulkMutationSuccessMessage(
          response.operation,
          response.updated_count,
          options.describeInventory(inventorySlug),
        ),
      );
      options.clearSelectedItems();
      return true;
    } catch (error) {
      showNotice(toUserMessage(error, "Could not apply the bulk tag action."), "error");
      return false;
    } finally {
      setBulkTagsBusy(false);
    }
  }

  return {
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
  };
}
