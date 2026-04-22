import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiClientError } from "./api";
import type {
  AccessSummaryResponse,
  CatalogNameSearchResult,
  CatalogNameSearchRow,
  CatalogPrintingLookupRow,
  CatalogPrintingSummaryResponse,
  InventoryAuditEvent,
  InventoryCreateResponse,
  InventorySummary,
  OwnedInventoryRow,
} from "./types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    listInventories: vi.fn(),
    getAccessSummary: vi.fn(),
    listInventoryItems: vi.fn(),
    listInventoryAudit: vi.fn(),
    searchCardNames: vi.fn(),
    listCardPrintings: vi.fn(),
    getCardPrintingSummary: vi.fn(),
    addInventoryItem: vi.fn(),
    bulkMutateInventoryItems: vi.fn(),
    bootstrapDefaultInventory: vi.fn(),
    createInventory: vi.fn(),
    patchInventoryItem: vi.fn(),
    deleteInventoryItem: vi.fn(),
    importCsv: vi.fn(),
    importDeckUrl: vi.fn(),
    importDecklist: vi.fn(),
    transferInventoryItems: vi.fn(),
  };
});

import {
  addInventoryItem,
  bootstrapDefaultInventory,
  bulkMutateInventoryItems,
  createInventory,
  getAccessSummary,
  importCsv,
  importDeckUrl,
  importDecklist,
  getCardPrintingSummary,
  listCardPrintings,
  listInventories,
  listInventoryItems,
  listInventoryAudit,
  patchInventoryItem,
  searchCardNames,
  transferInventoryItems,
} from "./api";

