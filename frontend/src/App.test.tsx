import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiClientError } from "./api";
import type { OwnedInventoryRow } from "./types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    listInventories: vi.fn(),
    listInventoryItems: vi.fn(),
    listInventoryAudit: vi.fn(),
    searchCards: vi.fn(),
    addInventoryItem: vi.fn(),
    patchInventoryItem: vi.fn(),
    deleteInventoryItem: vi.fn(),
  };
});

import {
  listInventories,
  listInventoryItems,
  listInventoryAudit,
  searchCards,
  patchInventoryItem,
} from "./api";

describe("App", () => {
  it("surfaces backend patch errors as a notice", async () => {
    const ownedRow: OwnedInventoryRow = {
      item_id: 7,
      scryfall_id: "bolt-1",
      name: "Lightning Bolt",
      set_code: "lea",
      set_name: "Limited Edition Alpha",
      rarity: "common",
      collector_number: "161",
      image_uri_small: null,
      image_uri_normal: null,
      quantity: 2,
      condition_code: "NM",
      finish: "normal",
      allowed_finishes: ["normal"],
      language_code: "en",
      location: "Binder",
      tags: ["burn"],
      acquisition_price: "1.00",
      acquisition_currency: "USD",
      currency: "USD",
      unit_price: "2.00",
      est_value: "4.00",
      price_date: "2026-04-01",
      notes: "Main deck",
    };

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 1,
        total_cards: 2,
      },
    ]);
    vi.mocked(listInventoryItems).mockResolvedValue([ownedRow]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCards).mockResolvedValue([
      {
        scryfall_id: "bolt-1",
        name: "Lightning Bolt",
        set_code: "lea",
        set_name: "Limited Edition Alpha",
        collector_number: "161",
        lang: "en",
        rarity: "common",
        finishes: ["normal", "foil"],
        tcgplayer_product_id: "123",
        image_uri_small: null,
        image_uri_normal: null,
      },
    ]);
    vi.mocked(patchInventoryItem).mockRejectedValue(
      new ApiClientError(
        "Finish 'foil' is not available for this card printing. Available finishes: normal.",
        {
          code: "validation_error",
          status: 400,
        },
      ),
    );

    render(<App />);

    const heading = await screen.findByRole("heading", { name: "Lightning Bolt" });
    const card = heading.closest("article");
    expect(card).not.toBeNull();
    const row = within(card!);

    await waitFor(() => {
      expect(row.getByRole("combobox")).toBeEnabled();
    });

    await userEvent.selectOptions(row.getByRole("combobox"), "foil");
    await userEvent.click(row.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Finish 'foil' is not available for this card printing. Available finishes: normal.",
    );
  });
});
