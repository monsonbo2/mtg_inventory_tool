import { useEffect, useState } from "react";

import {
  addInventoryItem,
  ApiClientError,
  bulkMutateInventoryItems,
  createInventory,
  deleteInventoryItem,
  importCsv,
  importDecklist,
  importDeckUrl,
  patchInventoryItem,
} from "../api";
import type {
  AddInventoryItemRequest,
  BulkInventoryItemMutationRequest,
  CsvImportResponse,
  DeckUrlImportResponse,
  DecklistImportResponse,
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

const BULK_MUTATION_MAX_ITEMS = 200;

type InventoryImportResponse =
  | CsvImportResponse
  | DeckUrlImportResponse
  | DecklistImportResponse;

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
  const [bulkMutationBusy, setBulkMutationBusy] = useState(false);
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

  async function refreshAfterMutation(
    inventorySlug: string,
    successMessage: string,
    refreshOptions: { reloadInventories?: boolean } = {},
  ) {
    try {
      await options.loadInventoryOverview(inventorySlug, {
        reloadInventories: refreshOptions.reloadInventories ?? true,
      });
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

  function getImportCardCount(response: InventoryImportResponse) {
    return response.summary.total_card_quantity || response.rows_written;
  }

  function getImportSuccessMessage(
    response: InventoryImportResponse,
    inventorySlug: string,
    inventoryLabel?: string | null,
  ) {
    const importedCount = getImportCardCount(response);
    const destinationLabel = inventoryLabel || options.describeInventory(inventorySlug);
    return `Imported ${importedCount} card${
      importedCount === 1 ? "" : "s"
    } into ${destinationLabel}.`;
  }

  async function handleImportResponse(
    inventorySlug: string,
    inventoryLabel: string | null | undefined,
    fallbackMessage: string,
    loadResponse: () => Promise<InventoryImportResponse>,
  ) {
    clearNotice();

    try {
      const response = await loadResponse();
      if (!response.ready_to_commit || response.resolution_issues.length > 0) {
        showNotice(
          "This import still needs manual resolution. The preview flow is not wired into the frontend yet.",
          "error",
        );
        return false;
      }

      const importingIntoDifferentCollection = inventorySlug !== options.selectedInventory;
      if (importingIntoDifferentCollection) {
        await options.reloadInventorySummaries(inventorySlug);
      }

      await refreshAfterMutation(
        inventorySlug,
        getImportSuccessMessage(response, inventorySlug, inventoryLabel),
        { reloadInventories: !importingIntoDifferentCollection },
      );
      options.resetSearchWorkspace();
      return true;
    } catch (error) {
      showNotice(toUserMessage(error, fallbackMessage), "error");
      return false;
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
      return { ok: true, inventory: response };
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

  async function handleImportDecklist(
    deckText: string,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) {
    if (!inventorySlug) {
      showNotice("Choose a collection before importing cards.");
      return false;
    }

    return handleImportResponse(
      inventorySlug,
      inventoryLabel,
      "Could not import cards from text.",
      () =>
        importDecklist({
          deck_text: deckText,
          default_inventory: inventorySlug,
        }),
    );
  }

  async function handleImportDeckUrl(
    sourceUrl: string,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) {
    if (!inventorySlug) {
      showNotice("Choose a collection before importing cards.");
      return false;
    }

    return handleImportResponse(
      inventorySlug,
      inventoryLabel,
      "Could not import cards from the deck URL.",
      () =>
        importDeckUrl({
          source_url: sourceUrl,
          default_inventory: inventorySlug,
        }),
    );
  }

  async function handleImportCsv(
    file: Blob,
    inventorySlug: string | null,
    inventoryLabel?: string | null,
  ) {
    if (!inventorySlug) {
      showNotice("Choose a collection before importing cards.");
      return false;
    }

    return handleImportResponse(
      inventorySlug,
      inventoryLabel,
      "Could not import cards from the CSV file.",
      () =>
        importCsv({
          file,
          default_inventory: inventorySlug,
        }),
    );
  }

  async function handlePatchItem(
    itemId: number,
    action: ItemMutationAction,
    payload: PatchInventoryItemRequest,
  ) {
    const inventorySlug = requireSelectedInventory(
      "Select a collection before making changes.",
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
      "Select a collection before removing cards.",
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

  function getBulkMutationSelectionError(payload: BulkInventoryItemMutationRequest) {
    if (!payload.item_ids.length) {
      return "Select at least one entry before making bulk changes.";
    }

    if (payload.item_ids.length > BULK_MUTATION_MAX_ITEMS) {
      return `Bulk edit currently supports up to ${BULK_MUTATION_MAX_ITEMS} entries at a time.`;
    }

    return null;
  }

  function getBulkMutationValidationError(payload: BulkInventoryItemMutationRequest) {
    switch (payload.operation) {
      case "add_tags":
      case "remove_tags":
      case "set_tags":
        return payload.tags.length === 0
          ? "Enter at least one tag before running this bulk tag action."
          : null;
      case "set_location":
        return "location" in payload || "clear_location" in payload
          ? null
          : "Enter a location or clear the current one before running this bulk edit.";
      case "set_notes":
        return "notes" in payload || "clear_notes" in payload
          ? null
          : "Enter notes or clear the current notes before running this bulk edit.";
      case "clear_tags":
      case "set_quantity":
      case "set_acquisition":
      case "set_finish":
      case "set_condition":
        return null;
    }
  }

  function getBulkMutationFallbackMessage(payload: BulkInventoryItemMutationRequest) {
    switch (payload.operation) {
      case "add_tags":
      case "remove_tags":
      case "set_tags":
      case "clear_tags":
        return "Could not apply the bulk tag action.";
      case "set_location":
        return "Could not update the location on the selected entries.";
      case "set_notes":
        return "Could not update notes on the selected entries.";
      case "set_quantity":
        return "Could not update quantity on the selected entries.";
      case "set_acquisition":
        return "Could not update acquisition details on the selected entries.";
      case "set_finish":
        return "Could not update finish on the selected entries.";
      case "set_condition":
        return "Could not update condition on the selected entries.";
    }
  }

  async function handleBulkMutation(payload: BulkInventoryItemMutationRequest) {
    const inventorySlug = requireSelectedInventory(
      "Select a collection before making changes.",
    );
    if (!inventorySlug) {
      return false;
    }

    const selectionError = getBulkMutationSelectionError(payload);
    if (selectionError) {
      showNotice(selectionError, "error");
      return false;
    }

    const validationError = getBulkMutationValidationError(payload);
    if (validationError) {
      showNotice(validationError, "error");
      return false;
    }

    setBulkMutationBusy(true);
    clearNotice();

    try {
      const response = await bulkMutateInventoryItems(inventorySlug, payload);
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
      showNotice(
        toUserMessage(error, getBulkMutationFallbackMessage(payload)),
        "error",
      );
      return false;
    } finally {
      setBulkMutationBusy(false);
    }
  }

  return {
    busyAddCardId,
    bulkMutationBusy,
    busyItem,
    clearNotice,
    createInventoryBusy,
    handleAddCard,
    handleBulkMutation,
    handleCreateInventory,
    handleDeleteItem,
    handleImportCsv,
    handleImportDecklist,
    handleImportDeckUrl,
    handlePatchItem,
    notice,
    reportNotice,
  };
}
