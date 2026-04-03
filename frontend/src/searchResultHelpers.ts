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
