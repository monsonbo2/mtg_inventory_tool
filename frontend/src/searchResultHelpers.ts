import type { CatalogSearchRow } from "./types";

export type SearchCardGroup = {
  groupId: string;
  name: string;
  rarity: string | null;
  image_uri_small: string | null;
  image_uri_normal: string | null;
  previewPrintings: CatalogSearchRow[];
};

export function getSearchCardGroupId(name: string) {
  return name.trim().replace(/\s+/g, " ").toLowerCase();
}

export function groupCatalogSearchRows(rows: CatalogSearchRow[]) {
  const groups: SearchCardGroup[] = [];
  const groupsById = new Map<string, SearchCardGroup>();

  for (const row of rows) {
    const groupId = getSearchCardGroupId(row.name);
    const existingGroup = groupsById.get(groupId);

    if (!existingGroup) {
      const nextGroup: SearchCardGroup = {
        groupId,
        name: row.name,
        rarity: row.rarity,
        image_uri_small: row.image_uri_small,
        image_uri_normal: row.image_uri_normal,
        previewPrintings: [row],
      };
      groups.push(nextGroup);
      groupsById.set(groupId, nextGroup);
      continue;
    }

    if (!existingGroup.image_uri_small && row.image_uri_small) {
      existingGroup.image_uri_small = row.image_uri_small;
    }
    if (!existingGroup.image_uri_normal && row.image_uri_normal) {
      existingGroup.image_uri_normal = row.image_uri_normal;
    }
    if (!existingGroup.rarity && row.rarity) {
      existingGroup.rarity = row.rarity;
    }
    if (!existingGroup.previewPrintings.some((printing) => printing.scryfall_id === row.scryfall_id)) {
      existingGroup.previewPrintings.push(row);
    }
  }

  return groups;
}

export function formatPrintingOptionLabel(printing: CatalogSearchRow) {
  return `${printing.set_code.toUpperCase()} · ${printing.set_name} · #${printing.collector_number} · ${printing.lang.toUpperCase()}`;
}

export function summarizePreviewPrintings(group: SearchCardGroup) {
  const previewSetCodes = Array.from(
    new Set(group.previewPrintings.map((printing) => printing.set_code.toUpperCase())),
  );

  if (previewSetCodes.length === 0) {
    return "Open the printing picker to choose an exact version.";
  }

  if (previewSetCodes.length <= 3) {
    return `Preview printings: ${previewSetCodes.join(", ")}.`;
  }

  return `Preview printings: ${previewSetCodes.slice(0, 3).join(", ")} +${previewSetCodes.length - 3} more.`;
}
