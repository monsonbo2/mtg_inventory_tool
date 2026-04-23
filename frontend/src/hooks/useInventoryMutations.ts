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
  transferInventoryItems,
} from "../api";
import type {
  AddInventoryItemRequest,
  BulkInventoryItemMutationRequest,
  CsvImportResponse,
  DeckUrlImportResponse,
  DecklistImportResponse,
  InventoryCreateRequest,
  InventoryTransferMode,
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
const TRANSFER_MUTATION_MAX_ITEMS = 100;

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
  selectedInventoryItemCount: number;
  clearSelectedItems: () => void;
};

export function useInventoryMutations(options: UseInventoryMutationsOptions) {
  const [busyItem, setBusyItem] = useState<ItemMutationState | null>(null);
  const [busyAddCardId, setBusyAddCardId] = useState<string | null>(null);
  const [bulkMutationBusy, setBulkMutationBusy] = useState(false);
  const [createInventoryBusy, setCreateInventoryBusy] = useState(false);
  const [notice, setNotice] = useState<NoticeState | null>(null);
  const [transferBusy, setTransferBusy] = useState<InventoryTransferMode | null>(null);

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

  function getImportIssueLabel(issue: InventoryImportResponse["resolution_issues"][number]) {
    const requested = issue.requested as Record<string, unknown>;
    const requestedName =
      typeof requested.name === "string" && requested.name.trim()
        ? requested.name.trim()
        : null;
    if (requestedName) {
      return requestedName;
    }

    const requestedScryfallId =
      typeof requested.scryfall_id === "string" && requested.scryfall_id.trim()
        ? requested.scryfall_id.trim()
        : null;
    if (requestedScryfallId) {
      return requestedScryfallId;
    }

    if ("source_position" in issue) {
      return `card at deck position ${issue.source_position}`;
    }
    if ("decklist_line" in issue) {
      return `card on decklist line ${issue.decklist_line}`;
    }
    return `card on CSV row ${issue.csv_row}`;
  }

  function getImportIssueMessage(response: InventoryImportResponse) {
    const labels = Array.from(
      new Set(
        response.resolution_issues
          .map(getImportIssueLabel)
          .filter((label) => Boolean(label)),
      ),
    );

    if (labels.length === 0) {
      return "Some cards could not be imported.";
    }
    if (labels.length === 1) {
      return `Could not import ${labels[0]}.`;
    }
    if (labels.length === 2) {
      return `Could not import ${labels[0]} and ${labels[1]}.`;
    }
    return `Could not import ${labels[0]}, ${labels[1]}, and ${labels.length - 2} other cards.`;
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
      if (response.resolution_issues.length > 0) {
        const issueMessage = getImportIssueMessage(response);

        if (response.rows_written <= 0) {
          showNotice(issueMessage, "error");
          return false;
        }

        const importingIntoDifferentCollection = inventorySlug !== options.selectedInventory;
        try {
          if (importingIntoDifferentCollection) {
            await options.reloadInventorySummaries(inventorySlug);
          }

          await options.loadInventoryOverview(inventorySlug, {
            reloadInventories: !importingIntoDifferentCollection,
          });
          showNotice(
            `${getImportSuccessMessage(response, inventorySlug, inventoryLabel)} ${issueMessage}`,
            "error",
          );
        } catch {
          showNotice(
            `${getImportSuccessMessage(response, inventorySlug, inventoryLabel)} ${issueMessage} The latest view could not refresh automatically.`,
            "error",
          );
        }
        options.resetSearchWorkspace();
        return true;
      }

      if (!response.ready_to_commit) {
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

  async function handleTransferItems(request: {
    mode: InventoryTransferMode;
    targetInventorySlug: string | null;
    targetInventoryLabel?: string | null;
  }) {
    const sourceInventorySlug = requireSelectedInventory(
      "Select a collection before copying or moving cards.",
    );
    if (!sourceInventorySlug) {
      return false;
    }

    if (!options.selectedItemIds.length) {
      showNotice("Select at least one entry before copying or moving cards.", "error");
      return false;
    }

    if (!request.targetInventorySlug) {
      showNotice("Choose a destination collection before copying or moving cards.", "error");
      return false;
    }

    if (request.targetInventorySlug === sourceInventorySlug) {
      showNotice("Choose a different destination collection.", "error");
      return false;
    }

    const transferringEntireCollection =
      options.selectedInventoryItemCount > 0 &&
      options.selectedItemIds.length === options.selectedInventoryItemCount;

    if (!transferringEntireCollection && options.selectedItemIds.length > TRANSFER_MUTATION_MAX_ITEMS) {
      showNotice(
        `Copy and move currently support up to ${TRANSFER_MUTATION_MAX_ITEMS} selected entries at a time unless you select the entire collection.`,
        "error",
      );
      return false;
    }

    setTransferBusy(request.mode);
    clearNotice();

    try {
      const response = await transferInventoryItems(sourceInventorySlug, {
        target_inventory_slug: request.targetInventorySlug,
        mode: request.mode,
        on_conflict: "merge",
        keep_acquisition: "source",
        ...(transferringEntireCollection
          ? { all_items: true as const }
          : { item_ids: options.selectedItemIds }),
      });

      const transferredCount = response.requested_count;
      await refreshAfterMutation(
        sourceInventorySlug,
        `${request.mode === "copy" ? "Copied" : "Moved"} ${transferredCount} entr${
          transferredCount === 1 ? "y" : "ies"
        } to ${
          request.targetInventoryLabel || options.describeInventory(request.targetInventorySlug)
        }.`,
      );
      options.clearSelectedItems();
      return true;
    } catch (error) {
      showNotice(
        toUserMessage(
          error,
          request.mode === "copy"
            ? "Could not copy the selected entries."
            : "Could not move the selected entries.",
        ),
        "error",
      );
      return false;
    } finally {
      setTransferBusy(null);
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
    handleTransferItems,
    notice,
    reportNotice,
    transferBusy,
  };
}
