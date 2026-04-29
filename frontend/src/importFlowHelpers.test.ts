import { describe, expect, it } from "vitest";

import {
  createDeckUrlImportSession,
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
