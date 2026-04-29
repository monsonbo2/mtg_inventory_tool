import type {
  CsvImportResponse,
  CsvImportResolutionIssueResponse,
  DeckUrlImportResponse,
  DeckUrlImportResolutionIssueResponse,
  DecklistImportResponse,
  DecklistImportResolutionIssueResponse,
  FinishValue,
  ImportResolutionIssueKind,
  ImportResolutionOptionResponse,
} from "./types";
import type {
  CsvImportSession,
  DeckUrlImportSession,
  DecklistImportSession,
  InventoryImportSession,
  InventoryImportResolutionSelections,
  InventoryImportStep,
} from "./uiTypes";

export type InventoryImportResponse =
  | CsvImportResponse
  | DeckUrlImportResponse
  | DecklistImportResponse;

export function getInventoryImportStep(
  response: InventoryImportResponse,
): InventoryImportStep {
  return response.ready_to_commit ? "ready_to_commit" : "needs_resolution";
}

export type InventoryImportResolutionSelectionMap = Record<string, string>;

export type InventoryImportResolutionOptionView = {
  key: string;
  scryfallId: string;
  finish: FinishValue;
  name: string;
  setCode: string;
  setName: string;
  collectorNumber: string;
  languageCode: string;
  imageUriSmall: string | null;
  imageUriNormal: string | null;
  detail: string;
};

export type InventoryImportResolutionIssueView = {
  key: string;
  kind: ImportResolutionIssueKind;
  heading: string;
  prompt: string;
  sourceLabel: string;
  requestedDetail: string;
  blockedMessage: string | null;
  options: InventoryImportResolutionOptionView[];
};

function formatFinishLabel(finish: FinishValue | null | undefined) {
  switch (finish) {
    case "foil":
      return "Foil";
    case "etched":
      return "Etched";
    case "normal":
      return "Normal";
    default:
      return null;
  }
}

function formatIssuePrompt(kind: ImportResolutionIssueKind, hasOptions: boolean) {
  switch (kind) {
    case "ambiguous_card_name":
      return hasOptions
        ? "Choose the correct card name before continuing."
        : "No selectable card matches were returned for this entry yet.";
    case "ambiguous_printing":
      return hasOptions
        ? "Choose the exact printing to import."
        : "No selectable printings were returned for this entry yet.";
    case "finish_required":
      return hasOptions
        ? "Choose the finish to import."
        : "No selectable finishes were returned for this entry yet.";
    case "unknown_card":
      return hasOptions
        ? "Choose the best matching card before continuing."
        : "This card could not be matched yet. Update the source list or wait for backend support.";
  }
}

function formatOptionDetail(option: ImportResolutionOptionResponse) {
  const parts = [`${option.set_code.toUpperCase()} ${option.collector_number}`];
  const finishLabel = formatFinishLabel(option.finish);
  if (finishLabel) {
    parts.push(finishLabel);
  }
  parts.push(option.lang.toUpperCase());
  return parts.join(" · ");
}

function formatRequestedDetail(options: {
  quantity: number;
  setCode: string | null;
  collectorNumber: string | null;
  finish?: FinishValue | null;
  languageCode?: string | null;
}) {
  const parts = [`Qty ${options.quantity}`];
  if (options.setCode && options.collectorNumber) {
    parts.push(`${options.setCode.toUpperCase()} ${options.collectorNumber}`);
  } else if (options.setCode) {
    parts.push(options.setCode.toUpperCase());
  }
  const finishLabel = formatFinishLabel(options.finish);
  if (finishLabel) {
    parts.push(finishLabel);
  }
  if (options.languageCode) {
    parts.push(options.languageCode.toUpperCase());
  }
  return parts.join(" · ");
}

function getOptionKey(option: ImportResolutionOptionResponse) {
  return `${option.scryfall_id}:${option.finish}`;
}

function getCsvIssueKey(issue: CsvImportResolutionIssueResponse) {
  return `csv:${issue.csv_row}:${issue.kind}`;
}

function getDecklistIssueKey(issue: DecklistImportResolutionIssueResponse) {
  return `decklist:${issue.decklist_line}:${issue.section}:${issue.kind}`;
}

function getDeckUrlIssueKey(issue: DeckUrlImportResolutionIssueResponse) {
  return `deck-url:${issue.source_position}:${issue.section}:${issue.kind}`;
}