beforeEach(() => {
  vi.mocked(getAccessSummary).mockResolvedValue({
    can_bootstrap: true,
    has_readable_inventory: true,
    visible_inventory_count: 1,
    default_inventory_slug: null,
  });
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("App", () => {
  function buildOwnedRow(overrides: Partial<OwnedInventoryRow> = {}): OwnedInventoryRow {
    return {
      item_id: 7,
      scryfall_id: "bolt-1",
      oracle_id: "bolt-oracle",
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
      printing_selection_mode: "explicit",
      ...overrides,
    };
  }

  function buildSearchRow(
    overrides: Partial<CatalogPrintingLookupRow> = {},
  ): CatalogPrintingLookupRow {
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
      is_default_add_choice: false,
      ...overrides,
    };
  }

  function buildPrintingSummary(
    printings: CatalogPrintingLookupRow[] = [],
    overrides: Partial<CatalogPrintingSummaryResponse> = {},
  ): CatalogPrintingSummaryResponse {
    const defaultPrinting =
      printings.find((printing) => printing.is_default_add_choice) || null;
    const availableLanguages = Array.from(
      new Set(printings.map((printing) => printing.lang)),
    );

    return {
      oracle_id: "bolt-oracle",
      default_printing: defaultPrinting,
      available_languages: availableLanguages.length ? availableLanguages : ["en"],
      printings_count: printings.length,
      has_more_printings: false,
      printings,
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

  function buildNameSearchResult(
    items: CatalogNameSearchRow[] = [],
    overrides: Partial<Omit<CatalogNameSearchResult, "items">> = {},
  ): CatalogNameSearchResult {
    return {
      items,
      total_count: overrides.total_count ?? items.length,
      has_more: overrides.has_more ?? false,
    };
  }

  function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (reason?: unknown) => void;
    const promise = new Promise<T>((promiseResolve, promiseReject) => {
      resolve = promiseResolve;
      reject = promiseReject;
    });
    return { promise, reject, resolve };
  }

  function buildInventorySummary(
    overrides: Partial<InventorySummary> = {},
  ): InventorySummary {
    return {
      slug: "personal",
      display_name: "Personal Collection",
      description: "Main demo inventory",
      default_location: null,
      default_tags: null,
      notes: null,
      acquisition_price: null,
      acquisition_currency: null,
      item_rows: 0,
      total_cards: 0,
      role: "owner",
      can_read: true,
      can_write: true,
      can_manage_share: true,
      can_transfer_to: true,
      ...overrides,
    };
  }

  function buildAccessSummary(
    overrides: Partial<AccessSummaryResponse> = {},
  ): AccessSummaryResponse {
    return {
      can_bootstrap: true,
      has_readable_inventory: true,
      visible_inventory_count: 1,
      default_inventory_slug: null,
      ...overrides,
    };
  }

  function buildDecklistImportResponse(overrides: Record<string, unknown> = {}) {
    return {
      deck_name: null,
      default_inventory: "personal",
      rows_seen: 1,
      rows_written: 1,
      ready_to_commit: true,
      summary: {
        total_card_quantity: 4,
        distinct_card_names: 1,
        distinct_printings: 1,
        section_card_quantities: {},
        requested_card_quantity: 4,
        unresolved_card_quantity: 0,
      },
      resolution_issues: [],
      dry_run: false,
      imported_rows: [],
      ...overrides,
    } as any;
  }

  function buildDeckUrlImportResponse(overrides: Record<string, unknown> = {}) {
    return {
      source_url: "https://www.moxfield.com/decks/demo",
      provider: "moxfield",
      deck_name: null,
      default_inventory: "personal",
      rows_seen: 1,
      rows_written: 1,
      ready_to_commit: true,
      source_snapshot_token: null,
      summary: {
        total_card_quantity: 4,
        distinct_card_names: 1,
        distinct_printings: 1,
        section_card_quantities: {},
        requested_card_quantity: 4,
        unresolved_card_quantity: 0,
      },
      resolution_issues: [],
      dry_run: false,
      imported_rows: [],
      ...overrides,
    } as any;
  }

  function buildCsvImportResponse(overrides: Record<string, unknown> = {}) {
    return {
      csv_filename: "cards.csv",
      detected_format: "generic_csv",
      default_inventory: "personal",
      rows_seen: 1,
      rows_written: 1,
      ready_to_commit: true,
      summary: {
        total_card_quantity: 4,
        distinct_card_names: 1,
        distinct_printings: 1,
        requested_card_quantity: 4,
        unresolved_card_quantity: 0,
      },
      resolution_issues: [],
      dry_run: false,
      imported_rows: [],
      ...overrides,
    } as any;
  }

  function buildInventoryCreateResponse(
    overrides: Partial<InventoryCreateResponse> = {},
  ): InventoryCreateResponse {
    return {
      inventory_id: 1,
      slug: "personal",
      display_name: "Personal Collection",
      description: "Main demo inventory",
      default_location: null,
      default_tags: null,
      notes: null,
      acquisition_price: null,
      acquisition_currency: null,
      ...overrides,
    };
  }

  function mockCollectionViewApp(options?: {
    items?: OwnedInventoryRow[];
    auditEvents?: InventoryAuditEvent[];
    inventories?: InventorySummary[];
  }) {
    const items = options?.items ?? [buildOwnedRow()];
    const auditEvents = options?.auditEvents ?? [];
    const inventories =
      options?.inventories ??
      [
        buildInventorySummary({
          item_rows: items.length,
          total_cards: items.reduce((sum, item) => sum + item.quantity, 0),
        }),
      ];

    vi.mocked(listInventories).mockResolvedValue(inventories);
    vi.mocked(listInventoryItems).mockResolvedValue(items);
    vi.mocked(listInventoryAudit).mockResolvedValue(auditEvents);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(getCardPrintingSummary).mockResolvedValue(buildPrintingSummary());
    vi.mocked(importCsv).mockResolvedValue(buildCsvImportResponse());
    vi.mocked(importDeckUrl).mockResolvedValue(buildDeckUrlImportResponse());
    vi.mocked(importDecklist).mockResolvedValue(buildDecklistImportResponse());
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
    vi.mocked(transferInventoryItems).mockResolvedValue({
      source_inventory: "personal",
      target_inventory: inventories[1]?.slug ?? "target",
      mode: "copy",
      dry_run: false,
      selection_kind: "items",
      requested_item_ids: [],
      requested_count: 0,
      copied_count: 0,
      moved_count: 0,
      merged_count: 0,
      failed_count: 0,
      results_returned: 0,
      results_truncated: false,
      results: [],
    });
  }

  function mockBaseSearchApp() {
    vi.mocked(listInventories).mockResolvedValue([
      buildInventorySummary(),
    ]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(getCardPrintingSummary).mockResolvedValue(buildPrintingSummary());
    vi.mocked(importCsv).mockResolvedValue(buildCsvImportResponse());
    vi.mocked(importDeckUrl).mockResolvedValue(buildDeckUrlImportResponse());
    vi.mocked(importDecklist).mockResolvedValue(buildDecklistImportResponse());
    vi.mocked(bulkMutateInventoryItems).mockResolvedValue({
      inventory: "personal",
      operation: "add_tags",
      requested_item_ids: [],
      updated_item_ids: [],
      updated_count: 0,
    });
    vi.mocked(transferInventoryItems).mockResolvedValue({
      source_inventory: "personal",
      target_inventory: "target",
      mode: "copy",
      dry_run: false,
      selection_kind: "items",
      requested_item_ids: [],
      requested_count: 0,
      copied_count: 0,
      moved_count: 0,
      merged_count: 0,
      failed_count: 0,
      results_returned: 0,
      results_truncated: false,
      results: [],
    });
  }

  it("starts with an empty search field and keeps the example text as a placeholder only", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    expect(input).toHaveValue("");
    expect(input).toHaveAttribute("placeholder", "e.g. Lightning Bolt");

    await user.click(screen.getByRole("button", { name: "Search cards" }));

    expect(searchCardNames).not.toHaveBeenCalled();
    expect(screen.queryByText("Run a search")).not.toBeInTheDocument();
  });

  it("loads readable inventories after the access summary startup probe", async () => {
    mockBaseSearchApp();

    render(<App />);

    expect(await screen.findByText("Current collection: Personal Collection")).toBeInTheDocument();
    expect(getAccessSummary).toHaveBeenCalledTimes(1);
    expect(listInventories).toHaveBeenCalledTimes(1);
    expect(vi.mocked(getAccessSummary).mock.invocationCallOrder[0]).toBeLessThan(
      vi.mocked(listInventories).mock.invocationCallOrder[0],
    );
  });

  it("opens an import menu above search with URL, text, and CSV options", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Import Cards" }));

    const menu = screen.getByRole("menu", { name: "Import Cards" });
    expect(within(menu).getByRole("menuitem", { name: /Import from URL/i })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Import as Text/i })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: /Import from CSV/i })).toBeInTheDocument();
  });

  it("imports pasted text into the selected collection from the search panel", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(importDecklist).mockResolvedValue(buildDecklistImportResponse());

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Import Cards" }));
    await user.click(screen.getByRole("menuitem", { name: /Import as Text/i }));

    const dialog = await screen.findByRole("dialog", { name: "Import As Text" });
    await user.type(within(dialog).getByRole("textbox", { name: "Card list" }), "4 Lightning Bolt");
    await user.click(within(dialog).getByRole("button", { name: "Import cards" }));

    await waitFor(() => {
      expect(importDecklist).toHaveBeenCalledWith({
        deck_text: "4 Lightning Bolt",
        default_inventory: "personal",
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Imported 4 cards into Personal Collection.",
    );
    expect(screen.queryByRole("dialog", { name: "Import As Text" })).not.toBeInTheDocument();
  });

  it("imports into a different existing collection chosen in the import dialog", async () => {
    const user = userEvent.setup();
    const personal = buildInventorySummary();
    const trade = buildInventorySummary({
      slug: "trade",
      display_name: "Trade Binder",
      description: "Cards for trades",
      item_rows: 3,
      total_cards: 12,
    });

    mockBaseSearchApp();
    vi.mocked(listInventories).mockResolvedValue([personal, trade]);
    vi.mocked(importDecklist).mockResolvedValue(
      buildDecklistImportResponse({ default_inventory: "trade" }),
    );

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Import Cards" }));
    await user.click(screen.getByRole("menuitem", { name: /Import as Text/i }));

    const dialog = await screen.findByRole("dialog", { name: "Import As Text" });
    await user.click(within(dialog).getByRole("button", { name: /Trade Binder/i }));
    await user.type(within(dialog).getByRole("textbox", { name: "Card list" }), "4 Lightning Bolt");
    await user.click(within(dialog).getByRole("button", { name: "Import cards" }));

    await waitFor(() => {
      expect(importDecklist).toHaveBeenCalledWith({
        deck_text: "4 Lightning Bolt",
        default_inventory: "trade",
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Imported 4 cards into Trade Binder.",
    );
    expect(await screen.findByText("Current collection: Trade Binder")).toBeInTheDocument();
  });

  it("creates a new collection from the import dialog and imports into it", async () => {
    const user = userEvent.setup();
    const personal = buildInventorySummary();
    const demoImports = buildInventoryCreateResponse({
      inventory_id: 2,
      slug: "demo-imports",
      display_name: "Demo Imports",
      description: null,
      default_location: "Trade Binder",
      default_tags: "trade, staples",
    });

    mockBaseSearchApp();
    vi.mocked(listInventories)
      .mockResolvedValueOnce([personal])
      .mockResolvedValue([personal, buildInventorySummary({
        slug: "demo-imports",
        display_name: "Demo Imports",
        description: null,
      })]);
    vi.mocked(createInventory).mockResolvedValue(demoImports);
    vi.mocked(importDecklist).mockResolvedValue(
      buildDecklistImportResponse({ default_inventory: "demo-imports" }),
    );

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Import Cards" }));
    await user.click(screen.getByRole("menuitem", { name: /Import as Text/i }));

    const dialog = await screen.findByRole("dialog", { name: "Import As Text" });
    await user.click(within(dialog).getByRole("button", { name: "Create new" }));
    await user.type(
      within(dialog).getByRole("textbox", { name: "Collection name" }),
      "Demo Imports",
    );
    await user.type(
      within(dialog).getByRole("textbox", { name: /Default location/i }),
      "Trade Binder",
    );
    await user.type(
      within(dialog).getByRole("textbox", { name: /Default tags/i }),
      "Trade, Staples",
    );
    await user.type(within(dialog).getByRole("textbox", { name: "Card list" }), "4 Lightning Bolt");
    await user.click(within(dialog).getByRole("button", { name: "Import cards" }));

    await waitFor(() => {
      expect(createInventory).toHaveBeenCalledWith({
        display_name: "Demo Imports",
        slug: "demo-imports",
        description: null,
        default_location: "Trade Binder",
        default_tags: "trade, staples",
      });
    });
    await waitFor(() => {
      expect(importDecklist).toHaveBeenCalledWith({
        deck_text: "4 Lightning Bolt",
        default_inventory: "demo-imports",
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Imported 4 cards into Demo Imports.",
    );
  });

  it("shows a generic collections-unavailable shell state when collection loading fails with 401", async () => {
    vi.mocked(getAccessSummary).mockRejectedValue(
      new ApiClientError("Authentication required.", {
        code: "authentication_required",
        status: 401,
      }),
    );
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    expect(await screen.findByText("Collections unavailable")).toBeInTheDocument();
    expect(screen.getByText("Search not ready yet")).toBeInTheDocument();
    expect(screen.getByText("Collection view not ready yet")).toBeInTheDocument();
    expect(screen.queryByText("Authentication required.")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Quick Add and Card Search" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create Collection" })).not.toBeInTheDocument();
    expect(listInventories).not.toHaveBeenCalled();
  });

  it("shows a generic collections-unavailable shell state when collection loading fails with 403", async () => {
    vi.mocked(getAccessSummary).mockRejectedValue(
      new ApiClientError("Forbidden.", {
        code: "forbidden",
        status: 403,
      }),
    );
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    expect(await screen.findByText("Collections unavailable")).toBeInTheDocument();
    expect(screen.getByText("Search not ready yet")).toBeInTheDocument();
    expect(screen.getByText("Collection view not ready yet")).toBeInTheDocument();
    expect(screen.queryByText("Forbidden.")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Quick Add and Card Search" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create Collection" })).not.toBeInTheDocument();
    expect(listInventories).not.toHaveBeenCalled();
  });

  it("shows a bootstrap shell state with a create action when no readable collections exist yet", async () => {
    vi.mocked(getAccessSummary).mockResolvedValue(
      buildAccessSummary({
        has_readable_inventory: false,
        visible_inventory_count: 0,
      }),
    );
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    expect(await screen.findByText("Start your first collection")).toBeInTheDocument();
    expect(screen.getByText("Search is ready when you are")).toBeInTheDocument();
    expect(screen.getByText("Your cards will appear here")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Quick Add and Card Search" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create Collection" })).toBeInTheDocument();
    expect(listInventories).not.toHaveBeenCalled();
  });

  it("shows an access-needed shell state without a create action when bootstrap is unavailable", async () => {
    vi.mocked(getAccessSummary).mockResolvedValue(
      buildAccessSummary({
        can_bootstrap: false,
        has_readable_inventory: false,
        visible_inventory_count: 0,
      }),
    );
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    await waitFor(() => {
      expect(screen.getAllByText("Collection access needed").length).toBeGreaterThan(0);
    });
    expect(screen.getByText("Search waiting for access")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Quick Add and Card Search" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create Collection" })).not.toBeInTheDocument();
    expect(listInventories).not.toHaveBeenCalled();
  });

  it("creates a custom first collection from the empty onboarding state", async () => {
    const user = userEvent.setup();

    vi.mocked(getAccessSummary)
      .mockResolvedValueOnce(
        buildAccessSummary({
          has_readable_inventory: false,
          visible_inventory_count: 0,
        }),
      )
      .mockResolvedValueOnce(
        buildAccessSummary({
          default_inventory_slug: null,
        }),
      );
    vi.mocked(listInventories).mockResolvedValueOnce([
        buildInventorySummary({
          slug: "commander-decks",
          display_name: "Commander Decks",
          description: "Built and brewing commander lists",
        }),
      ]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(createInventory).mockResolvedValue(
      buildInventoryCreateResponse({
        inventory_id: 9,
        slug: "commander-decks",
        display_name: "Commander Decks",
        description: "Built and brewing commander lists",
      }),
    );

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Create Collection" }));

    const dialog = await screen.findByRole("dialog", { name: "Create Collection" });
    await user.type(within(dialog).getByRole("textbox", { name: "Collection name" }), "Commander Decks");
    await user.type(
      within(dialog).getByRole("textbox", { name: "Description (optional)" }),
      "Built and brewing commander lists",
    );
    await user.click(within(dialog).getByRole("button", { name: "Create Collection" }));

    await waitFor(() => {
      expect(createInventory).toHaveBeenCalledWith({
        slug: "commander-decks",
        display_name: "Commander Decks",
        description: "Built and brewing commander lists",
      });
    });
    expect(bootstrapDefaultInventory).not.toHaveBeenCalled();

    expect(await screen.findByRole("status")).toHaveTextContent("Created Commander Decks.");
    expect(await screen.findByText("Current collection: Commander Decks")).toBeInTheDocument();

    await waitFor(() => {
      expect(listInventoryItems).toHaveBeenCalledWith("commander-decks");
      expect(listInventoryAudit).toHaveBeenCalledWith("commander-decks");
    });
  });

  it("surfaces backend patch errors as a notice", async () => {
    const ownedRow: OwnedInventoryRow = {
      item_id: 7,
      scryfall_id: "bolt-1",
      oracle_id: "bolt-oracle",
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
      printing_selection_mode: "explicit",
    };

    vi.mocked(listInventories).mockResolvedValue([
      buildInventorySummary({
        item_rows: 1,
        total_cards: 2,
      }),
    ]);
    vi.mocked(listInventoryItems).mockResolvedValue([ownedRow]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
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

    const heading = await screen.findByRole("heading", { name: "Lightning Bolt" });
    const card = heading.closest("article");
    expect(card).not.toBeNull();

    await userEvent.click(within(card!).getByRole("button", { name: "Open details" }));

    const dialog = await screen.findByRole("dialog", { name: "Card details" });
    const row = within(dialog);
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

    const row = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest("article");
    expect(row).not.toBeNull();

    await user.click(within(row!).getByRole("button", { name: "Open details" }));

    const dialog = await screen.findByRole("dialog", { name: "Card details" });
    expect(within(dialog).getByRole("combobox")).toBeEnabled();
    expect(within(dialog).getByText("Available: Normal, Foil.")).toBeInTheDocument();
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
        return buildNameSearchResult([forest, forceOfWill]);
      }
      return buildNameSearchResult();
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
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

    expect(searchCardNames).toHaveBeenCalledWith({ query: "Fo", limit: 8 });
    expect(input).toHaveValue("Force of Will");
    expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Force of Will" })).toBeInTheDocument();
    expect(screen.queryByText("Matching cards")).not.toBeInTheDocument();
  });

  it("lets arrow-up return keyboard focus to the search input so Enter submits the full search", async () => {
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
        return buildNameSearchResult([forest, forceOfWill]);
      }
      return buildNameSearchResult();
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.clear(input);
    await user.type(input, "Fo");

    await screen.findByRole("option", { name: /Forest/i });
    expect(input).toHaveAttribute("aria-activedescendant", expect.stringContaining("-option-0"));

    await user.keyboard("{ArrowUp}");

    expect(input).not.toHaveAttribute("aria-activedescendant");

    await user.keyboard("{Enter}");

    expect(searchCardNames).toHaveBeenLastCalledWith({ query: "Fo", limit: 18 });
    expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Forest" })).toBeInTheDocument();
    expect(screen.getByText("Matching cards")).toBeInTheDocument();
  });

  it("uses arrow keys to move through matching cards after a submitted search and Enter selects the card", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "lightn") {
        return buildNameSearchResult([
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
        ]);
      }
      return buildNameSearchResult();
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "lightn");
    await screen.findByRole("option", { name: /Lightning Angel/i });

    await user.keyboard("{ArrowUp}");
    expect(input).not.toHaveAttribute("aria-activedescendant");

    await user.keyboard("{Enter}");

    expect(await screen.findByText("Matching cards")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();

    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");

    expect(await screen.findByRole("heading", { name: "Lightning Angel" })).toBeInTheDocument();
    expect(screen.queryByText("Matching cards")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to matches" })).toBeInTheDocument();
  });

  it("scrolls matching-card navigation into view as keyboard selection moves", async () => {
    const user = userEvent.setup();
    const originalScrollIntoView = window.HTMLElement.prototype.scrollIntoView;
    const scrollIntoViewSpy = vi.fn();
    Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoViewSpy,
    });

    try {
      mockBaseSearchApp();
      vi.mocked(searchCardNames).mockImplementation(async (params) => {
        if (params.query === "lightn") {
          return buildNameSearchResult([
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
          ]);
        }
        return buildNameSearchResult();
      });

      render(<App />);

      const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
      await user.type(input, "lightn");
      await screen.findByRole("option", { name: /Lightning Angel/i });

      await user.keyboard("{ArrowUp}");
      await user.keyboard("{Enter}");

      await screen.findByText("Matching cards");
      scrollIntoViewSpy.mockClear();

      await user.keyboard("{ArrowDown}");

      expect(scrollIntoViewSpy).toHaveBeenCalled();
    } finally {
      Object.defineProperty(window.HTMLElement.prototype, "scrollIntoView", {
        configurable: true,
        value: originalScrollIntoView,
      });
    }
  });

  it("preserves backend ordering for name-search suggestions and grouped results", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "lightn") {
        return buildNameSearchResult([
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
        ]);
      }
      return buildNameSearchResult();
    });

    const { container } = render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
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

    await screen.findByRole("heading", { name: "Lightning Bolt" });
    expect(screen.getByText("Matching cards")).toBeInTheDocument();

    const resultNames = Array.from(
      container.querySelectorAll(".search-workspace-result-copy strong"),
    ).map((name) => name.textContent);

    expect(resultNames).toEqual([
      "Lightning Bolt",
      "Lightning Angel",
      "Lightning Axe",
      "Lightning Blast",
    ]);

    const blastResult = screen.getByText("Lightning Blast").closest("button");
    expect(blastResult).not.toBeNull();

    await user.click(blastResult!);

    expect(await screen.findByRole("heading", { name: "Lightning Blast" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Lightning Angel" })).not.toBeInTheDocument();
    expect(screen.queryByText("Matching cards")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Back to matches" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back to matches" }));

    expect(screen.getByText("Matching cards")).toBeInTheDocument();
  });

  it("loads more matching cards from the browse list in 10-card steps", async () => {
    const user = userEvent.setup();
    const rows = Array.from({ length: 21 }, (_, index) =>
      buildNameSearchRow({
        oracle_id: `cloud-${index + 1}`,
        name: `Cloud Result ${String(index + 1).padStart(2, "0")}`,
        printings_count: index + 1,
      }),
    );

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Cloud") {
        const limit = params.limit ?? rows.length;
        return buildNameSearchResult(rows.slice(0, limit), {
          total_count: rows.length,
          has_more: limit < rows.length,
        });
      }
      return buildNameSearchResult();
    });

    const { container } = render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Cloud");
    await screen.findByRole("option", { name: /Cloud Result 01/i });
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    await screen.findByRole("heading", { name: "Cloud Result 01" });
    expect(searchCardNames).toHaveBeenLastCalledWith({ query: "Cloud", limit: 18 });
    expect(screen.getByText("21 matching cards")).toBeInTheDocument();

    const visibleResultNames = () =>
      Array.from(container.querySelectorAll(".search-workspace-result-copy strong")).map(
        (name) => name.textContent,
      );

    expect(visibleResultNames()).toHaveLength(8);

    const initialCallCount = vi.mocked(searchCardNames).mock.calls.length;
    await user.click(
      screen.getByRole("button", { name: "Show 10 more of 13 additional matches" }),
    );

    expect(visibleResultNames()).toHaveLength(18);
    expect(vi.mocked(searchCardNames).mock.calls).toHaveLength(initialCallCount);

    await user.click(screen.getByRole("button", { name: "Load 3 more matches" }));

    await waitFor(() => {
      expect(searchCardNames).toHaveBeenLastCalledWith({ query: "Cloud", limit: 28 });
    });
    await waitFor(() => {
      expect(visibleResultNames()).toHaveLength(21);
    });
    expect(screen.queryByRole("button", { name: /more matches/i })).not.toBeInTheDocument();
  });

  it("ignores stale submitted search responses", async () => {
    const user = userEvent.setup();
    const cloudSearch = deferred<CatalogNameSearchResult>();
    const lightningSearch = deferred<CatalogNameSearchResult>();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Cloud" && params.limit === 18) {
        return cloudSearch.promise;
      }
      if (params.query === "Lightning" && params.limit === 18) {
        return lightningSearch.promise;
      }
      return buildNameSearchResult();
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Cloud");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    await user.clear(input);
    await user.type(input, "Lightning");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    lightningSearch.resolve(
      buildNameSearchResult([
        buildNameSearchRow({
          oracle_id: "lightning-bolt-oracle",
          name: "Lightning Bolt",
        }),
      ]),
    );

    expect(await screen.findByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();

    cloudSearch.resolve(
      buildNameSearchResult([
        buildNameSearchRow({
          oracle_id: "cloud-oracle",
          name: "Cloud Sprite",
        }),
      ]),
    );

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();
    });
    expect(screen.queryByRole("heading", { name: "Cloud Sprite" })).not.toBeInTheDocument();
  });

  it("keeps submitted results labeled while the search input is edited", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Cloud") {
        return buildNameSearchResult([
          buildNameSearchRow({
            oracle_id: "cloud-oracle",
            name: "Cloud Sprite",
          }),
        ]);
      }
      return buildNameSearchResult();
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Cloud");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    expect(await screen.findByRole("heading", { name: "Cloud Sprite" })).toBeInTheDocument();

    await user.type(input, "s");

    expect(screen.getByRole("heading", { name: "Cloud Sprite" })).toBeInTheDocument();
    expect(
      screen.getByText('Showing cards results for "Cloud". Search to update.'),
    ).toBeInTheDocument();
  });

  it("switches catalog scope and uses it for search and printing lookups", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Clue" && params.scope === "all") {
        return buildNameSearchResult([
          buildNameSearchRow({
            oracle_id: "clue-token-oracle",
            name: "Clue Token",
          }),
        ]);
      }
      if (params.query === "Clue") {
        return buildNameSearchResult([
          buildNameSearchRow({
            oracle_id: "clue-card-oracle",
            name: "Trail of Evidence",
          }),
        ]);
      }
      return buildNameSearchResult();
    });
    vi.mocked(getCardPrintingSummary).mockResolvedValue(
      buildPrintingSummary([
        buildSearchRow({
          scryfall_id: "clue-token",
          name: "Clue Token",
          is_default_add_choice: true,
        }),
      ]),
    );

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Clue");

    const scopeGroup = screen.getByRole("group", { name: "Catalog search scope" });
    await user.click(within(scopeGroup).getByRole("button", { name: "All catalog" }));

    expect(await screen.findByRole("heading", { name: "Clue Token" })).toBeInTheDocument();
    await waitFor(() => {
      expect(searchCardNames).toHaveBeenLastCalledWith({
        query: "Clue",
        limit: 18,
        scope: "all",
      });
    });
    await waitFor(() => {
      expect(getCardPrintingSummary).toHaveBeenCalledWith("clue-token-oracle", {
        scope: "all",
      });
    });

    await user.click(within(scopeGroup).getByRole("button", { name: "Cards" }));

    expect(await screen.findByRole("heading", { name: "Trail of Evidence" })).toBeInTheDocument();
    await waitFor(() => {
      expect(searchCardNames).toHaveBeenLastCalledWith({
        query: "Clue",
        limit: 18,
        scope: undefined,
      });
    });
  });

  it("keeps visible results and shows an inline retry path when loading more fails", async () => {
    const user = userEvent.setup();
    const rows = Array.from({ length: 21 }, (_, index) =>
      buildNameSearchRow({
        oracle_id: `cloud-${index + 1}`,
        name: `Cloud Result ${String(index + 1).padStart(2, "0")}`,
        printings_count: index + 1,
      }),
    );

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Cloud" && params.limit === 28) {
        throw new Error("Search index unavailable");
      }
      if (params.query === "Cloud") {
        const limit = params.limit ?? rows.length;
        return buildNameSearchResult(rows.slice(0, limit), {
          total_count: rows.length,
          has_more: limit < rows.length,
        });
      }
      return buildNameSearchResult();
    });

    const { container } = render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Cloud");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    await screen.findByRole("heading", { name: "Cloud Result 01" });
    await user.click(
      screen.getByRole("button", { name: "Show 10 more of 13 additional matches" }),
    );
    await user.click(screen.getByRole("button", { name: "Load 3 more matches" }));

    await screen.findByText("Search index unavailable");

    const visibleResultNames = Array.from(
      container.querySelectorAll(".search-workspace-result-copy strong"),
    ).map((name) => name.textContent);
    expect(visibleResultNames).toHaveLength(18);
    expect(screen.getByRole("button", { name: "Load 3 more matches" })).toBeEnabled();
    expect(screen.queryByText("Search unavailable")).not.toBeInTheDocument();
  });

  it("keeps printing unselected while still using the backend default printing choice on add", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Lightning") {
        return buildNameSearchResult([
          buildNameSearchRow({
            oracle_id: "bolt-oracle",
            name: "Lightning Bolt",
            printings_count: 2,
            available_languages: ["en"],
          }),
        ]);
      }
      return buildNameSearchResult();
    });
    vi.mocked(getCardPrintingSummary).mockResolvedValue(
      buildPrintingSummary([
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
          is_default_add_choice: true,
        }),
      ]),
    );
    vi.mocked(addInventoryItem).mockResolvedValue({ card_name: "Lightning Bolt" } as any);

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Lightning");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    const boltCard = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltCard).not.toBeNull();

    const printingSelect = within(boltCard!).getByRole("combobox", { name: "Printing" });
    const finishSelect = within(boltCard!).getByRole("combobox", { name: "Finish" });

    await waitFor(() => {
      expect(getCardPrintingSummary).toHaveBeenCalledWith("bolt-oracle");
    });
    await waitFor(() => {
      expect(printingSelect).toHaveValue("");
    });
    expect(listCardPrintings).not.toHaveBeenCalledWith("bolt-oracle", { lang: "all" });

    expect(
      within(printingSelect).getByRole("option", {
        name: /MAGIC 2011 .* Default choice/i,
      }),
    ).toBeInTheDocument();
    expect(
      within(boltCard!).getByText(/Ready to add with the default printing/i),
    ).toBeInTheDocument();
    expect(finishSelect).toBeEnabled();
    const addButton = within(boltCard!).getByRole("button", { name: "Add to collection" });
    expect(addButton).toBeEnabled();

    await user.click(addButton);

    await waitFor(() => {
      expect(addInventoryItem).toHaveBeenCalledWith(
        "personal",
        expect.objectContaining({
          scryfall_id: "bolt-m11",
          quantity: 1,
          finish: "normal",
        }),
      );
    });
  });

  it("uses collection default location and tags when quick add details are blank", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(listInventories).mockResolvedValue([
      buildInventorySummary({
        default_location: "Trade Binder",
        default_tags: "trade, staples",
      }),
    ]);
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Lightning") {
        return buildNameSearchResult([
          buildNameSearchRow({
            oracle_id: "bolt-oracle",
            name: "Lightning Bolt",
            printings_count: 2,
            available_languages: ["en"],
          }),
        ]);
      }
      return buildNameSearchResult();
    });
    vi.mocked(getCardPrintingSummary).mockResolvedValue(
      buildPrintingSummary([
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
          is_default_add_choice: true,
        }),
      ]),
    );
    vi.mocked(addInventoryItem).mockResolvedValue({ card_name: "Lightning Bolt" } as any);

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Lightning");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    const boltCard = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest(
      "article",
    );
    expect(boltCard).not.toBeNull();
    expect(within(boltCard!).getByText("Location: Trade Binder · 2 tags")).toBeInTheDocument();

    await user.click(within(boltCard!).getByRole("button", { name: "Add to collection" }));

    await waitFor(() => {
      expect(addInventoryItem).toHaveBeenCalledWith(
        "personal",
        expect.objectContaining({
          scryfall_id: "bolt-m11",
          location: "Trade Binder",
          tags: ["trade", "staples"],
        }),
      );
    });
  });

  it("groups name-first search results and clears the quick-add workspace after a successful add", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Lightning") {
        return buildNameSearchResult([
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
        ]);
      }
      return buildNameSearchResult();
    });
    vi.mocked(getCardPrintingSummary).mockImplementation(async (oracleId) => {
      if (oracleId === "bolt-oracle") {
        return buildPrintingSummary([
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
        ]);
      }
      return buildPrintingSummary([], { oracle_id: oracleId });
    });
    vi.mocked(listCardPrintings).mockImplementation(async (oracleId, params) => {
      if (oracleId === "bolt-oracle" && params?.lang === "all") {
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

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Lightning");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    const boltCard = (await screen.findByRole("heading", { name: "Lightning Bolt" })).closest("article");
    expect(boltCard).not.toBeNull();
    expect(screen.getAllByRole("heading", { name: "Lightning Bolt" })).toHaveLength(1);
    expect(screen.getByText("Lightning Blast")).toBeInTheDocument();

    const printingSelect = within(boltCard!).getByRole("combobox", { name: "Printing" });
    const finishSelect = within(boltCard!).getByRole("combobox", { name: "Finish" });

    expect(finishSelect).toBeDisabled();

    await waitFor(() => {
      expect(getCardPrintingSummary).toHaveBeenCalledWith("bolt-oracle");
    });
    expect(listCardPrintings).not.toHaveBeenCalledWith("bolt-oracle", { lang: "all" });

    expect(
      within(boltCard!).getByRole("button", { name: "Select printing first" }),
    ).toBeDisabled();
    expect(
      within(printingSelect).getByRole("option", { name: "3 printings available" }),
    ).toBeInTheDocument();

    expect(
      within(boltCard!).getByRole("button", { name: "Load all languages" }),
    ).toBeInTheDocument();
    expect(
      within(printingSelect).queryByRole("option", { name: /STRIXHAVEN MYSTICAL ARCHIVE/i }),
    ).not.toBeInTheDocument();

    await user.click(
      within(boltCard!).getByRole("button", { name: "Load all languages" }),
    );

    await waitFor(() => {
      expect(listCardPrintings).toHaveBeenCalledWith("bolt-oracle", { lang: "all" });
    });

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
    expect(screen.queryByText("Run a search")).not.toBeInTheDocument();
  });

  it("closes autocomplete on escape and outside click", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Fo") {
        return buildNameSearchResult([
          buildNameSearchRow({
            oracle_id: "forest-oracle",
            name: "Forest",
            printings_count: 1,
          }),
        ]);
      }
      return buildNameSearchResult();
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
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

  it("keeps the add-card pane open on outside click and closes it from the explicit close button", async () => {
    const user = userEvent.setup();

    mockBaseSearchApp();
    vi.mocked(searchCardNames).mockImplementation(async (params) => {
      if (params.query === "Lightning") {
        return buildNameSearchResult([
          buildNameSearchRow({
            oracle_id: "bolt-oracle",
            name: "Lightning Bolt",
            printings_count: 3,
          }),
        ]);
      }
      return buildNameSearchResult();
    });

    render(<App />);

    const input = await screen.findByRole("combobox", { name: "Quick Add and Card Search" });
    await user.type(input, "Lightning");
    await user.click(screen.getByRole("button", { name: "Search cards" }));

    expect(await screen.findByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();
    expect(input).toHaveValue("Lightning");
    expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();

    await user.click(input);

    expect(await screen.findByRole("listbox", { name: "Card suggestions" })).toBeInTheDocument();

    await user.click(document.body);

    await waitFor(() => {
      expect(screen.queryByRole("listbox", { name: "Card suggestions" })).not.toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();
    expect(input).toHaveValue("Lightning");

    await user.click(screen.getByRole("button", { name: "Close add card pane" }));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Lightning Bolt" })).not.toBeInTheDocument();
    });
    expect(input).toHaveValue("Lightning");
  });

  it("defaults to browse collection view, toggles table mode, and opens details without refetching", async () => {
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
    expect(screen.queryByRole("button", { name: "Detailed" })).not.toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Table" }));

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute("aria-pressed", "false");
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "true");
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Browse" }));

    await screen.findByRole("heading", { name: "Lightning Bolt" });
    expect(screen.queryByText("Inline edits")).not.toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    const counterspellRow = (await screen.findByRole("heading", { name: "Counterspell" })).closest(
      "article",
    );
    expect(counterspellRow).not.toBeNull();

    await user.click(within(counterspellRow!).getByRole("button", { name: "Open details" }));

    const dialog = await screen.findByRole("dialog", { name: "Card details" });
    expect(within(dialog).getByText("Inline edits")).toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);
  });

  it("caps browse and table entries by default and supports pagination in each view", async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 60 }, (_, index) =>
      buildOwnedRow({
        item_id: index + 1,
        scryfall_id: `card-${index + 1}`,
        oracle_id: `oracle-${index + 1}`,
        name: `Card ${String(index + 1).padStart(3, "0")}`,
        set_code: "m11",
        set_name: "Magic 2011",
        collector_number: String(index + 1),
        quantity: 1,
        location: index % 2 === 0 ? "Binder" : "Box",
        tags: [],
        notes: null,
        est_value: "1.00",
        unit_price: "1.00",
      }),
    );

    mockCollectionViewApp({ items });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Card 001" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Card 025" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Card 026" })).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByRole("heading", { name: "Card 026" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Card 050" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Card 025" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Card 051" })).not.toBeInTheDocument();
    expect(screen.getByText("Page 2 of 3")).toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Browse entries shown" }),
      "50",
    );

    expect(await screen.findByRole("heading", { name: "Card 050" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Card 051" })).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Table" }));

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(51);
    expect(within(table).queryByText("Card 051")).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next" }));

    expect(within(await screen.findByRole("table")).getAllByRole("row")).toHaveLength(11);
    expect(screen.getByText("Card 051")).toBeInTheDocument();
    expect(screen.getByText("Card 060")).toBeInTheDocument();
    expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Table rows shown" }),
      "100",
    );

    expect(within(await screen.findByRole("table")).getAllByRole("row")).toHaveLength(61);
    expect(screen.getByText("Card 060")).toBeInTheDocument();
    expect(screen.getByText("Page 1 of 1")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Detailed" })).not.toBeInTheDocument();
  });

  it("saves browse edits directly when a field blurs", async () => {
    const user = userEvent.setup();

    const initialBolt = buildOwnedRow();
    const updatedBolt = buildOwnedRow({ quantity: 5, est_value: "10.00" });

    vi.mocked(listInventories).mockResolvedValue([
      buildInventorySummary({
        item_rows: 1,
        total_cards: 5,
      }),
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
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
      oracle_id: "bolt-oracle",
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
      printing_selection_mode: "explicit",
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
      buildInventorySummary({
        item_rows: 1,
        total_cards: 2,
      }),
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
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
      oracle_id: "bolt-oracle",
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
      printing_selection_mode: "explicit",
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
      buildInventorySummary({
        item_rows: 1,
        total_cards: 2,
      }),
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
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
      oracle_id: "bolt-oracle",
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
      printing_selection_mode: "explicit",
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
      buildInventorySummary({
        item_rows: 1,
        total_cards: 2,
      }),
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
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
      oracle_id: "bolt-oracle",
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
      printing_selection_mode: "explicit",
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
      buildInventorySummary({
        item_rows: 1,
        total_cards: 2,
      }),
    ]);
    vi.mocked(listInventoryItems)
      .mockResolvedValueOnce([initialBolt])
      .mockResolvedValueOnce([updatedBolt]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
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
      oracle_id: "bolt-oracle",
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
      printing_selection_mode: "explicit",
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

  it("opens the matching row in a detail dialog from browse mode", async () => {
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

    const dialog = await screen.findByRole("dialog", { name: "Card details" });
    expect(screen.getByRole("button", { name: "Browse" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.queryByRole("button", { name: "Detailed" })).not.toBeInTheDocument();

    expect(within(dialog).getByRole("heading", { name: "Counterspell" })).toBeInTheDocument();
    expect(within(dialog).getByText("Inline edits")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Close dialog" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Card details" })).not.toBeInTheDocument();
    });
  });

  it("filters the current collection from a small in-pane search field", async () => {
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

    const collectionSearch = await screen.findByRole("textbox", {
      name: "Search this collection",
    });
    expect(await screen.findByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Counterspell" })).toBeInTheDocument();

    await user.type(collectionSearch, "Counter");

    expect(screen.queryByRole("heading", { name: "Lightning Bolt" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Counterspell" })).toBeInTheDocument();

    await user.clear(collectionSearch);

    expect(screen.getByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Counterspell" })).toBeInTheDocument();
  });

  it("opens and closes the activity drawer while keeping activity off the main page by default", async () => {
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

    await screen.findByRole("button", { name: "Recent Activity" });
    expect(screen.queryByRole("heading", { name: "Activity" })).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Collection Activity" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Recent Activity" }));
    expect(await screen.findByRole("dialog", { name: "Collection Activity" })).toBeInTheDocument();
    expect(screen.getByText("Set Finish")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close activity drawer" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Collection Activity" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Recent Activity" }));
    expect(await screen.findByRole("dialog", { name: "Collection Activity" })).toBeInTheDocument();

    await user.click(screen.getByTestId("activity-drawer-backdrop"));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Collection Activity" })).not.toBeInTheDocument();
    });

    await user.click(screen.getByRole("button", { name: "Recent Activity" }));
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

    const openButton = await screen.findByRole("button", { name: "Recent Activity" });
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

  it("supports table view row selection without refetching and preserves selection across browse/table changes", async () => {
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
    const lightningBoltRow = within(table)
      .getAllByRole("row")
      .find((row) => row.textContent?.includes("Lightning Bolt"));

    expect(lightningBoltRow).toBeDefined();
    expect(await screen.findByRole("checkbox", { name: "Select Lightning Bolt" })).toBeInTheDocument();
    expect(screen.getByText("No entries selected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Bulk edit" })).not.toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(lightningBoltRow!);

    expect(screen.getByText("1 entry selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Bulk edit" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Browse" }));
    expect(screen.queryByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeInTheDocument();
    expect(listInventoryItems).toHaveBeenCalledTimes(1);
    expect(listInventoryAudit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Table" }));
    expect(await screen.findByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByText("1 entry selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    expect(screen.getByText("2 entries selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByText("No entries selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).not.toBeChecked();
  });

  it("supports row-click range and additive selection in the table view", async () => {
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
        buildOwnedRow({
          item_id: 9,
          scryfall_id: "sol-ring-1",
          name: "Sol Ring",
          set_code: "cmm",
          set_name: "Commander Masters",
          collector_number: "396",
          quantity: 1,
          location: "Trade Tray",
          tags: ["artifact"],
          est_value: "1.50",
          unit_price: "1.50",
          notes: null,
        }),
      ],
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));

    const table = screen.getByRole("table");
    const getRow = (cardName: string) =>
      within(table)
        .getAllByRole("row")
        .find((row) => row.textContent?.includes(cardName));

    const lightningBoltRow = getRow("Lightning Bolt");
    const counterspellRow = getRow("Counterspell");
    const solRingRow = getRow("Sol Ring");

    expect(lightningBoltRow).toBeDefined();
    expect(counterspellRow).toBeDefined();
    expect(solRingRow).toBeDefined();

    await user.click(lightningBoltRow!);
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByText("1 entry selected")).toBeInTheDocument();

    await user.keyboard("{Shift>}");
    await user.click(solRingRow!);
    await user.keyboard("{/Shift}");

    expect(screen.getByText("3 entries selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Sol Ring" })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(screen.getByText("No entries selected")).toBeInTheDocument();

    await user.click(lightningBoltRow!);
    await user.keyboard("{Control>}");
    await user.click(solRingRow!);
    await user.keyboard("{/Control}");

    expect(screen.getByText("2 entries selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Sol Ring" })).toBeChecked();
  });

  it("can select the entire collection from the table even when not all rows are visible", async () => {
    const user = userEvent.setup();
    const items = Array.from({ length: 60 }, (_, index) =>
      buildOwnedRow({
        item_id: index + 1,
        scryfall_id: `card-${index + 1}`,
        oracle_id: `oracle-${index + 1}`,
        name: `Card ${String(index + 1).padStart(3, "0")}`,
        set_code: "m11",
        set_name: "Magic 2011",
        collector_number: String(index + 1),
        quantity: 1,
        location: index % 2 === 0 ? "Binder" : "Box",
        tags: [],
        notes: null,
        est_value: "1.00",
        unit_price: "1.00",
      }),
    );

    mockCollectionViewApp({ items });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Select entire collection" }));

    expect(screen.getByText("60 entries selected")).toBeInTheDocument();
    expect(screen.getByText("10 selected entries not shown in the current view.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Card 001" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Card 050" })).toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Select Card 051" })).not.toBeInTheDocument();
  });

  it("copies selected table entries into an existing collection", async () => {
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
      inventories: [
        buildInventorySummary({
          item_rows: 2,
          total_cards: 3,
        }),
        buildInventorySummary({
          slug: "trade",
          display_name: "Trade Binder",
          description: "Cards available for swaps",
          item_rows: 4,
          total_cards: 6,
        }),
      ],
    });
    vi.mocked(transferInventoryItems).mockResolvedValue({
      source_inventory: "personal",
      target_inventory: "trade",
      mode: "copy",
      dry_run: false,
      selection_kind: "items",
      requested_item_ids: [7, 8],
      requested_count: 2,
      copied_count: 2,
      moved_count: 0,
      merged_count: 0,
      failed_count: 0,
      results_returned: 2,
      results_truncated: false,
      results: [],
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    await user.click(screen.getByRole("button", { name: "Copy to collection" }));

    const tray = screen.getByRole("region", { name: "Copy to collection tray" });
    await user.click(within(tray).getByRole("button", { name: "Copy to collection" }));

    await waitFor(() => {
      expect(transferInventoryItems).toHaveBeenCalledWith("personal", {
        target_inventory_slug: "trade",
        mode: "copy",
        all_items: true,
        on_conflict: "merge",
        keep_acquisition: "source",
      });
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Copied 2 entries to Trade Binder.",
    );
  });

  it("creates a new collection during a move transfer and sends the whole collection when selected", async () => {
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
    vi.mocked(createInventory).mockResolvedValue({
      inventory_id: 9,
      slug: "archive-box",
      display_name: "Archive Box",
      description: "Long-term storage",
      default_location: "Closet Shelf",
      default_tags: "archive, cube",
      notes: null,
      acquisition_price: null,
      acquisition_currency: null,
    });
    vi.mocked(transferInventoryItems).mockResolvedValue({
      source_inventory: "personal",
      target_inventory: "archive-box",
      mode: "move",
      dry_run: false,
      selection_kind: "all_items",
      requested_item_ids: null,
      requested_count: 2,
      copied_count: 0,
      moved_count: 2,
      merged_count: 0,
      failed_count: 0,
      results_returned: 2,
      results_truncated: false,
      results: [],
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    await user.click(screen.getByRole("button", { name: "Move to collection" }));

    const tray = screen.getByRole("region", { name: "Move to collection tray" });
    await user.type(within(tray).getByRole("textbox", { name: "Collection name" }), "Archive Box");
    await user.type(
      within(tray).getByRole("textbox", { name: "Description (optional)" }),
      "Long-term storage",
    );
    await user.type(
      within(tray).getByRole("textbox", { name: /Default location/i }),
      "Closet Shelf",
    );
    await user.type(
      within(tray).getByRole("textbox", { name: /Default tags/i }),
      "Archive, Cube",
    );
    await user.click(within(tray).getByRole("button", { name: "Create and move" }));

    await waitFor(() => {
      expect(createInventory).toHaveBeenCalledWith({
        display_name: "Archive Box",
        slug: "archive-box",
        description: "Long-term storage",
        default_location: "Closet Shelf",
        default_tags: "archive, cube",
      });
    });

    await waitFor(() => {
      expect(transferInventoryItems).toHaveBeenCalledWith("personal", {
        target_inventory_slug: "archive-box",
        mode: "move",
        all_items: true,
        on_conflict: "merge",
        keep_acquisition: "source",
      });
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Moved 2 entries to Archive Box.",
    );
  });

  it("opens collection entry details from the table card action", async () => {
    const user = userEvent.setup();

    mockCollectionViewApp({
      items: [buildOwnedRow()],
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Open Lightning Bolt details" }));

    const dialog = await screen.findByRole("dialog", { name: "Card details" });
    expect(within(dialog).getByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();
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
    expect(screen.getByText("1 entry selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Set" }));
    await user.click(screen.getByLabelText("LEA · Limited Edition Alpha"));

    expect(screen.getByText("Showing all 1 entry.")).toBeInTheDocument();
    expect(screen.getByText("1 selected entry not shown in the current view.")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: "Select Counterspell" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeChecked();

    await user.click(screen.getByRole("button", { name: "Select all visible" }));

    expect(screen.getByText("2 entries selected")).toBeInTheDocument();
    expect(screen.getByText("1 selected entry not shown in the current view.")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(screen.getByText("Showing all 2 entries.")).toBeInTheDocument();
    expect(screen.queryByText("1 selected entry not shown in the current view.")).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).toBeChecked();
  });

  it("applies bulk tag actions to selected table entries and clears the selection after success", async () => {
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
    expect(screen.queryByRole("textbox", { name: "Tag list" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    await user.click(screen.getByRole("button", { name: "Bulk edit" }));

    expect(screen.getByText("2 entries selected")).toBeInTheDocument();

    await user.type(screen.getByRole("textbox", { name: "Tag list" }), "burn, staples");
    await user.click(screen.getByRole("button", { name: "Add tags" }));

    await waitFor(() => {
      expect(bulkMutateInventoryItems).toHaveBeenCalledWith("personal", {
        operation: "add_tags",
        item_ids: [7, 8],
        tags: ["burn", "staples"],
      });
    });

    await waitFor(() => {
      expect(screen.getByText("No entries selected")).toBeInTheDocument();
    });
    expect(screen.getByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select Counterspell" })).not.toBeChecked();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Added tags to 2 entries in Personal Collection.",
    );
    expect(listInventoryItems).toHaveBeenCalledTimes(2);
    expect(listInventoryAudit).toHaveBeenCalledTimes(2);
  });

  it("applies bulk location updates from the bulk edit tray", async () => {
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
      operation: "set_location",
      requested_item_ids: [7, 8],
      updated_item_ids: [7, 8],
      updated_count: 2,
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    await user.click(screen.getByRole("button", { name: "Bulk edit" }));

    const tray = screen.getByRole("region", { name: "Bulk edit tray" });
    await user.click(within(tray).getByRole("button", { name: "Location" }));
    await user.type(within(tray).getByRole("textbox", { name: "Location" }), "Archive Box");
    await user.click(within(tray).getByRole("button", { name: "Set location" }));

    await waitFor(() => {
      expect(bulkMutateInventoryItems).toHaveBeenCalledWith("personal", {
        operation: "set_location",
        item_ids: [7, 8],
        location: "Archive Box",
      });
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Updated location on 2 entries in Personal Collection.",
    );
  });

  it("replaces notes from the bulk edit tray", async () => {
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
      operation: "set_notes",
      requested_item_ids: [7, 8],
      updated_item_ids: [7, 8],
      updated_count: 2,
    });

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(screen.getByRole("button", { name: "Select all visible" }));
    await user.click(screen.getByRole("button", { name: "Bulk edit" }));

    const tray = screen.getByRole("region", { name: "Bulk edit tray" });
    await user.click(within(tray).getByRole("button", { name: "Notes" }));
    await user.type(
      within(tray).getByRole("textbox", { name: "Notes" }),
      "Updated deck notes",
    );
    await user.click(within(tray).getByRole("button", { name: "Replace notes" }));

    await waitFor(() => {
      expect(bulkMutateInventoryItems).toHaveBeenCalledWith("personal", {
        operation: "set_notes",
        item_ids: [7, 8],
        notes: "Updated deck notes",
      });
    });

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Updated notes on 2 entries in Personal Collection.",
    );
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
    await user.click(screen.getByRole("button", { name: "Bulk edit" }));
    await user.type(screen.getByRole("textbox", { name: "Tag list" }), "burn, staples");
    await user.click(screen.getByRole("button", { name: "Clear tags" }));

    await waitFor(() => {
      expect(bulkMutateInventoryItems).toHaveBeenCalledWith("personal", {
        operation: "clear_tags",
        item_ids: [7, 8],
      });
    });

    expect(screen.queryByRole("textbox", { name: "Tag list" })).not.toBeInTheDocument();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Cleared tags from 2 entries in Personal Collection.",
    );
  });

  it("clears table selection when the selected inventory changes", async () => {
    const user = userEvent.setup();

    vi.mocked(listInventories).mockResolvedValue([
      buildInventorySummary({
        item_rows: 2,
        total_cards: 3,
      }),
      buildInventorySummary({
        slug: "trade-binder",
        display_name: "Trade Binder",
        description: "Cards available to trade",
        item_rows: 1,
        total_cards: 1,
      }),
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
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);

    render(<App />);

    await user.click(await screen.findByRole("button", { name: "Table" }));
    await user.click(await screen.findByRole("checkbox", { name: "Select Lightning Bolt" }));
    expect(screen.getByText("1 entry selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Personal Collection/i }));
    await user.click(screen.getByRole("button", { name: /Trade Binder/i }));

    expect(await screen.findByText("No entries selected")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Select Sol Ring" })).not.toBeChecked();
    expect(screen.queryByRole("checkbox", { name: "Select Lightning Bolt" })).not.toBeInTheDocument();
  });

  it("creates a new inventory from the sidebar and selects it", async () => {
    const user = userEvent.setup();

    vi.mocked(listInventories)
      .mockResolvedValueOnce([
        buildInventorySummary(),
      ])
      .mockResolvedValueOnce([
        buildInventorySummary(),
        buildInventorySummary({
          slug: "trade-binder",
          display_name: "Trade Binder",
          description: "Cards available to trade",
        }),
      ]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
    vi.mocked(listCardPrintings).mockResolvedValue([]);
    vi.mocked(createInventory).mockResolvedValue(
      buildInventoryCreateResponse({
        inventory_id: 42,
        slug: "trade-binder",
        display_name: "Trade Binder",
        description: "Cards available to trade",
      }),
    );

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
    await user.type(
      within(dialog).getByRole("textbox", { name: /Default location/i }),
      "Trade Binder",
    );
    await user.type(
      within(dialog).getByRole("textbox", { name: /Default tags/i }),
      "Trade, Staples",
    );
    await user.click(within(dialog).getByRole("button", { name: "Create Collection" }));

    await waitFor(() => {
      expect(createInventory).toHaveBeenCalledWith({
        slug: "trade-binder",
        display_name: "Trade Binder",
        description: "Cards available to trade",
        default_location: "Trade Binder",
        default_tags: "trade, staples",
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
      buildInventorySummary(),
    ]);
    vi.mocked(listInventoryItems).mockResolvedValue([]);
    vi.mocked(listInventoryAudit).mockResolvedValue([]);
    vi.mocked(searchCardNames).mockResolvedValue(buildNameSearchResult());
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
