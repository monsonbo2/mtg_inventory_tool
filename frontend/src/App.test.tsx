import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiClientError } from "./api";
import type {
  CatalogNameSearchRow,
  CatalogSearchRow,
  InventoryAuditEvent,
  OwnedInventoryRow,
} from "./types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    bootstrapDefaultInventory: vi.fn(),
    listInventories: vi.fn(),
    listInventoryItems: vi.fn(),
    listInventoryAudit: vi.fn(),
    searchCardNames: vi.fn(),
    listCardPrintings: vi.fn(),
    addInventoryItem: vi.fn(),
    bulkMutateInventoryItems: vi.fn(),
    createInventory: vi.fn(),
    patchInventoryItem: vi.fn(),
    deleteInventoryItem: vi.fn(),
  };
});

import {
  addInventoryItem,
  bootstrapDefaultInventory,
  bulkMutateInventoryItems,
  createInventory,
  listCardPrintings,
  listInventories,
  listInventoryItems,
  listInventoryAudit,
  patchInventoryItem,
  searchCardNames,
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

  function buildSearchRow(overrides: Partial<CatalogSearchRow> = {}): CatalogSearchRow {
    return {
      scryfall_id: "bolt-1",
      name: "Lightning Bolt",
      set_code: "lea",
      set_name: "Limited Edition Alpha",
      collector_number: "161",
      lang: "en",
      rarity: "common",
      finishes: ["normal"],
      tcgplayer_product_id: "1001",
      image_uri_small: null,
      image_uri_normal: null,
      ...overrides,
    };
  }

  function buildNameSearchRow(
    overrides: Partial<CatalogNameSearchRow> = {},
  ): CatalogNameSearchRow {
    return {
      oracle_id: "bolt-oracle",
      name: "Lightning Bolt",
      printings_count: 2,
      available_languages: ["en"],
      image_uri_small: null,
      image_uri_normal: null,
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
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
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
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
  }

  it("starts with an empty search field and keeps the example text as a placeholder only", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockResolvedValue([]);

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Search query" });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", "e.g. Lightning Bolt");

    await user.click(screen.getByRole("button", { name: "Search cards" }));

    expect(searchCardNames).not.toHaveBeenCalled();
    expect(screen.getByText("Run a search")).toBeInTheDocument();
  });

  it("classifies unauthenticated inventory loads as an auth-required shell state", async () => {
    vi.mocked(listInventories).mockRejectedValue(
      new ApiClientError("Authentication required.", {
        code: "authentication_required",
        status: 401,
      }),
    );
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    expect(await screen.findAllByText("Authentication required")).toHaveLength(3);
    expect(screen.queryByRole("combobox", { name: "Search query" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create Collection" })).not.toBeInTheDocument();
  });

  it("classifies forbidden inventory loads as an access-blocked shell state", async () => {
    vi.mocked(listInventories).mockRejectedValue(
      new ApiClientError("Forbidden.", {
        code: "forbidden",
        status: 403,
      }),
    );
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    expect(await screen.findAllByText("Collection access blocked")).toHaveLength(3);
    expect(screen.queryByRole("combobox", { name: "Search query" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create Collection" })).not.toBeInTheDocument();
  });

  it("classifies an empty visible inventory list without opening create-collection flow", async () => {
    vi.mocked(listInventories).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    expect(await screen.findAllByText("No visible collections")).toHaveLength(3);
    expect(screen.queryByRole("combobox", { name: "Search query" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create Collection" })).not.toBeInTheDocument();
  });

  it("bootstraps the default collection from the empty inventory state", async () => {
    const user = userEvent.setup();

    vi.mocked(listInventories)
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        {
          slug: "collection",
          display_name: "Collection",
          description: "Default personal collection",
          item_rows: 0,
          total_cards: 0,
        },
      ]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bootstrapDefaultInventory).mockResolvedValue({
      created: true,
      inventory: {
        inventory_id: 9,
        slug: "collection",
        display_name: "Collection",
        description: "Default personal collection",
      },
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Set Up My Collection" }));

    await waitFor(() => {
      expect(bootstrapDefaultInventory).toHaveBeenCalledTimes(1);
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Set up Collection.");
    expect(await screen.findByText("Current collection: Collection")).toBeInTheDocument();

    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledWith("collection");
      expect(listInventoryAudit).toHaveBeenCalledWith("collection");
    });
  });

  it("keeps the onboarding state visible when bootstrap fails", async () => {
    const user = userEvent.setup();

    vi.mocked(listInventories).mockResolvedValue([]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bootstrapDefaultInventory).mockRejectedValue(
      new ApiClientError("Editor access is required to set up a collection.", {
        code: "forbidden",
        status: 403,
      }),
    );

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Set Up My Collection" }));

    await waitFor(() => {
      expect(bootstrapDefaultInventory).toHaveBeenCalledTimes(1);
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Editor access is required to set up a collection.",
    );
    expect(screen.getByRole("button", { name: "Set Up My Collection" })).toBeInTheDocument();
    expect(screen.queryByText("Current collection: Collection")).not.toBeInTheDocument();
    expect(listInventoryItems).not.toHaveBeenCalled();
    expect(listInventoryAudit).not.toHaveBeenCalled();
  });

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
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
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

    await userEvent.click(await screen.findByRole("button", { name: "Detailed" }));

    const heading = await screen.findByRole("heading", { name: "Lightning Bolt" });
    const card = heading.closest("article");
    expect(card).not.toBeNull();
    const row = within(card!);
    expect(row.getByRole("combobox")).toBeEnabled();

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

    await user.click(await screen.findByRole("button", { name: "Detailed" }));

    const row = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest("article");
    expect(row).not.toBeNull();

    expect(within(row!).getByRole("combobox")).toBeEnabled();
    expect(within(row!).getByText("Available: Normal, Foil.")).toBeInTheDocument();
    expect(listCardPrintings).not.toHaveBeenCalled();
  });

  it("supports keyboard selection from autocomplete suggestions", async () => {
    const user = userEvent.setup();
    const forest = buildNameSearchRow({
      oracle_id: "forest-oracle",
      name: "Forest",
      printings_count: 1,
    });
    const forceOfWill = buildNameSearchRow({
      oracle_id: "force-oracle",
      name: "Force of Will",
      printings_count: 4,
      available_languages: ["en", "de"],
    });

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Fo") {
        return [forest, forceOfWill];
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

    expect(searchCardNames).toHaveBeenCalledWith({ query: "Fo", limit: 5 });
    expect(input).toHaveValue("Force of Will");
    expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Force of Will" })).toBeInTheDocument();
  });

  it("preserves backend ordering for name-search suggestions and grouped results", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "lightn") {
        return [
          buildNameSearchRow({
            oracle_id: "lightning-bolt-oracle",
            name: "Lightning Bolt",
            printings_count: 3,
          }),
          buildNameSearchRow({
            oracle_id: "lightning-angel-oracle",
            name: "Lightning Angel",
            printings_count: 5,
          }),
          buildNameSearchRow({
            oracle_id: "lightning-axe-oracle",
            name: "Lightning Axe",
            printings_count: 9,
          }),
          buildNameSearchRow({
            oracle_id: "lightning-blast-oracle",
            name: "Lightning Blast",
            printings_count: 6,
          }),
        ];
      }
      return [];
    });

    const { container } = render(<App />);

    const input = await screen.findByRole("combobox", { name: "Search query" });
    await user.type(input, "lightn");

    await screen.findByRole("option", { name: /Lightning Angel/i });

    const listbox = screen.getByRole("listbox", { name: "Card suggestions" });
    const suggestionNames = within(listbox)
      .getAllByRole("option")
      .map((option) => option.querySelector(".search-autocomplete-copy strong")?.textContent);

    expect(suggestionNames).toEqual([
      "Lightning Bolt",
      "Lightning Angel",
      "Lightning Axe",
      "Lightning Blast",
    ]);

    await user.click(screen.getByRole("button", { name: "Search cards" }));

    await screen.findByRole("heading", { name: "Lightning Angel" });

    const resultNames = Array.from(
      container.querySelectorAll(".search-results-grid article h3"),
    ).map((heading) => heading.textContent);

    expect(resultNames).toEqual([
      "Lightning Bolt",
      "Lightning Angel",
      "Lightning Axe",
      "Lightning Blast",
    ]);
  });

  it("groups name-first search results and clears the quick-add workspace after a successful add", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Lightning") {
        return [
          buildNameSearchRow({
            oracle_id: "bolt-oracle",
            name: "Lightning Bolt",
            printings_count: 3,
            available_languages: ["en", "ja"],
          }),
          buildNameSearchRow({
            oracle_id: "blast-oracle",
            name: "Lightning Blast",
            printings_count: 1,
            available_languages: ["en"],
          }),
        ];
      }
      return [];
    });
    vi.mocked(listCardPrintings).mockImplementation(async (oracleId) => {
      if (oracleId === "bolt-oracle") {
        return [
          buildSearchRow({
            scryfall_id: "bolt-alpha",
            name: "Lightning Bolt",
            set_code: "lea",
            set_name: "Limited Edition Alpha",
            collector_number: "161",
            finishes: ["normal"],
          }),
          buildSearchRow({
            scryfall_id: "bolt-m11",
            name: "Lightning Bolt",
            set_code: "m11",
            set_name: "Magic 2011",
            collector_number: "146",
            finishes: ["normal", "foil"],
          }),
          buildSearchRow({
            scryfall_id: "bolt-sta-ja",
            name: "Lightning Bolt",
            set_code: "sta",
            set_name: "Strixhaven Mystical Archive",
            collector_number: "39",
            lang: "ja",
            finishes: ["normal"],
          }),
        ];
      }
      return [];
    });
    vi.mocked(addInventoryItem).mockResolvedValue({ card_name: "Lightning Bolt" } as any);

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Search query" });
    await user.type(input, "Lightning");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    const boltCard = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest("article");
    expect(boltCard).not.toBeNull();
    expect(screen.getAllByRole("heading", { name: "Lightning Bolt" })).toHaveLength(1);
    expect(screen.getByRole("heading", { name: "Lightning Blast" })).toBeInTheDocument();

    const printingSelect = within(boltCard!).getByRole("combobox", { name: "Printing" });
    const finishSelect = within(boltCard!).getByRole("combobox", { name: "Finish" });

    expect(finishSelect).toBeDisabled();

    await user.click(printingSelect);

    await waitFor(() => {
      expect(listCardPrintings).toHaveBeenCalledWith("bolt-oracle", { lang: "all" });
    });

    expect(
      within(boltCard!).getByRole("button", { name: "Other languages available" }),
    ).toBeInTheDocument();
    expect(
      within(printingSelect).queryByRole("option", { name: /STRIXHAVEN MYSTICAL ARCHIVE/i }),
    ).not.toBeInTheDocument();

    await user.click(
      within(boltCard!).getByRole("button", { name: "Other languages available" }),
    );

    const languageSelect = within(boltCard!).getByRole("combobox", { name: "Language" });
    await user.selectOptions(languageSelect, "ja");

    expect(
      within(printingSelect).getByRole("option", { name: /STRIXHAVEN MYSTICAL ARCHIVE/i }),
    ).toBeInTheDocument();

    await user.selectOptions(languageSelect, "en");
    await user.selectOptions(printingSelect, "bolt-m11");

    expect(finishSelect).toBeEnabled();
    expect(within(finishSelect).getByRole("option", { name: "Foil" })).toBeInTheDocument();

    await user.selectOptions(finishSelect, "foil");
    await user.click(within(boltCard!).getByRole("button", { name: "Add to collection" }));

    await waitFor(() => {
      expect(addInventoryItem).toHaveBeenCalledWith(
        "personal",
        expect.objectContaining({
          scryfall_id: "bolt-m11",
          quantity: 1,
          finish: "foil",
        }),
      );
    });

    await waitFor(() => {
      expect(input).toHaveValue("");
    });
    expect(screen.queryByRole("heading", { name: "Lightning Bolt" })).not.toBeInTheDocument();
    expect(screen.getByText("Run a search")).toBeInTheDocument();
  });

  it("closes autocomplete on escape and outside click", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Fo") {
        return [
          buildNameSearchRow({
            oracle_id: "forest-oracle",
            name: "Forest",
            printings_count: 1,
          }),
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

  it("defaults to browse collection view and toggles detailed mode without refetching", async () => {
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

    await screen.findByRole("heading", { name: "Lightning Bolt" });
    expect(screen.queryByText("Inline edits")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "false");
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Detailed" }));

    expect(screen.getAllByText("Inline edits")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Detailed" })).toHaveAttribute("aria-pressed", "true");
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Browse" }));

    await screen.findByRole("heading", { name: "Lightning Bolt" });
    expect(screen.queryByText("Inline edits")).not.toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);
  });

  it("saves browse edits directly when a field blurs", async () => {
    const user = userEvent.setup();

    const initialBolt = buildOwnedRow();
    const updatedBolt = buildOwnedRow({ quantity: 5, est_value: "10.00" });

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 1,
        total_cards: 5,
      },
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
    vi.mocked(patchInventoryItem).mockResolvedValue({
      inventory: "personal",
      operation: "set_quantity",
      card_name: "Lightning Bolt",
      set_code: "lea",
      set_name: "Limited Edition Alpha",
      collector_number: "161",
      scryfall_id: "bolt-1",
      item_id: 7,
      quantity: 5,
      finish: "normal",
      condition_code: "NM",
      language_code: "en",
      location: "Binder",
      acquisition_price: "1.00",
      acquisition_currency: "USD",
      notes: "Main deck",
      tags: ["burn"],
      old_quantity: 2,
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    expect(boltRowScope.getByRole("combobox", { name: /Finish/ })).toBeEnabled();
    expect(
      boltRowScope.queryByRole("textbox", { name: /Notes/ }),
    ).not.toBeInTheDocument();
    const boltQuantityInput = boltRowScope.getByRole("spinbutton", { name: /Quantity/ });
    expect(boltRowScope.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();

    await user.clear(boltQuantityInput);
    await user.type(boltQuantityInput, "5");
    expect(boltRowScope.getByRole("spinbutton", { name: /Quantity/ })).toHaveValue(5);
    expect(boltRowScope.queryByText("Changes save automatically.")).not.toBeInTheDocument();
    await user.tab();

    await waitFor(() => {
      expect(patchInventoryItem).toHaveBeenCalledWith("personal", 7, { quantity: 5 });
    });
    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledTimes(2);
    });

    const refreshedBoltRow = (await screen.findByRole("heading", {
      name: "Lightning Bolt",
    })).closest("article");
    expect(refreshedBoltRow).not.toBeNull();
    const refreshedBoltScope = within(refreshedBoltRow!);
    const refreshedQuantityInput = refreshedBoltScope.getByRole("spinbutton", {
      name: /Quantity/,
    });
    expect(refreshedQuantityInput).toHaveValue(5);
    const refreshedQuantityField = refreshedQuantityInput.closest("label");
    expect(refreshedQuantityField).not.toBeNull();
    expect(within(refreshedQuantityField!).getByText("Saved")).toBeInTheDocument();
  });

  it("keeps browse validation feedback inside the quantity field instead of the row", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp();

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    const quantityInput = boltRowScope.getByRole("spinbutton", { name: /Quantity/ });

    await user.clear(quantityInput);
    await user.type(quantityInput, "0");

    const quantityField = quantityInput.closest("label");
    expect(quantityField).not.toBeNull();
    expect(
      within(quantityField!).getByText("Enter a whole-number quantity greater than 0."),
    ).toBeInTheDocument();
    expect(boltRow!.querySelector(".compact-row-status")).toBeNull();
  });

  it("offers existing collection locations as browse suggestions", async () => {
    mockCollectionViewApp({
      items: [
        buildOwnedRow({ location: "Binder" }),
        buildOwnedRow({
          item_id: 11,
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
        buildOwnedRow({
          item_id: 15,
          scryfall_id: "giant-growth-1",
          name: "Giant Growth",
          set_code: "lea",
          set_name: "Limited Edition Alpha",
          collector_number: "207",
          quantity: 3,
          location: "Binder",
          tags: ["pump"],
          est_value: "6.00",
          unit_price: "2.00",
          notes: null,
        }),
      ],
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const locationInput = within(boltRow!).getByRole("combobox", { name: /Location/ });
    const listId = locationInput.getAttribute("list");
    expect(listId).toBeTruthy();

    const locationList = document.getElementById(listId!);
    expect(locationList).not.toBeNull();
    const optionValues = Array.from(locationList!.querySelectorAll("option")).map((option) =>
      option.getAttribute("value"),
    );
    expect(optionValues).toEqual(["Binder", "Trade Binder"]);
  });

  it("updates browse finish from allowed options and refreshes the row value", async () => {
    const user = userEvent.setup();

    const initialBolt = buildOwnedRow({
      allowed_finishes: ["normal", "foil"],
      finish: "normal",
      est_value: "4.00",
      unit_price: "2.00",
    });
    const updatedBolt = buildOwnedRow({
      allowed_finishes: ["normal", "foil"],
      finish: "foil",
      est_value: "9.00",
      unit_price: "4.50",
    });

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 1,
        total_cards: 2,
      },
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
    vi.mocked(patchInventoryItem).mockResolvedValue({
      inventory: "personal",
      operation: "set_finish",
      card_name: "Lightning Bolt",
      set_code: "lea",
      set_name: "Limited Edition Alpha",
      collector_number: "161",
      scryfall_id: "bolt-1",
      item_id: 7,
      quantity: 2,
      finish: "foil",
      condition_code: "NM",
      language_code: "en",
      location: "Binder",
      acquisition_price: "1.00",
      acquisition_currency: "USD",
      notes: "Main deck",
      tags: ["burn"],
      old_finish: "normal",
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    const finishSelect = boltRowScope.getByRole("combobox", { name: /Finish/ });
    expect(finishSelect).toBeEnabled();
    expect(within(finishSelect).getByRole("option", { name: "Foil" })).toBeInTheDocument();

    await user.selectOptions(finishSelect, "foil");

    await waitFor(() => {
      expect(patchInventoryItem).toHaveBeenCalledWith("personal", 7, { finish: "foil" });
    });
    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledTimes(2);
    });

    const refreshedBoltRow = (await screen.findByRole("heading", {
      name: "Lightning Bolt",
    })).closest("article");
    expect(refreshedBoltRow).not.toBeNull();
    const refreshedBoltScope = within(refreshedBoltRow!);
    expect(refreshedBoltScope.getByRole("combobox", { name: /Finish/ })).toHaveValue("foil");
    expect(refreshedBoltScope.getByText("$9.00")).toBeInTheDocument();
  });

  it("adds a browse tag on Enter, saves it, clears the input, and keeps focus ready", async () => {
    const user = userEvent.setup();

    const initialBolt = buildOwnedRow({
      tags: ["burn"],
    });
    const updatedBolt = buildOwnedRow({
      tags: ["burn", "trade"],
    });

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 1,
        total_cards: 2,
      },
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
    vi.mocked(patchInventoryItem).mockResolvedValue({
      inventory: "personal",
      operation: "set_tags",
      card_name: "Lightning Bolt",
      set_code: "lea",
      set_name: "Limited Edition Alpha",
      collector_number: "161",
      scryfall_id: "bolt-1",
      item_id: 7,
      quantity: 2,
      finish: "normal",
      condition_code: "NM",
      language_code: "en",
      location: "Binder",
      acquisition_price: "1.00",
      acquisition_currency: "USD",
      notes: "Main deck",
      tags: ["burn", "trade"],
      old_tags: ["burn"],
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    const tagsInput = boltRowScope.getByRole("textbox", { name: /Tags/ });

    await user.type(tagsInput, "trade{enter}");

    await waitFor(() => {
      expect(patchInventoryItem).toHaveBeenCalledWith("personal", 7, {
        tags: ["burn", "trade"],
      });
    });
    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledTimes(2);
    });

    const refreshedBoltRow = (await screen.findByRole("heading", {
      name: "Lightning Bolt",
    })).closest("article");
    expect(refreshedBoltRow).not.toBeNull();
    const refreshedBoltScope = within(refreshedBoltRow!);
    const refreshedTagsInput = refreshedBoltScope.getByRole("textbox", { name: /Tags/ });
    expect(refreshedTagsInput).toHaveValue("");
    await waitFor(() => {
      expect(refreshedTagsInput).toHaveFocus();
    });
    expect(refreshedBoltScope.getByText("burn")).toBeInTheDocument();
    expect(refreshedBoltScope.getByText("trade")).toBeInTheDocument();
  });

  it("removes a browse tag once the tags field is active and keeps the tag input focused", async () => {
    const user = userEvent.setup();

    const initialBolt = buildOwnedRow({
      tags: ["burn", "trade"],
    });
    const updatedBolt = buildOwnedRow({
      tags: ["burn"],
    });

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 1,
        total_cards: 2,
      },
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
    vi.mocked(patchInventoryItem).mockResolvedValue({
      inventory: "personal",
      operation: "set_tags",
      card_name: "Lightning Bolt",
      set_code: "lea",
      set_name: "Limited Edition Alpha",
      collector_number: "161",
      scryfall_id: "bolt-1",
      item_id: 7,
      quantity: 2,
      finish: "normal",
      condition_code: "NM",
      language_code: "en",
      location: "Binder",
      acquisition_price: "1.00",
      acquisition_currency: "USD",
      notes: "Main deck",
      tags: ["burn"],
      old_tags: ["burn", "trade"],
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    const tagsInput = boltRowScope.getByRole("textbox", { name: /Tags/ });

    await user.click(tagsInput);
    expect(boltRowScope.getByText("Click a tag to remove it.")).toBeInTheDocument();
    await user.click(boltRowScope.getByRole("button", { name: "Remove tag trade" }));

    await waitFor(() => {
      expect(patchInventoryItem).toHaveBeenCalledWith("personal", 7, {
        tags: ["burn"],
      });
    });
    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledTimes(2);
    });

    const refreshedBoltRow = (await screen.findByRole("heading", {
      name: "Lightning Bolt",
    })).closest("article");
    expect(refreshedBoltRow).not.toBeNull();
    const refreshedBoltScope = within(refreshedBoltRow!);
    const refreshedTagsInput = refreshedBoltScope.getByRole("textbox", { name: /Tags/ });
    await waitFor(() => {
      expect(refreshedTagsInput).toHaveFocus();
    });
    expect(refreshedBoltScope.getByText("Removed trade.")).toBeInTheDocument();
    expect(refreshedBoltScope.getByText("burn")).toBeInTheDocument();
    expect(refreshedBoltScope.queryByText("trade")).not.toBeInTheDocument();
  });

  it("removes the last browse tag with Backspace when the tag input is empty", async () => {
    const user = userEvent.setup();

    const initialBolt = buildOwnedRow({
      tags: ["burn", "trade"],
    });
    const updatedBolt = buildOwnedRow({
      tags: ["burn"],
    });

    vi.mocked(listInventories).mockResolvedValue([
      {
        slug: "personal",
        display_name: "Personal Collection",
        description: "Main demo inventory",
        item_rows: 1,
        total_cards: 2,
      },
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
    vi.mocked(patchInventoryItem).mockResolvedValue({
      inventory: "personal",
      operation: "set_tags",
      card_name: "Lightning Bolt",
      set_code: "lea",
      set_name: "Limited Edition Alpha",
      collector_number: "161",
      scryfall_id: "bolt-1",
      item_id: 7,
      quantity: 2,
      finish: "normal",
      condition_code: "NM",
      language_code: "en",
      location: "Binder",
      acquisition_price: "1.00",
      acquisition_currency: "USD",
      notes: "Main deck",
      tags: ["burn"],
      old_tags: ["burn", "trade"],
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    const tagsInput = boltRowScope.getByRole("textbox", { name: /Tags/ });

    await user.click(tagsInput);
    expect(tagsInput).toHaveValue("");
    await user.keyboard("{Backspace}");

    await waitFor(() => {
      expect(patchInventoryItem).toHaveBeenCalledWith("personal", 7, {
        tags: ["burn"],
      });
    });
    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledTimes(2);
    });

    const refreshedBoltRow = (await screen.findByRole("heading", {
      name: "Lightning Bolt",
    })).closest("article");
    expect(refreshedBoltRow).not.toBeNull();
    const refreshedBoltScope = within(refreshedBoltRow!);
    const refreshedTagsInput = refreshedBoltScope.getByRole("textbox", { name: /Tags/ });
    await waitFor(() => {
      expect(refreshedTagsInput).toHaveFocus();
    });
    expect(refreshedBoltScope.getByText("burn")).toBeInTheDocument();
    expect(refreshedBoltScope.queryByText("trade")).not.toBeInTheDocument();
  });

  it("uses the first browse tag click to activate tag removal instead of removing immediately", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [
        buildOwnedRow({
          tags: ["burn", "trade"],
        }),
      ],
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);

    await user.click(boltRowScope.getByText("trade"));

    expect(patchInventoryItem).not.toHaveBeenCalled();
    const tagsInput = boltRowScope.getByRole("textbox", { name: /Tags/ });
    await waitFor(() => {
      expect(tagsInput).toHaveFocus();
    });
    expect(boltRowScope.getByText("Click a tag to remove it.")).toBeInTheDocument();
    expect(
      boltRowScope.getByRole("button", { name: "Remove tag trade" }),
    ).toBeInTheDocument();
  });

  it("exits browse tag edit mode on Escape", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [
        buildOwnedRow({
          tags: ["burn", "trade"],
        }),
      ],
    });

    render(<App />);

    const boltRow = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltRow).not.toBeNull();
    const boltRowScope = within(boltRow!);
    const tagsInput = boltRowScope.getByRole("textbox", { name: /Tags/ });

    await user.click(tagsInput);
    expect(boltRowScope.getByText("Click a tag to remove it.")).toBeInTheDocument();
    expect(boltRowScope.getByRole("button", { name: "Remove tag trade" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(tagsInput).not.toHaveFocus();
    });
    expect(boltRowScope.queryByText("Click a tag to remove it.")).not.toBeInTheDocument();
    expect(
      boltRowScope.queryByRole("button", { name: "Remove tag trade" }),
    ).not.toBeInTheDocument();
    expect(boltRowScope.getByText("trade")).toBeInTheDocument();
  });

  it("opens the matching row in detailed view from browse mode", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [
        buildOwnedRow(),
        buildOwnedRow({
          item_id: 11,
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

    const counterspellRow = (await screen.findByRole("heading", { name: "Counterspell" })).closest(
      "article",
    );
    expect(counterspellRow).not.toBeNull();

    await user.click(
      within(counterspellRow!).getByRole("button", { name: "Open details" }),
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Detailed" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    });

    const detailedCounterspellRow = (await screen.findByRole("heading", {
      name: "Counterspell",
    })).closest("article");
    expect(detailedCounterspellRow).not.toBeNull();
    expect(detailedCounterspellRow).toHaveAttribute("data-focused", "true");
    await waitFor(() => {
      expect(detailedCounterspellRow).toHaveFocus();
    });
    expect(within(detailedCounterspellRow!).getByText("Inline edits")).toBeInTheDocument();
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
    expect(screen.queryByRole("dialog", { name: "Collection Activity" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "View Activity" }));
    expect(await screen.findByRole("dialog", { name: "Collection Activity" })).toBeInTheDocument();
    expect(screen.getByText("Set Finish")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close activity drawer" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Collection Activity" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "View Activity" }));
    expect(await screen.findByRole("dialog", { name: "Collection Activity" })).toBeInTheDocument();

    await user.click(screen.getByTestId("activity-drawer-backdrop"));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Collection Activity" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "View Activity" }));
    expect(await screen.findByRole("dialog", { name: "Collection Activity" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Collection Activity" })).not.toBeInTheDocument();
    });
  });

  it("moves focus into the activity drawer, traps tab focus, and returns focus to the opener", async () => {
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

    const openButton = await screen.findByRole("button", { name: "View Activity" });
    openButton.focus();
    expect(openButton).toHaveFocus();

    await user.click(openButton);

    const closeButton = await screen.findByRole("button", {
      name: "Close activity drawer",
    });
    await waitFor(() => {
      expect(closeButton).toHaveFocus();
    });

    await user.tab();
    expect(closeButton).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => {
      expect(
        screen.queryByRole("dialog", { name: "Collection Activity" }),
      ).not.toBeInTheDocument();
    });
    expect(openButton).toHaveFocus();
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

    const table = screen.getByRole("table");
    const lightningBoltRow = within(table)
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("Lightning Bolt"));
    expect(lightningBoltRow).toBeDefined();

    await user.click(lightningBoltRow!);

    expect(screen.getByText("1 row selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();

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

  it("supports header-driven table sorting and filtering while keeping hidden selections visible in the summary", async () => {
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

    const table = screen.getByRole("table");
    const getRows = () => within(table).getAllByRole("row").slice(1);

    expect(getRows()[0]).toHaveTextContent("Lightning Bolt");
    expect(getRows()[1]).toHaveTextContent("Counterspell");

    await user.click(screen.getByRole("button", { name: "Qty" }));
    await user.click(screen.getByRole("button", { name: "Lowest quantity first" }));

    expect(getRows()[0]).toHaveTextContent("Counterspell");
    expect(getRows()[1]).toHaveTextContent("Lightning Bolt");

    await user.click(screen.getByRole("checkbox", { name: "Select Counterspell" }));
    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Set" }));
    await user.click(screen.getByLabelText("LEA · Limited Edition Alpha"));

    expect(screen.getByText("Showing 1 of 2 rows.")).toBeInTheDocument();
    expect(screen.getByText("1 selected row hidden by current filters.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select Counterspell" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Select all visible" }));

    expect(screen.getByText("2 rows selected")).toBeInTheDocument();
    expect(screen.getByText("1 selected row hidden by current filters.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(screen.getByText("Showing all 2 rows.")).toBeInTheDocument();
    expect(screen.queryByText("1 selected row hidden by current filters.")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
  });

  it("applies bulk tag actions to selected table rows and clears the selection after success", async () => {
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
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [7, 8],
      updated_item_ids: [7, 8],
      updated_count: 2,
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Select all visible" }));

    expect(screen.getByText("2 rows selected")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Bulk tags" }), "burn, staples");
    await user.click(screen.getByRole("button", { name: "Add tags" }));

    await waitFor(() => {
      expect(bulkMutateInventoryItems).toHaveBeenCalledWith("personal", {
        operation: "add_tags",
        item_ids: [7, 8],
        tags: ["burn", "staples"],
      });
    });

    await waitFor(() => {
      expect(screen.getByText("No rows selected")).toBeInTheDocument();
    });
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).not.toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Added tags on 2 rows in Personal Collection.",
    );
    expect(listInventoryItems).toHaveBeenCalledTimes(2);
    expect(listInventoryAudit).toHaveBeenCalledTimes(2);
  });

  it("submits clear-tags bulk actions without sending a tags payload", async () => {
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
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "clear_tags",
      requested_item_ids: [7, 8],
      updated_item_ids: [7, 8],
      updated_count: 2,
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    await user.type(screen.getByRole("textbox", { name: "Bulk tags" }), "burn, staples");
    await user.click(screen.getByRole("button", { name: "Clear tags" }));

    await waitFor(() => {
      expect(bulkMutateInventoryItems).toHaveBeenCalledWith("personal", {
        operation: "clear_tags",
        item_ids: [7, 8],
      });
    });

    expect(screen.getByRole("textbox", { name: "Bulk tags" })).toHaveValue("");
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Cleared tags on 2 rows in Personal Collection.",
    );
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
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(await screen.findByRole("checkbox", { name: "Select Lightning Bolt" }));
    expect(screen.getByText("1 row selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Change collection/i }));
    await user.click(screen.getByRole("button", { name: /Trade Binder/i }));

    expect(await screen.findByText("No rows selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Sol Ring" })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeInTheDocument();
  });

  it("creates a new inventory from the sidebar and selects it", async () => {
    const user = userEvent.setup();

    vi.mocked(listInventories)
      .mockResolvedValueOnce([
        {
          slug: "personal",
          display_name: "Personal Collection",
          description: "Main demo inventory",
          item_rows: 0,
          total_cards: 0,
        },
      ])
      .mockResolvedValueOnce([
        {
          slug: "personal",
          display_name: "Personal Collection",
          description: "Main demo inventory",
          item_rows: 0,
          total_cards: 0,
        },
        {
          slug: "trade-binder",
          display_name: "Trade Binder",
          description: "Cards available to trade",
          item_rows: 0,
          total_cards: 0,
        },
      ]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(createInventory).mockResolvedValue({
      inventory_id: 42,
      slug: "trade-binder",
      display_name: "Trade Binder",
      description: "Cards available to trade",
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Create Collection" }));
    const dialog = await screen.findByRole("dialog", { name: "Create Collection" });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: "Collection name" })).toHaveFocus();
    expect(within(dialog).queryByRole("textbox", { name: /Short name/i })).not.toBeInTheDocument();
    await user.type(within(dialog).getByRole("textbox", { name: "Collection name" }), "Trade Binder");

    await user.type(
      within(dialog).getByRole("textbox", { name: "Description (optional)" }),
      "Cards available to trade",
    );
    await user.click(within(dialog).getByRole("button", { name: "Create Collection" }));

    await waitFor(() => {
      expect(createInventory).toHaveBeenCalledWith({
        slug: "trade-binder",
        display_name: "Trade Binder",
        description: "Cards available to trade",
      });
    });

    expect(await screen.findByRole("status")).toHaveTextContent("Created Trade Binder.");
    expect(await screen.findByText("Current collection: Trade Binder")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Create Collection" })).not.toBeInTheDocument();

    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledWith("trade-binder");
      expect(listInventoryAudit).toHaveBeenCalledWith("trade-binder");
    });
  });

  it("reveals the short name field after a create conflict", async () => {
    const user = userEvent.setup();

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
    vi.mocked(searchCardNames).mockResolvedValue([]);
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(createInventory).mockRejectedValue(
      new ApiClientError("Inventory short name already exists.", {
        code: "conflict",
        status: 409,
      }),
    );

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Create Collection" }));
    const dialog = await screen.findByRole("dialog", { name: "Create Collection" });
    expect(within(dialog).queryByRole("textbox", { name: /Short name/i })).not.toBeInTheDocument();

    await user.type(within(dialog).getByRole("textbox", { name: "Collection name" }), "Trade Binder");
    await user.click(within(dialog).getByRole("button", { name: "Create Collection" }));

    expect(await within(dialog).findByRole("textbox", { name: /Short name/i })).toHaveValue(
      "trade-binder",
    );
    expect(
      screen.getByText(
        "That collection name needs a different short name. Edit it below and try again.",
      ),
    ).toBeInTheDocument();
  });
});
