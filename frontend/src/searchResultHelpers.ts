import type { CatalogNameSearchRow, CatalogSearchRow } from "./types";
import { formatLanguageCode } from "./uiHelpers";

export type SearchCardGroup = {
  groupId: string;
  oracleId: string;
  name: string;
  image_uri_small: string | null;
  image_uri_normal: string | null;
  printingsCount: number;
  availableLanguages: string[];
};

function normalizeSearchText(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function getNameSearchPriority(name: string, query: string) {
  const normalizedName = normalizeSearchText(name);
  const normalizedQuery = normalizeSearchText(query);

  if (!normalizedQuery) {
    return 4;
  }
  if (normalizedName === normalizedQuery) {
    return 0;
  }
  if (normalizedName.startsWith(normalizedQuery)) {
    return 1;
  }
  const firstMatchIndex = normalizedName.indexOf(normalizedQuery);
  if (firstMatchIndex >= 0) {
    return normalizedName[firstMatchIndex - 1] === " " ? 2 : 3;
  }
  return 4;
}

export function sortNameSearchRows(rows: CatalogNameSearchRow[], query: string) {
  const normalizedQuery = normalizeSearchText(query);
  if (!normalizedQuery) {
    return [...rows];
  }

  return [...rows].sort((left, right) => {
    const priorityDifference =
      getNameSearchPriority(left.name, normalizedQuery) -
      getNameSearchPriority(right.name, normalizedQuery);
    if (priorityDifference !== 0) {
      return priorityDifference;
    }

    const leftIndex = normalizeSearchText(left.name).indexOf(normalizedQuery);
    const rightIndex = normalizeSearchText(right.name).indexOf(normalizedQuery);
    if (leftIndex !== rightIndex) {
      return leftIndex - rightIndex;
    }

    const nameComparison = left.name.localeCompare(right.name, undefined, {
      sensitivity: "base",
    });
    if (nameComparison !== 0) {
      return nameComparison;
    }

    return left.oracle_id.localeCompare(right.oracle_id, undefined, {
      sensitivity: "base",
    });
  });
}

export function createSearchCardGroups(rows: CatalogNameSearchRow[]) {
  return rows.map((row) => ({
    groupId: row.oracle_id,
    oracleId: row.oracle_id,
    name: row.name,
    image_uri_small: row.image_uri_small,
    image_uri_normal: row.image_uri_normal,
    printingsCount: row.printings_count,
    availableLanguages: row.available_languages,
  }));
}

export function formatPrintingOptionLabel(printing: CatalogSearchRow) {
  return `${printing.set_code.toUpperCase()} · ${printing.set_name} · #${printing.collector_number} · ${printing.lang.toUpperCase()}`;
}

export function summarizeSearchGroup(group: SearchCardGroup) {
  const formattedLanguages = group.availableLanguages.map((languageCode) =>
    formatLanguageCode(languageCode),
  );

  if (!formattedLanguages.length) {
    return `${group.printingsCount} printing${group.printingsCount === 1 ? "" : "s"} available.`;
  }

  if (formattedLanguages.length === 1) {
    return `${group.printingsCount} printing${group.printingsCount === 1 ? "" : "s"} available in ${formattedLanguages[0]}.`;
  }

  if (formattedLanguages.length <= 4) {
    return `${group.printingsCount} printings available across ${formattedLanguages.join(", ")}.`;
  }

  return `${group.printingsCount} printings across ${formattedLanguages.slice(0, 4).join(", ")} +${formattedLanguages.length - 4} more languages.`;
}