function normalizeIssueOptions(
  options: ImportResolutionOptionResponse[],
): InventoryImportResolutionOptionView[] {
  return options.map((option) => ({
    key: getOptionKey(option),
    scryfallId: option.scryfall_id,
    finish: option.finish,
    name: option.name,
    setCode: option.set_code,
    setName: option.set_name,
    collectorNumber: option.collector_number,
    languageCode: option.lang,
    imageUriNormal: option.image_uri_normal,
    imageUriSmall: option.image_uri_small,
    detail: formatOptionDetail(option),
  }));
}

export function getInventoryImportResolutionIssues(
  session: InventoryImportSession,
): InventoryImportResolutionIssueView[] {
  switch (session.mode) {
    case "csv":
      return session.preview.resolution_issues.map((issue) => {
        const options = normalizeIssueOptions(issue.options);
        return {
          key: getCsvIssueKey(issue),
          kind: issue.kind,
          heading: issue.requested.name || "Unknown card",
          prompt: formatIssuePrompt(issue.kind, options.length > 0),
          sourceLabel: `Row ${issue.csv_row}`,
          requestedDetail: formatRequestedDetail({
            collectorNumber: issue.requested.collector_number,
            finish: issue.requested.finish,
            languageCode: issue.requested.lang,
            quantity: issue.requested.quantity,
            setCode: issue.requested.set_code,
          }),
          blockedMessage:
            options.length === 0
              ? "No selectable resolution options were returned for this row."
              : null,
          options,
        };
      });
    case "decklist":
      return session.preview.resolution_issues.map((issue) => {
        const options = normalizeIssueOptions(issue.options);
        return {
          key: getDecklistIssueKey(issue),
          kind: issue.kind,
          heading: issue.requested.name || "Unknown card",
          prompt: formatIssuePrompt(issue.kind, options.length > 0),
          sourceLabel: `${issue.section} · Line ${issue.decklist_line}`,
          requestedDetail: formatRequestedDetail({
            collectorNumber: issue.requested.collector_number,
            finish: issue.requested.finish,
            quantity: issue.requested.quantity,
            setCode: issue.requested.set_code,
          }),
          blockedMessage:
            options.length === 0
              ? "No selectable resolution options were returned for this line."
              : null,
          options,
        };
      });
    case "deck_url":
      return session.preview.resolution_issues.map((issue) => {
        const options = normalizeIssueOptions(issue.options);
        return {
          key: getDeckUrlIssueKey(issue),
          kind: issue.kind,
          heading: issue.requested.name || "Unknown card",
          prompt: formatIssuePrompt(issue.kind, options.length > 0),
          sourceLabel: `${issue.section} · Position ${issue.source_position}`,
          requestedDetail: formatRequestedDetail({
            collectorNumber: issue.requested.collector_number,
            finish: issue.requested.finish,
            quantity: issue.requested.quantity,
            setCode: issue.requested.set_code,
          }),
          blockedMessage:
            options.length === 0
              ? "No selectable resolution options were returned for this source entry."
              : null,
          options,
        };
      });
  }
}

export function buildInitialInventoryImportResolutionSelectionMap(
  session: InventoryImportSession,
): InventoryImportResolutionSelectionMap {
  return Object.fromEntries(
    getInventoryImportResolutionIssues(session)
      .filter((issue) => issue.options.length === 1)
      .map((issue) => [issue.key, issue.options[0].key]),
  );
}

export function reconcileInventoryImportResolutionSelectionMap(
  session: InventoryImportSession,
  currentSelections: InventoryImportResolutionSelectionMap,
): InventoryImportResolutionSelectionMap {
  const nextEntries = getInventoryImportResolutionIssues(session).map((issue) => {
    const currentSelection = currentSelections[issue.key];
    if (currentSelection && issue.options.some((option) => option.key === currentSelection)) {
      return [issue.key, currentSelection] as const;
    }
    if (issue.options.length === 1) {
      return [issue.key, issue.options[0].key] as const;
    }
    return [issue.key, ""] as const;
  });

  return Object.fromEntries(
    nextEntries.filter(([, value]) => value),
  );
}

export function getInventoryImportResolutionProgress(
  session: InventoryImportSession,
  selections: InventoryImportResolutionSelectionMap,
) {
  const issues = getInventoryImportResolutionIssues(session);
  const blockedCount = issues.filter((issue) => issue.options.length === 0).length;
  const requiredCount = issues.filter((issue) => issue.options.length > 0).length;
  const selectedCount = issues.filter(
    (issue) =>
      issue.options.length > 0 &&
      issue.options.some((option) => option.key === selections[issue.key]),
  ).length;
  return {
    blockedCount,
    issues,
    requiredCount,
    selectedCount,
  };
}

