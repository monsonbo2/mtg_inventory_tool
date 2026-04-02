import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiClientError } from "./api";
import type { CatalogSearchRow, OwnedInventoryRow } from "./types";

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

afterEach(() => {
  vi.clearAllMocks();
});

describe("App", () => {
  function mockBaseSearchApp() {
    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 0,
        total_cards: 0,
      },
    ]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
  }

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

  it("supports keyboard selection from autocomplete suggestions", async () => {
    const user = userEvent.setup();
    const forest: CatalogSearchRow = {
      scryfall_id: "forest-1",
      name: "Forest",
      set_code: "m10",
      set_name: "Magic 2010",
      collector_number: "246",
      lang: "en",
      rarity: "common",
      finishes: ["normal"],
      tcgplayer_product_id: "1003",
      image_uri_small: null,
      image_uri_normal: null,
    };
    const forceOfWill: CatalogSearchRow = {
      scryfall_id: "force-1",
      name: "Force of Will",
      set_code: "all",
      set_name: "Alliances",
      collector_number: "28",
      lang: "en",
      rarity: "rare",
      finishes: ["normal"],
      tcgplayer_product_id: "2001",
      image_uri_small: null,
      image_uri_normal: null,
    };

    mockBaseSearchApp();
    vi.mocked(searchCards).mockImplementation(async (params) => {
      if (params.query === "Fo") {
        return [forest, forceOfWill];
      }
      if (params.query === "Force of Will") {
        return [forceOfWill];
      }
      return [];
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Search query" });
    await user.clear(input);
    await user.type(input, "Fo");

    expect(
      await screen.findByRole("listbox", { name: "Card suggestions" }, { timeout: 2000 }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("option", { name: /Forest/i }, { timeout: 2000 }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("option", { name: /Force of Will/i }, { timeout: 2000 }),
    ).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-activedescendant", expect.stringContaining("-option-0"));

    await user.keyboard("{ArrowDown}");
    expect(input).toHaveAttribute("aria-activedescendant", expect.stringContaining("-option-1"));

    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(searchCards).toHaveBeenCalledWith(
        expect.objectContaining({ query: "Force of Will", limit: 8 }),
      );
    });
    expect(input).toHaveValue("Force of Will");
    expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Force of Will" })).toBeInTheDocument();
  });

  it("closes autocomplete on escape and outside click", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCards).mockImplementation(async (params) => {
      if (params.query === "Fo") {
        return [
          {
            scryfall_id: "forest-1",
            name: "Forest",
            set_code: "m10",
            set_name: "Magic 2010",
            collector_number: "246",
            lang: "en",
            rarity: "common",
            finishes: ["normal"],
            tcgplayer_product_id: "1003",
            image_uri_small: null,
            image_uri_normal: null,
          },
        ];
      }
      return [];
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Search query" });
    await user.clear(input);
    await user.type(input, "Fo");

    expect(
      await screen.findByRole("listbox", { name: "Card suggestions" }, { timeout: 2000 }),
    ).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();
    expect(input).toHaveAttribute("aria-expanded", "false");

    await user.click(input);
    expect(await screen.findByRole("listbox", { name: "Card suggestions" })).toBeInTheDocument();

    await user.click(document.body);
    await waitFor(() => {
      expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();
    });
    expect(input).toHaveAttribute("aria-expanded", "false");
  });
});
