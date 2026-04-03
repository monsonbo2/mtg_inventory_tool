import { ApiClientError } from "./api";
import type {
  BulkInventoryItemOperation,
  FinishInput,
  FinishValue,
  InventoryAuditEvent,
  InventoryItemPatchResponse,
  InventorySummary,
  OwnedInventoryRow,
} from "./types";
import type { AsyncStatus, ItemMutationAction } from "./uiTypes";

export const FINISH_OPTIONS: Array<{ value: FinishValue; label: string }> = [
  { value: "normal", label: "Normal" },
  { value: "foil", label: "Foil" },
  { value: "etched", label: "Etched" },
];

export function parseTags(value: string) {
  return value
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean)
    .filter((tag, index, tags) => tags.indexOf(tag) === index);
}

export function decimalToNumber(value: string | null) {
  if (!value) {
    return 0;
  }
  return Number.parseFloat(value);
}

export function formatUsd(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value || 0);
}

export function formatMaybeCurrency(value: string | null, currency: string | null) {
  if (!value) {
    return "Not set";
  }
  if (currency === "USD" || !currency) {
    return formatUsd(decimalToNumber(value));
  }
  return `${value} ${currency}`;
}

export function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function toUserMessage(error: unknown, fallback: string) {
  if (error instanceof ApiClientError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}

export function resolveSelectedInventorySlug(
  inventories: InventorySummary[],
  preferredSlug: string | null,
) {
  if (preferredSlug && inventories.some((inventory) => inventory.slug === preferredSlug)) {
    return preferredSlug;
  }

  return inventories[0]?.slug ?? null;
}

export function getBusyMessage(action: ItemMutationAction) {
  switch (action) {
    case "quantity":
      return "Saving quantity...";
    case "finish":
      return "Saving finish...";
    case "location":
      return "Saving location...";
    case "notes":
      return "Saving notes...";
    case "tags":
      return "Saving tags...";
    case "delete":
      return "Removing row...";
  }
}

export function normalizeOptionalText(value: string | null | undefined) {
  const text = value?.trim();
  return text ? text : null;
}

export function normalizeInventorySlugInput(value: string) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function equalStringArrays(left: string[], right: string[]) {
  if (left.length !== right.length) {
    return false;
  }

  return left.every((value, index) => value === right[index]);
}

export function getInventoryCollectionEmptyMessage(inventory: InventorySummary) {
  if (inventory.total_cards === 0) {
    const lead = inventory.description
      ? `${inventory.description}.`
      : `${inventory.display_name} is ready for its first card.`;
    return `${lead} Search for a card and add it to create the first owned row.`;
  }

  return "Add a card from the search panel to create the first owned row.";
}

export function getInventoryAuditEmptyMessage(inventory: InventorySummary) {
  if (inventory.total_cards === 0) {
    return "This collection has not recorded any write activity yet. Adding the first card will start the audit trail.";
  }

  return "Once you add, edit, or remove cards, the latest events will appear here.";
}

export function formatStatusLabel(status: AsyncStatus) {
  switch (status) {
    case "idle":
      return "Waiting";
    case "loading":
      return "Loading";
    case "ready":
      return "Ready";
    case "error":
      return "Error";
  }
}

export function formatFinishLabel(value: FinishInput | string) {
  if (value === "nonfoil") {
    return "Normal";
  }
  return FINISH_OPTIONS.find((option) => option.value === value)?.label || value;
}

export function formatLanguageCode(value: string) {
  return value.toUpperCase();
}

export function formatAuditAction(value: string) {
  return value
    .split("_")
    .map((part) => formatTitleCase(part))
    .join(" ");
}

export function formatAuditActor(event: InventoryAuditEvent) {
  if (event.actor_id && event.actor_id !== event.actor_type) {
    return `${event.actor_id} via ${formatActorType(event.actor_type)}`;
  }
  return event.actor_id || formatActorType(event.actor_type);
}

export function summarizeInlineText(value: string, maxLength: number) {
  if (value.length <= maxLength) {
    return value;
  }

  return `${value.slice(0, maxLength - 1)}…`;
}

export function getPatchSuccessMessage(
  response: InventoryItemPatchResponse,
  inventoryLabel: string,
) {
  switch (response.operation) {
    case "set_quantity":
      return `Updated ${response.card_name} to quantity ${response.quantity} in ${inventoryLabel}.`;
    case "set_finish":
      return `Set ${response.card_name} to ${formatFinishLabel(response.finish)} in ${inventoryLabel}.`;
    case "set_location":
      return response.merged
        ? `Updated location for ${response.card_name} and merged matching rows in ${inventoryLabel}.`
        : `Updated location for ${response.card_name} to ${formatLocationLabel(response.location)} in ${inventoryLabel}.`;
    case "set_condition":
      return response.merged
        ? `Updated condition for ${response.card_name} and merged matching rows in ${inventoryLabel}.`
        : `Set condition for ${response.card_name} to ${response.condition_code} in ${inventoryLabel}.`;
    case "set_notes":
      return response.notes
        ? `Saved notes for ${response.card_name} in ${inventoryLabel}.`
        : `Cleared notes for ${response.card_name} in ${inventoryLabel}.`;
    case "set_tags":
      return response.tags.length
        ? `Saved ${response.tags.length} tag${response.tags.length === 1 ? "" : "s"} for ${response.card_name} in ${inventoryLabel}.`
        : `Cleared tags for ${response.card_name} in ${inventoryLabel}.`;
    case "set_acquisition":
      return response.acquisition_price
        ? `Updated acquisition details for ${response.card_name} in ${inventoryLabel}.`
        : `Cleared acquisition details for ${response.card_name} in ${inventoryLabel}.`;
  }
}

export function getBulkMutationSuccessMessage(
  operation: BulkInventoryItemOperation,
  updatedCount: number,
  inventoryLabel: string,
) {
  const rowLabel = `${updatedCount} row${updatedCount === 1 ? "" : "s"}`;

  switch (operation) {
    case "add_tags":
      return `Added tags on ${rowLabel} in ${inventoryLabel}.`;
    case "remove_tags":
      return `Removed tags from ${rowLabel} in ${inventoryLabel}.`;
    case "set_tags":
      return `Replaced tags on ${rowLabel} in ${inventoryLabel}.`;
    case "clear_tags":
      return `Cleared tags on ${rowLabel} in ${inventoryLabel}.`;
  }
}

export function formatLocationLabel(value: string | null) {
  return value?.trim() ? value : "no location";
}

export function formatTitleCase(value: string) {
  if (!value) {
    return value;
  }

  return value.charAt(0).toUpperCase() + value.slice(1);
}

export function formatActorType(value: string) {
  if (value.toLowerCase() === "api") {
    return "API";
  }
  return formatTitleCase(value);
}

export function getAvailableFinishesForOwnedRow(
  currentFinish: FinishValue,
  allowedFinishes: FinishValue[],
) {
  const nextFinishes = [currentFinish, ...allowedFinishes].filter(
    (value, index, values) => values.indexOf(value) === index,
  );
  return nextFinishes;
}