function findSelectedOption(
  issueOptions: ImportResolutionOptionResponse[],
  selectedKey: string | undefined,
) {
  if (!selectedKey) {
    return null;
  }
  return issueOptions.find((option) => getOptionKey(option) === selectedKey) ?? null;
}

export function buildInventoryImportResolutionSelections(
  session: InventoryImportSession,
  selections: InventoryImportResolutionSelectionMap,
): InventoryImportResolutionSelections | null {
  switch (session.mode) {
    case "csv": {
      const nextResolutions = session.preview.resolution_issues.map((issue) => {
        const selectedOption = findSelectedOption(
          issue.options,
          selections[getCsvIssueKey(issue)],
        );
        if (!selectedOption) {
          return null;
        }
        return {
          csv_row: issue.csv_row,
          finish: selectedOption.finish,
          scryfall_id: selectedOption.scryfall_id,
        };
      });
      if (nextResolutions.some((resolution) => resolution === null)) {
        return null;
      }
      return {
        mode: "csv",
        resolutions: nextResolutions.filter(
          (resolution): resolution is Exclude<typeof resolution, null> => resolution !== null,
        ),
      };
    }
    case "decklist": {
      const nextResolutions = session.preview.resolution_issues.map((issue) => {
        const selectedOption = findSelectedOption(
          issue.options,
          selections[getDecklistIssueKey(issue)],
        );
        if (!selectedOption) {
          return null;
        }
        return {
          decklist_line: issue.decklist_line,
          finish: selectedOption.finish,
          scryfall_id: selectedOption.scryfall_id,
        };
      });
      if (nextResolutions.some((resolution) => resolution === null)) {
        return null;
      }
      return {
        mode: "decklist",
        resolutions: nextResolutions.filter(
          (resolution): resolution is Exclude<typeof resolution, null> => resolution !== null,
        ),
      };
    }
    case "deck_url": {
      const nextResolutions = session.preview.resolution_issues.map((issue) => {
        const selectedOption = findSelectedOption(
          issue.options,
          selections[getDeckUrlIssueKey(issue)],
        );
        if (!selectedOption) {
          return null;
        }
        return {
          finish: selectedOption.finish,
          scryfall_id: selectedOption.scryfall_id,
          source_position: issue.source_position,
        };
      });
      if (nextResolutions.some((resolution) => resolution === null)) {
        return null;
      }
      return {
        mode: "deck_url",
        resolutions: nextResolutions.filter(
          (resolution): resolution is Exclude<typeof resolution, null> => resolution !== null,
        ),
      };
    }
  }
}

export function createCsvImportSession(options: {
  file: Blob;
  inventorySlug: string;
  inventoryLabel?: string | null;
  preview: CsvImportResponse;
}): CsvImportSession {
  return {
    inventoryLabel: options.inventoryLabel ?? null,
    inventorySlug: options.inventorySlug,
    mode: "csv",
    preview: options.preview,
    source: {
      file: options.file,
    },
    step: getInventoryImportStep(options.preview),
  };
}

export function createDecklistImportSession(options: {
  deckText: string;
  inventorySlug: string;
  inventoryLabel?: string | null;
  preview: DecklistImportResponse;
}): DecklistImportSession {
  return {
    inventoryLabel: options.inventoryLabel ?? null,
    inventorySlug: options.inventorySlug,
    mode: "decklist",
    preview: options.preview,
    source: {
      deckText: options.deckText,
    },
    step: getInventoryImportStep(options.preview),
  };
}

export function createDeckUrlImportSession(options: {
  sourceUrl: string;
  inventorySlug: string;
  inventoryLabel?: string | null;
  preview: DeckUrlImportResponse;
}): DeckUrlImportSession {
  return {
    inventoryLabel: options.inventoryLabel ?? null,
    inventorySlug: options.inventorySlug,
    mode: "deck_url",
    preview: options.preview,
    source: {
      sourceUrl: options.sourceUrl,
    },
    step: getInventoryImportStep(options.preview),
  };
}

export function replaceInventoryImportSessionPreview(
  session: InventoryImportSession,
  preview: InventoryImportResponse,
): InventoryImportSession {
  switch (session.mode) {
    case "csv":
      return {
        ...session,
        preview: preview as CsvImportResponse,
        step: getInventoryImportStep(preview),
      };
    case "decklist":
      return {
        ...session,
        preview: preview as DecklistImportResponse,
        step: getInventoryImportStep(preview),
      };
    case "deck_url":
      return {
        ...session,
        preview: preview as DeckUrlImportResponse,
        step: getInventoryImportStep(preview),
      };
  }
}
