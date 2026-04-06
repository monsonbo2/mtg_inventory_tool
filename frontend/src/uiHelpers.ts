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

const TAG_COLOR_PALETTE = [
  {
    background: "rgba(248, 113, 113, 0.18)",
    borderColor: "rgba(248, 113, 113, 0.34)",
    color: "#fecaca",
  },
  {
    background: "rgba(249, 115, 22, 0.18)",
    borderColor: "rgba(249, 115, 22, 0.34)",
    color: "#fed7aa",
  },
  {
    background: "rgba(250, 204, 21, 0.18)",
    borderColor: "rgba(250, 204, 21, 0.34)",
    color: "#fde68a",
  },
  {
    background: "rgba(163, 230, 53, 0.18)",
    borderColor: "rgba(163, 230, 53, 0.34)",
    color: "#d9f99d",
  },
  {
    background: "rgba(74, 222, 128, 0.18)",
    borderColor: "rgba(74, 222, 128, 0.34)",
    color: "#bbf7d0",
  },
  {
    background: "rgba(45, 212, 191, 0.18)",
    borderColor: "rgba(45, 212, 191, 0.34)",
    color: "#99f6e4",
  },
  {
    background: "rgba(56, 189, 248, 0.18)",
    borderColor: "rgba(56, 189, 248, 0.34)",
    color: "#bae6fd",
  },
  {
    background: "rgba(96, 165, 250, 0.18)",
    borderColor: "rgba(96, 165, 250, 0.34)",
    color: "#bfdbfe",
  },
  {
    background: "rgba(129, 140, 248, 0.18)",
    borderColor: "rgba(129, 140, 248, 0.34)",
    color: "#d1d7ff",
  },
  {
    background: "rgba(192, 132, 252, 0.18)",
    borderColor: "rgba(192, 132, 252, 0.34)",
    color: "#e9d5ff",
  },
  {
    background: "rgba(244, 114, 182, 0.18)",
    borderColor: "rgba(244, 114, 182, 0.34)",
    color: "#fbcfe8",
  },
  {
    background: "rgba(251, 146, 60, 0.16)",
    borderColor: "rgba(251, 146, 60, 0.3)",
    color: "#fdba74",
  },
];

export function parseTags(value: string) {
  return value
    .split(",")
    .map((part) => part.trim().toLowerCase())
    .filter(Boolean)
    .filter((tag, index, tags) => tags.indexOf(tag) === index);
}

export function getTagChipStyle(tag: string) {
  let hash = 0;
  for (const character of tag) {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  }

  return TAG_COLOR_PALETTE[hash % TAG_COLOR_PALETTE.length];
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
      return "Removing entry...";
  }
}

export function normalizeOptionalText(value: string | null | undefined) {
  const text = value?.trim();
  return text ? text : null;
}

export function getInventoryLocationSuggestions(items: OwnedInventoryRow[]) {
  const locations = new Map<
    string,
    {
      count: number;
      label: string;
    }
  >();

  for (const item of items) {
    const location = item.location?.trim();
    if (!location) {
      continue;
    }

    const key = location.toLowerCase();
    const current = locations.get(key);
    if (current) {
      current.count += 1;
      continue;
    }

    locations.set(key, {
      count: 1,
      label: location,
    });
  }

  return Array.from(locations.values())
    .sort(
      (left, right) =>
        right.count - left.count || left.label.localeCompare(right.label, "en", { sensitivity: "base" }),
    )
    .map((entry) => entry.label);
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
    return `${lead} Search for a card and add it to start building this collection.`;
  }

  return "Add a card from search to keep building this collection.";
}

export function getInventoryAuditEmptyMessage(inventory: InventorySummary) {
  if (inventory.total_cards === 0) {
    return "This collection does not have any recent changes yet. Adding the first card will start the activity feed.";
  }

  return "Once you add, edit, or remove cards, the latest changes will appear here.";
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
        ? `Updated location for ${response.card_name} and combined matching entries in ${inventoryLabel}.`
        : `Updated location for ${response.card_name} to ${formatLocationLabel(response.location)} in ${inventoryLabel}.`;
    case "set_condition":
      return response.merged
        ? `Updated condition for ${response.card_name} and combined matching entries in ${inventoryLabel}.`
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
  const entryLabel = `${updatedCount} entr${updatedCount === 1 ? "y" : "ies"}`;

  switch (operation) {
    case "add_tags":
      return `Added tags to ${entryLabel} in ${inventoryLabel}.`;
    case "remove_tags":
      return `Removed tags from ${entryLabel} in ${inventoryLabel}.`;
    case "set_tags":
      return `Replaced tags on ${entryLabel} in ${inventoryLabel}.`;
    case "clear_tags":
      return `Cleared tags from ${entryLabel} in ${inventoryLabel}.`;
    case "set_quantity":
      return `Updated quantity on ${entryLabel} in ${inventoryLabel}.`;
    case "set_notes":
      return `Updated notes on ${entryLabel} in ${inventoryLabel}.`;
    case "set_acquisition":
      return `Updated acquisition details on ${entryLabel} in ${inventoryLabel}.`;
    case "set_finish":
      return `Updated finish on ${entryLabel} in ${inventoryLabel}.`;
    case "set_location":
      return `Updated location on ${entryLabel} in ${inventoryLabel}.`;
    case "set_condition":
      return `Updated condition on ${entryLabel} in ${inventoryLabel}.`;
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
