import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiClientError } from "./api";
import type { CatalogSearchRow, InventoryAuditEvent, OwnedInventoryRow } from "./types";

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
  function buildOwnedRow(overrides: Partial<OwnedInventoryRow> = {}): OwnedInventoryRow {
    return {
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
      allowed_finishes: ["normal", "foil"],
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
      ...overrides,
    };
  }

  function mockCollectionViewApp(options?: {
    items?: OwnedInventoryRow[];
    auditEvents?: InventoryAuditEvent[];
  }) {
    const items = options?.items ?? [buildOwnedRow()];
    const auditEvents = options?.auditEvents ?? [];

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: items.length,
        total_cards: items.reduce((sum, item) => sum + item.quantity, 0),
      },
    ]);
    vi.mocked(listInventoryItems).mockResolvedValue(items);
    vi.mocked(listInventoryAudit).mockResolvedValue(auditEvents);
    vi.mocked(searchCards).mockResolvedValue([]);
  }

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
      allowed_finishes: ["normal", "foil"],
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
    await userEvent.click(row.getByRole("button", { name: "Edit Lightning Bolt" }));

    await waitFor(() => {
      expect(row.getByRole("combobox")).toBeEnabled();
    });

    await userEvent.selectOptions(row.getByRole("combobox"), "foil");
    await userEvent.click(row.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Finish 'foil' is not available for this card printing. Available finishes: normal.",
    );
  });

  it("uses allowed finishes from owned rows without exact catalog follow-up lookups", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [
        buildOwnedRow({
          allowed_finishes: ["normal", "foil"],
        }),
      ],
    });

    render(<App />);

    const row = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest("article");
    expect(row).not.toBeNull();

    await user.click(within(row!).getByRole("button", { name: "Edit Lightning Bolt" }));

    await waitFor(() => {
      expect(vi.mocked(searchCards).mock.calls.some(([params]) => params.query === "Lightning Bolt")).toBe(true);
    });

    expect(within(row!).getByRole("combobox")).toBeEnabled();
    expect(within(row!).getByText("Available: Normal, Foil.")).toBeInTheDocument();
    expect(vi.mocked(searchCards).mock.calls.some(([params]) => params.exact === true)).toBe(false);
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

  it("defaults to compact collection view and toggles detailed mode without refetching", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [
        buildOwnedRow(),
        buildOwnedRow({
          item_id: 8,
          scryfall_id: "counterspell-1",
          name: "Counterspell",
          set_code: "7ed",
          set_name: "Seventh Edition",
          collector_number: "67",
          quantity: 1,
          location: "Trade Binder",
          tags: ["control"],
          est_value: "3.00",
          unit_price: "3.00",
          notes: null,
        }),
      ],
    });

    render(<App />);

    expect(await screen.findByRole("button", { name: "Edit Lightning Bolt" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Compact" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "false");
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Detailed" }));

    expect(screen.queryByRole("button", { name: "Edit Lightning Bolt" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Inline edits")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Compact" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "true");
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Compact" }));

    expect(await screen.findByRole("button", { name: "Edit Lightning Bolt" })).toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);
  });

  it("keeps one compact row open at a time and clears unsaved drafts when switching rows", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [
        buildOwnedRow(),
        buildOwnedRow({
          item_id: 8,
          scryfall_id: "counterspell-1",
          name: "Counterspell",
          set_code: "7ed",
          set_name: "Seventh Edition",
          collector_number: "67",
          quantity: 1,
          location: "Trade Binder",
          tags: ["control"],
          est_value: "3.00",
          unit_price: "3.00",
          notes: null,
        }),
      ],
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Edit Lightning Bolt" }));

    let boltRow = screen.getByRole("heading", { name: "Lightning Bolt" }).closest("article");
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    const boltQuantityInput = boltRowScope.getByRole("spinbutton", { name: /Quantity/ });

    await user.clear(boltQuantityInput);
    await user.type(boltQuantityInput, "5");
    expect(boltRowScope.getByRole("spinbutton", { name: /Quantity/ })).toHaveValue(5);

    const counterspellRow = screen.getByRole("heading", { name: "Counterspell" }).closest("article");
    expect(counterspellRow).not.toBeNull();
    await user.click(within(counterspellRow!).getByRole("button", { name: "Edit Counterspell" }));

    boltRow = screen.getByRole("heading", { name: "Lightning Bolt" }).closest("article");
    expect(boltRow).not.toBeNull();
    expect(within(boltRow!).queryByRole("spinbutton", { name: /Quantity/ })).not.toBeInTheDocument();

    await user.click(within(boltRow!).getByRole("button", { name: "Edit Lightning Bolt" }));

    boltRow = screen.getByRole("heading", { name: "Lightning Bolt" }).closest("article");
    expect(boltRow).not.toBeNull();
    expect(within(boltRow!).getByRole("spinbutton", { name: /Quantity/ })).toHaveValue(2);
    expect(
      within(screen.getByRole("heading", { name: "Counterspell" }).closest("article")!).queryByRole(
        "spinbutton",
        { name: /Quantity/ },
      ),
    ).not.toBeInTheDocument();
  });

  it("opens and closes the activity drawer while keeping audit off the main page by default", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      auditEvents: [
        {
          id: 1,
          inventory: "personal",
          item_id: 42,
          action: "set_finish",
          actor_type: "api",
          actor_id: "local-demo",
          request_id: "req-1",
          occurred_at: "2026-04-02T01:07:30Z",
          before: null,
          after: null,
          metadata: {},
        },
      ],
    });

    render(<App />);

    await screen.findByRole("button", { name: "View Activity" });
    expect(screen.queryByRole("heading", { name: "Audit Feed" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Inventory Activity" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "View Activity" }));
    expect(await screen.findByRole("dialog", { name: "Inventory Activity" })).toBeInTheDocument();
    expect(screen.getByText("Set Finish")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close activity drawer" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Inventory Activity" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "View Activity" }));
    expect(await screen.findByRole("dialog", { name: "Inventory Activity" })).toBeInTheDocument();

    await user.click(screen.getByTestId("activity-drawer-backdrop"));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Inventory Activity" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "View Activity" }));
    expect(await screen.findByRole("dialog", { name: "Inventory Activity" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Inventory Activity" })).not.toBeInTheDocument();
    });
  });

  it("supports table view row selection without refetching and preserves selection across view changes", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [
        buildOwnedRow(),
        buildOwnedRow({
          item_id: 8,
          scryfall_id: "counterspell-1",
          name: "Counterspell",
          set_code: "7ed",
          set_name: "Seventh Edition",
          collector_number: "67",
          quantity: 1,
          location: "Trade Binder",
          tags: ["control"],
          est_value: "3.00",
          unit_price: "3.00",
          notes: null,
        }),
      ],
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));

    expect(await screen.findByRole("checkbox", { name: "Select Lightning Bolt" })).toBeInTheDocument();
    expect(screen.getByText("No rows selected")).toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("checkbox", { name: "Select Lightning Bolt" }));
    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Detailed" }));
    expect(screen.queryByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Table" }));
    expect(await screen.findByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    expect(screen.getByText("2 rows selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByText("No rows selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).not.toBeChecked();
  });

  it("clears table selection when the selected inventory changes", async () => {
    const user = userEvent.setup();

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 2,
        total_cards: 3,
      },
      {
        slug: "trade-binder",
        display_name: "Trade Binder",
        description: "Cards available to trade",
        item_rows: 1,
        total_cards: 1,
      },
    ]);
    vi.mocked(listInventoryItems).mockImplementation(async (inventorySlug) => {
      if (inventorySlug === "trade-binder") {
        return [
          buildOwnedRow({
            item_id: 101,
            scryfall_id: "sol-ring-1",
            name: "Sol Ring",
            set_code: "cmm",
            set_name: "Commander Masters",
            collector_number: "396",
            quantity: 1,
            location: "Trade Tray",
            tags: ["trade"],
            est_value: "1.50",
            unit_price: "1.50",
            notes: null,
          }),
        ];
      }

      return [
        buildOwnedRow(),
        buildOwnedRow({
          item_id: 8,
          scryfall_id: "counterspell-1",
          name: "Counterspell",
          set_code: "7ed",
          set_name: "Seventh Edition",
          collector_number: "67",
          quantity: 1,
          location: "Trade Binder",
          tags: ["control"],
          est_value: "3.00",
          unit_price: "3.00",
          notes: null,
        }),
      ];
    });
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCards).mockResolvedValue([]);

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(await screen.findByRole("checkbox", { name: "Select Lightning Bolt" }));
    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Trade Binder/i }));

    expect(await screen.findByText("No rows selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Sol Ring" })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeInTheDocument();
  });
});
