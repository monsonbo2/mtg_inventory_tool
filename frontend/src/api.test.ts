import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  bootstrapDefaultInventory,
  createInventory,
  duplicateInventory,
  exportInventoryCsv,
  getAccessSummary,
  importCsv,
  importDeckUrl,
  importDecklist,
  requestFormData,
  requestJson,
  requestText,
  searchCards,
  transferInventoryItems,
} from "./api";

describe("api transport", () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.fetch = originalFetch;
  });

  it("sends JSON requests with the expected headers", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          inventory_id: 5,
          slug: "personal",
          display_name: "Personal",
          description: null,
          default_location: null,
          default_tags: null,
          notes: null,
          acquisition_price: null,
          acquisition_currency: null,
        }),
        {
          headers: {
            "Content-Type": "application/json",
          },
          status: 200,
        },
      ),
    );

    await createInventory({
      display_name: "Personal",
      slug: "personal",
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = new Headers(init?.headers);

    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("content-type")).toBe("application/json");
    expect(init?.body).toBe(
      JSON.stringify({
        display_name: "Personal",
        slug: "personal",
      }),
    );
  });

  it("sends multipart requests without forcing a JSON content type", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: {
          "Content-Type": "application/json",
        },
        status: 200,
      }),
    );

    const formData = new FormData();
    formData.set("file", new Blob(["name,qty\nBolt,4"], { type: "text/csv" }), "cards.csv");
    formData.set("dry_run", "true");

    await requestFormData<{ ok: boolean }>("/imports/csv", {
      formData,
      method: "POST",
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const headers = new Headers(init?.headers);

    expect(headers.get("accept")).toBe("application/json");
    expect(headers.get("content-type")).toBeNull();
    expect(init?.body).toBe(formData);
  });

  it("returns text responses with filename metadata for download-style routes", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("name,quantity\nLightning Bolt,4\n", {
        headers: {
          "Content-Disposition": 'attachment; filename="inventory-export.csv"',
          "Content-Type": "text/csv; charset=utf-8",
        },
        status: 200,
      }),
    );

    const response = await requestText("/inventories/personal/export.csv", {
      accept: "text/csv",
    });

    expect(response.body).toBe("name,quantity\nLightning Bolt,4\n");
    expect(response.contentType).toBe("text/csv; charset=utf-8");
    expect(response.filename).toBe("inventory-export.csv");
  });

  it("decodes UTF-8 filenames from content-disposition metadata", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("name,quantity\nCounterspell,2\n", {
        headers: {
          "Content-Disposition":
            "attachment; filename*=UTF-8''deck%20%C3%BCber.csv",
          "Content-Type": "text/csv",
        },
        status: 200,
      }),
    );

    const response = await requestText("/inventories/personal/export.csv");

    expect(response.filename).toBe("deck \u00fcber.csv");
  });

  it("surfaces structured JSON API errors with details", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "validation_error",
            details: {
              resolution_issues: [{ csv_row: 2 }],
            },
            message: "Import needs explicit resolutions before commit.",
          },
        }),
        {
          headers: {
            "Content-Type": "application/json",
          },
          status: 400,
          statusText: "Bad Request",
        },
      ),
    );

    await expect(
      requestFormData("/imports/csv", {
        formData: new FormData(),
        method: "POST",
      }),
    ).rejects.toMatchObject({
      code: "validation_error",
      details: {
        resolution_issues: [{ csv_row: 2 }],
      },
      message: "Import needs explicit resolutions before commit.",
      status: 400,
    });
  });

  it("falls back to plain-text error bodies when no JSON envelope is available", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("Upstream proxy denied the request.", {
        headers: {
          "Content-Type": "text/plain",
        },
        status: 502,
        statusText: "Bad Gateway",
      }),
    );

    await expect(requestText("/inventories/personal/export.csv")).rejects.toMatchObject({
      code: "http_error",
      message: "Upstream proxy denied the request.",
      status: 502,
    });
  });

  it("parses JSON error envelopes even when the content type is not JSON", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          error: {
            code: "conflict",
            details: {
              conflicting_item_ids: [1, 2],
            },
            message: "Transfer would collide with existing rows.",
          },
        }),
        {
          headers: {
            "Content-Type": "text/plain",
          },
          status: 409,
        },
      ),
    );

    await expect(
      transferInventoryItems("personal", {
        item_ids: [1, 2],
        mode: "move",
        on_conflict: "fail",
        target_inventory_slug: "trades",
      }),
    ).rejects.toMatchObject({
      code: "conflict",
      details: {
        conflicting_item_ids: [1, 2],
      },
      message: "Transfer would collide with existing rows.",
      status: 409,
    });
  });

  it("falls back to a generic message for empty error responses", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("", {
        status: 503,
        statusText: "Service Unavailable",
      }),
    );

    await expect(requestJson("/health")).rejects.toMatchObject({
      code: "http_error",
      message: "The API request failed.",
      status: 503,
    });
  });

  it("gets the shared-service access summary from the expected endpoint", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          can_bootstrap: true,
          has_readable_inventory: false,
          visible_inventory_count: 0,
          default_inventory_slug: null,
        }),
        {
          headers: {
            "Content-Type": "application/json",
          },
          status: 200,
        },
      ),
    );

    const response = await getAccessSummary();

    expect(response).toEqual({
      can_bootstrap: true,
      has_readable_inventory: false,
      visible_inventory_count: 0,
      default_inventory_slug: null,
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toContain("/api/me/access-summary");
    expect(init?.method).toBeUndefined();
    expect(init?.body).toBeUndefined();
  });

  it("posts the new JSON wrapper routes to the expected endpoints", async () => {
    vi.mocked(fetch).mockImplementation(
      async () =>
        new Response(JSON.stringify({ ok: true }), {
          headers: {
            "Content-Type": "application/json",
          },
          status: 200,
        }),
    );

    const decklistPayload = {
      deck_text: "4 Lightning Bolt",
      default_inventory: "personal",
      dry_run: true,
    } as const;
    const deckUrlPayload = {
      source_url: "https://www.moxfield.com/decks/demo",
      default_inventory: "personal",
    } as const;
    const duplicatePayload = {
      target_display_name: "Personal Copy",
      target_slug: "personal-copy",
    } as const;
    const transferPayload = {
      item_ids: [1, 2] as number[],
      mode: "copy",
      on_conflict: "fail",
      target_inventory_slug: "trades",
    } as const;

    await bootstrapDefaultInventory();
    await importDecklist(decklistPayload);
    await importDeckUrl(deckUrlPayload);
    await duplicateInventory("personal", duplicatePayload);
    await transferInventoryItems("personal", transferPayload);

    expect(fetch).toHaveBeenCalledTimes(5);

    const bootstrapCall = vi.mocked(fetch).mock.calls[0];
    expect(String(bootstrapCall[0])).toContain("/api/me/bootstrap");
    expect(bootstrapCall[1]?.method).toBe("POST");
    expect(bootstrapCall[1]?.body).toBeUndefined();

    const decklistCall = vi.mocked(fetch).mock.calls[1];
    expect(String(decklistCall[0])).toContain("/api/imports/decklist");
    expect(decklistCall[1]?.method).toBe("POST");
    expect(JSON.parse(String(decklistCall[1]?.body))).toEqual(decklistPayload);

    const deckUrlCall = vi.mocked(fetch).mock.calls[2];
    expect(String(deckUrlCall[0])).toContain("/api/imports/deck-url");
    expect(deckUrlCall[1]?.method).toBe("POST");
    expect(JSON.parse(String(deckUrlCall[1]?.body))).toEqual(deckUrlPayload);

    const duplicateCall = vi.mocked(fetch).mock.calls[3];
    expect(String(duplicateCall[0])).toContain(
      "/api/inventories/personal/duplicate",
    );
    expect(duplicateCall[1]?.method).toBe("POST");
    expect(JSON.parse(String(duplicateCall[1]?.body))).toEqual(duplicatePayload);

    const transferCall = vi.mocked(fetch).mock.calls[4];
    expect(String(transferCall[0])).toContain(
      "/api/inventories/personal/transfer",
    );
    expect(transferCall[1]?.method).toBe("POST");
    expect(JSON.parse(String(transferCall[1]?.body))).toEqual(transferPayload);
  });

  it("builds CSV import requests with the backend's multipart field names", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: {
          "Content-Type": "application/json",
        },
        status: 200,
      }),
    );

    await importCsv({
      default_inventory: "personal",
      dry_run: true,
      file: new Blob(["name,qty\nBolt,4"], { type: "text/csv" }),
      resolutions: [
        {
          csv_row: 2,
          finish: "foil",
          scryfall_id: "abc123",
        },
      ],
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    const formData = init?.body as FormData;

    expect(String(url)).toContain("/api/imports/csv");
    expect(init?.method).toBe("POST");
    expect(formData.get("file")).toBeInstanceOf(Blob);
    expect(formData.get("default_inventory")).toBe("personal");
    expect(formData.get("dry_run")).toBe("true");
    expect(formData.get("resolutions_json")).toBe(
      JSON.stringify([
        {
          csv_row: 2,
          finish: "foil",
          scryfall_id: "abc123",
        },
      ]),
    );
  });

  it("preserves explicit CSV filenames and omits absent multipart fields", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), {
        headers: {
          "Content-Type": "application/json",
        },
        status: 200,
      }),
    );

    await importCsv({
      dry_run: false,
      file: new File(["name,qty\nCounterspell,2"], "cube-upload.csv", {
        type: "text/csv",
      }),
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [, init] = vi.mocked(fetch).mock.calls[0];
    const formData = init?.body as FormData;
    const file = formData.get("file");

    expect(file).toBeInstanceOf(File);
    expect((file as File).name).toBe("cube-upload.csv");
    expect(formData.get("dry_run")).toBe("false");
    expect(formData.get("default_inventory")).toBeNull();
    expect(formData.get("resolutions_json")).toBeNull();
  });

  it("serializes CSV export filters as query parameters", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response("name,quantity\nLightning Bolt,4\n", {
        headers: {
          "Content-Type": "text/csv; charset=utf-8",
        },
        status: 200,
      }),
    );

    await exportInventoryCsv("personal", {
      finish: "foil",
      language_code: "en",
      profile: "default",
      query: "Lightning Bolt",
      tags: ["burn", "trade"],
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url] = vi.mocked(fetch).mock.calls[0];
    const requestUrl = new URL(String(url));

    expect(requestUrl.pathname).toBe("/api/inventories/personal/export.csv");
    expect(requestUrl.searchParams.get("query")).toBe("Lightning Bolt");
    expect(requestUrl.searchParams.get("profile")).toBe("default");
    expect(requestUrl.searchParams.get("finish")).toBe("foil");
    expect(requestUrl.searchParams.get("language_code")).toBe("en");
    expect(requestUrl.searchParams.getAll("tags")).toEqual(["burn", "trade"]);
  });

  it("serializes search params with explicit false booleans and omits blank filters", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify([]), {
        headers: {
          "Content-Type": "application/json",
        },
        status: 200,
      }),
    );

    await searchCards({
      exact: false,
      limit: 25,
      query: "Lightning Bolt",
      scope: "all",
      set_code: "",
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url] = vi.mocked(fetch).mock.calls[0];
    const requestUrl = new URL(String(url));

    expect(requestUrl.pathname).toBe("/api/cards/search");
    expect(requestUrl.searchParams.get("query")).toBe("Lightning Bolt");
    expect(requestUrl.searchParams.get("scope")).toBe("all");
    expect(requestUrl.searchParams.get("exact")).toBe("false");
    expect(requestUrl.searchParams.get("limit")).toBe("25");
    expect(requestUrl.searchParams.has("set_code")).toBe(false);
  });
});
