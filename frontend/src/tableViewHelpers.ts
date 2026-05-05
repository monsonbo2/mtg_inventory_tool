import { decimalToNumber } from "./uiHelpers";
import type {
  ConditionCode,
  FinishValue,
  LanguageCode,
  OwnedInventoryRow,
} from "./types";

export type InventoryTableColumnKey =
  | "name"
  | "set"
  | "quantity"
  | "finish"
  | "condition_code"
  | "language_code"
  | "location"
  | "tags"
  | "est_value";

export type InventoryTableSortState = {
  key: InventoryTableColumnKey;
  direction: "asc" | "desc";
} | null;

export type InventoryTableFilters = {
  nameQuery: string;
  setCodes: string[];
  finishes: FinishValue[];
  conditionCodes: ConditionCode[];
  languageCodes: LanguageCode[];
  locationQuery: string;
  emptyLocationOnly: boolean;
  tags: string[];
};

export type InventoryTableFilterOptions = {
  sets: Array<{ value: string; label: string }>;
  finishes: FinishValue[];
  conditionCodes: ConditionCode[];
  languageCodes: LanguageCode[];
  tags: string[];
};

const CONDITION_ORDER: ConditionCode[] = ["M", "NM", "LP", "MP", "HP", "DMG"];
const FINISH_ORDER: FinishValue[] = ["normal", "foil", "etched"];

export function createDefaultInventoryTableFilters(): InventoryTableFilters {
  return {
    nameQuery: "",
    setCodes: [],
    finishes: [],
    conditionCodes: [],
    languageCodes: [],
    locationQuery: "",
    emptyLocationOnly: false,
    tags: [],
  };
}

export function getInventoryTableColumnLabel(column: InventoryTableColumnKey) {
  switch (column) {
    case "name":
      return "Card";
    case "set":
      return "Set";
    case "quantity":
      return "Qty";
    case "finish":
      return "Finish";
    case "condition_code":
      return "Cond.";
    case "language_code":
      return "Lang";
    case "location":
      return "Location";
    case "tags":
      return "Tags";
    case "est_value":
      return "Value";
  }
}

export function getInventoryTableSortActionLabel(
  column: InventoryTableColumnKey,
  direction: "asc" | "desc",
) {
  switch (column) {
    case "quantity":
      return direction === "asc" ? "Lowest quantity first" : "Highest quantity first";
    case "est_value":
      return direction === "asc" ? "Lowest value first" : "Highest value first";
    case "name":
      return direction === "asc" ? "Card A-Z" : "Card Z-A";
    case "set":
      return direction === "asc" ? "Set A-Z" : "Set Z-A";
    case "finish":
      return direction === "asc" ? "Finish A-Z" : "Finish Z-A";
    case "condition_code":
      return direction === "asc" ? "Best condition first" : "Most worn first";
    case "language_code":
      return direction === "asc" ? "Language A-Z" : "Language Z-A";
    case "location":
      return direction === "asc" ? "Location A-Z" : "Location Z-A";
    case "tags":
      return direction === "asc" ? "Tags A-Z" : "Tags Z-A";
  }
}

export function getInventoryTableColumnFilterCount(
  filters: InventoryTableFilters,
  column: InventoryTableColumnKey,
) {
  switch (column) {
    case "name":
      return filters.nameQuery.trim() ? 1 : 0;
    case "set":
      return filters.setCodes.length;
    case "finish":
      return filters.finishes.length;
    case "condition_code":
      return filters.conditionCodes.length;
    case "language_code":
      return filters.languageCodes.length;
    case "location":
      return (filters.locationQuery.trim() ? 1 : 0) + (filters.emptyLocationOnly ? 1 : 0);
    case "tags":
      return filters.tags.length;
    case "quantity":
    case "est_value":
      return 0;
  }
}

export function getActiveInventoryTableFilterCount(filters: InventoryTableFilters) {
  return (
    (filters.nameQuery.trim() ? 1 : 0) +
    filters.setCodes.length +
    filters.finishes.length +
    filters.conditionCodes.length +
    filters.languageCodes.length +
    (filters.locationQuery.trim() ? 1 : 0) +
    (filters.emptyLocationOnly ? 1 : 0) +
    filters.tags.length
  );
}

