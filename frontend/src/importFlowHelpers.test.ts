import { describe, expect, it } from "vitest";

import {
  buildInitialInventoryImportResolutionSelectionMap,
  buildInventoryImportResolutionSelections,
  createDeckUrlImportSession,
  getInventoryImportResolutionProgress,
  getInventoryImportStep,
  replaceInventoryImportSessionPreview,
} from "./importFlowHelpers";
import type { DeckUrlImportResponse } from "./types";

function buildDeckUrlImportResponse(
  overrides: Partial<DeckUrlImportResponse> = {},
): DeckUrlImportResponse {
  return {
    source_url: "https://www.moxfield.com/decks/demo",
    provider: "moxfield",
    deck_name: null,
    default_inventory: "personal",
    rows_seen: 1,
    rows_written: 1,
    ready_to_commit: true,
    source_snapshot_token: "snapshot-1",
    summary: {
      total_card_quantity: 4,
      distinct_card_names: 1,
      distinct_printings: 1,
      section_card_quantities: {},
      requested_card_quantity: 4,
      unresolved_card_quantity: 0,
    },
    resolution_issues: [],
    dry_run: true,
    imported_rows: [],
    ...overrides,
  };
}

describe("importFlowHelpers", () => {
  it("treats any preview with ready_to_commit false as needing resolution", () => {
    expect(
      getInventoryImportStep(
        buildDeckUrlImportResponse({
          ready_to_commit: false,
          resolution_issues: [
            {
              kind: "ambiguous_card_name",
              blocking: true,
              source_position: 4,
              section: "mainboard",
              requested: {
                scryfall_id: null,
                name: "Bolt",
                quantity: 1,
                set_code: null,
                collector_number: null,
                finish: null,
              },
              options: [],
            },
          ],
        }),
      ),
    ).toBe("needs_resolution");
  });

  it("keeps commit-ready previews in the ready state even when they report unresolved leftovers", () => {
    expect(
      getInventoryImportStep(
        buildDeckUrlImportResponse({
          ready_to_commit: true,
          resolution_issues: [
            {
              kind: "unknown_card",
              blocking: false,
              source_position: 9,
              section: "mainboard",
              requested: {
                scryfall_id: null,
                name: "Unknown Card",
                quantity: 1,
                set_code: null,
                collector_number: null,
                finish: null,
              },
              options: [],
            },
          ],
        }),
      ),
    ).toBe("ready_to_commit");
  });

  it("does not require manual selections for non-blocking leftover issues", () => {
    const session = createDeckUrlImportSession({
      sourceUrl: "https://www.moxfield.com/decks/demo",
      inventorySlug: "personal",
      inventoryLabel: "Personal Collection",
      preview: buildDeckUrlImportResponse({
        ready_to_commit: false,
        resolution_issues: [
          {
            kind: "ambiguous_printing",
            blocking: true,
            source_position: 2,
            section: "mainboard",
            requested: {
              scryfall_id: null,
              name: "Counterspell",
              quantity: 1,
              set_code: "7ED",
              collector_number: "67",
              finish: null,
            },
            options: [
              {
                scryfall_id: "counterspell-7ed",
                finish: "normal",
                name: "Counterspell",
                set_code: "7ed",
                set_name: "Seventh Edition",
                collector_number: "67",
                lang: "en",
                image_uri_small: null,
                image_uri_normal: null,
                image_uri_art_crop: "https://example.test/cards/counterspell-art-crop.jpg",
              },
            ],
          },
          {
            kind: "unknown_card",
            blocking: false,
            source_position: 9,
            section: "mainboard",
            requested: {
              scryfall_id: "stale-id",
              name: "Unknown Card",
              quantity: 1,
              set_code: null,
              collector_number: null,
              finish: null,
            },
            options: [],
          },
        ],
      }),
    });

    const selections = buildInitialInventoryImportResolutionSelectionMap(session);
    const progress = getInventoryImportResolutionProgress(session, selections);
    const resolutionPayload = buildInventoryImportResolutionSelections(session, selections);

    expect(progress.blockedCount).toBe(0);
    expect(progress.requiredCount).toBe(1);
    expect(progress.issues[0].options[0].imageUriArtCrop).toBe(
      "https://example.test/cards/counterspell-art-crop.jpg",
    );
    expect(resolutionPayload).toEqual({
      mode: "deck_url",
      resolutions: [
        {
          finish: "normal",
          scryfall_id: "counterspell-7ed",
          source_position: 2,
        },
      ],
    });
  });

  it("preserves the deck URL snapshot token inside the import session", () => {
    const session = createDeckUrlImportSession({
      sourceUrl: "https://www.moxfield.com/decks/demo",
      inventorySlug: "personal",
      inventoryLabel: "Personal Collection",
      preview: buildDeckUrlImportResponse({
        source_snapshot_token: "snapshot-42",
      }),
    });

    expect(session.preview.source_snapshot_token).toBe("snapshot-42");

    const updatedSession = replaceInventoryImportSessionPreview(
      session,
      buildDeckUrlImportResponse({
        ready_to_commit: false,
        source_snapshot_token: "snapshot-42",
        resolution_issues: [
          {
            kind: "finish_required",
            blocking: true,
            source_position: 11,
            section: "mainboard",
            requested: {
              scryfall_id: null,
              name: "Counterspell",
              quantity: 1,
              set_code: null,
              collector_number: null,
              finish: null,
            },
            options: [],
          },
        ],
      }),
    );

    expect(updatedSession.mode).toBe("deck_url");
    if (updatedSession.mode !== "deck_url") {
      throw new Error("Expected a deck URL import session.");
    }
    expect(updatedSession.preview.source_snapshot_token).toBe("snapshot-42");
    expect(updatedSession.step).toBe("needs_resolution");
  });
});