export function getInventoryTableFilterOptions(items: OwnedInventoryRow[]) {
  const setMap = new Map<string, string>();
  const finishSet = new Set<FinishValue>();
  const conditionSet = new Set<ConditionCode>();
  const languageSet = new Set<LanguageCode>();
  const tagSet = new Set<string>();

  for (const item of items) {
    setMap.set(item.set_code, item.set_name);
    finishSet.add(item.finish);
    for (const finish of item.allowed_finishes) {
      finishSet.add(finish);
    }
    conditionSet.add(item.condition_code);
    languageSet.add(item.language_code);
    for (const tag of item.tags) {
      tagSet.add(tag);
    }
  }

  const filterOptions: InventoryTableFilterOptions = {
    sets: Array.from(setMap.entries())
      .sort(([leftCode, leftName], [rightCode, rightName]) => {
        const nameResult = compareText(leftName, rightName);
        if (nameResult !== 0) {
          return nameResult;
        }
        return compareText(leftCode, rightCode);
      })
      .map(([code, name]) => ({
        value: code,
        label: `${code.toUpperCase()} · ${name}`,
      })),
    finishes: FINISH_ORDER.filter((finish) => finishSet.has(finish)),
    conditionCodes: CONDITION_ORDER.filter((conditionCode) => conditionSet.has(conditionCode)),
    languageCodes: Array.from(languageSet).sort(compareText),
    tags: Array.from(tagSet).sort(compareText),
  };

  return filterOptions;
}

export function applyInventoryTableQuery(
  items: OwnedInventoryRow[],
  sortState: InventoryTableSortState,
  filters: InventoryTableFilters,
) {
  const filteredItems = items.filter((item) => matchesInventoryTableFilters(item, filters));

  if (!sortState) {
    return filteredItems;
  }

  const sortedItems = [...filteredItems].sort((left, right) => {
    const directionMultiplier = sortState.direction === "asc" ? 1 : -1;
    const result = compareInventoryTableRows(left, right, sortState.key);
    if (result !== 0) {
      return result * directionMultiplier;
    }
    return left.item_id - right.item_id;
  });

  return sortedItems;
}

function matchesInventoryTableFilters(
  item: OwnedInventoryRow,
  filters: InventoryTableFilters,
) {
  const normalizedNameQuery = filters.nameQuery.trim().toLowerCase();
  if (normalizedNameQuery && !item.name.toLowerCase().includes(normalizedNameQuery)) {
    return false;
  }

  if (filters.setCodes.length > 0 && !filters.setCodes.includes(item.set_code)) {
    return false;
  }

  if (filters.finishes.length > 0 && !filters.finishes.includes(item.finish)) {
    return false;
  }

  if (
    filters.conditionCodes.length > 0 &&
    !filters.conditionCodes.includes(item.condition_code)
  ) {
    return false;
  }

  if (
    filters.languageCodes.length > 0 &&
    !filters.languageCodes.includes(item.language_code)
  ) {
    return false;
  }

  const normalizedLocation = item.location?.trim() ?? "";
  const normalizedLocationQuery = filters.locationQuery.trim().toLowerCase();
  if (filters.emptyLocationOnly && normalizedLocation) {
    return false;
  }
  if (
    normalizedLocationQuery &&
    !normalizedLocation.toLowerCase().includes(normalizedLocationQuery)
  ) {
    return false;
  }

  if (
    filters.tags.length > 0 &&
    !filters.tags.every((tag) => item.tags.includes(tag))
  ) {
    return false;
  }

  return true;
}

function compareInventoryTableRows(
  left: OwnedInventoryRow,
  right: OwnedInventoryRow,
  key: InventoryTableColumnKey,
) {
  switch (key) {
    case "name":
      return compareText(left.name, right.name);
    case "set":
      return compareText(left.set_name, right.set_name) || compareText(left.set_code, right.set_code);
    case "quantity":
      return left.quantity - right.quantity;
    case "finish":
      return compareKnownOrder(left.finish, right.finish, FINISH_ORDER);
    case "condition_code":
      return compareKnownOrder(left.condition_code, right.condition_code, CONDITION_ORDER);
    case "language_code":
      return compareText(left.language_code, right.language_code);
    case "location":
      return compareText(left.location ?? "", right.location ?? "");
    case "tags":
      return compareText(left.tags.join(", "), right.tags.join(", "));
    case "est_value":
      return decimalToNumber(left.est_value) - decimalToNumber(right.est_value);
  }
}

function compareKnownOrder<T extends string>(left: T, right: T, order: readonly T[]) {
  const leftIndex = order.indexOf(left);
  const rightIndex = order.indexOf(right);

  if (leftIndex === -1 || rightIndex === -1) {
    return compareText(left, right);
  }

  return leftIndex - rightIndex;
}

function compareText(left: string, right: string) {
  return left.localeCompare(right, undefined, {
    numeric: true,
    sensitivity: "base",
  });
}
