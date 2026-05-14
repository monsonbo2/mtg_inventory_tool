import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { ApiClientError } from "./api";
import type { PublicInventoryShareResponse } from "./types";

vi.mock("./api", async () => {
  const actual = await vi.importActual<typeof import("./api")>("./api");
  return {
    ...actual,
    getAccessSummary: vi.fn(),
    getPublicInventoryShare: vi.fn(),
    listInventories: vi.fn(),
  };
});

import {
  getAccessSummary,
  getPublicInventoryShare,
  listInventories,
} from "./api";

function buildPublicInventoryShare(
  overrides: Partial<PublicInventoryShareResponse> = {},
): PublicInventoryShareResponse {
  return {
    inventory: {
      description: "Cards visible through a public link",
      display_name: "Public Binder",
      item_rows: 1,
      total_cards: 2,
    },
    items: [
      {
        allowed_finishes: ["normal", "foil"],
        collector_number: "161",
        condition_code: "NM",
        finish: "normal",
        image_uri_normal: null,
        image_uri_small: null,
        language_code: "en",
        name: "Lightning Bolt",
        oracle_id: "bolt-oracle",
        quantity: 2,
        rarity: "common",
        scryfall_id: "bolt-1",
        set_code: "lea",
        set_name: "Limited Edition Alpha",
      },
    ],
    ...overrides,
  };
}

describe("public share route", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    vi.mocked(getPublicInventoryShare).mockReset();
    vi.mocked(getAccessSummary).mockReset();
    vi.mocked(listInventories).mockReset();
  });

  afterEach(() => {
    window.history.pushState({}, "", "/");
    vi.clearAllMocks();
  });

  it("renders public share links without booting the authenticated app shell", async () => {
    window.history.pushState({}, "", "/shared/inventories/v1.1.public.sig");
    vi.mocked(getPublicInventoryShare).mockResolvedValue(
      buildPublicInventoryShare(),
    );

    render(<App />);

    expect(
      await screen.findByRole("heading", { name: "Public Binder" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Cards visible through a public link"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Lightning Bolt" })).toBeInTheDocument();
    expect(screen.getByText("Qty 2")).toBeInTheDocument();
    expect(screen.getByText("NM")).toBeInTheDocument();
    expect(screen.getByText("Normal")).toBeInTheDocument();
    expect(screen.getByText("EN")).toBeInTheDocument();
    expect(getPublicInventoryShare).toHaveBeenCalledWith("v1.1.public.sig");
    expect(getAccessSummary).not.toHaveBeenCalled();
    expect(listInventories).not.toHaveBeenCalled();
  });

  it("shows an unavailable state for invalid public share links", async () => {
    window.history.pushState({}, "", "/shared/inventories/missing-token");
    vi.mocked(getPublicInventoryShare).mockRejectedValue(
      new ApiClientError("Shared inventory link was not found.", {
        code: "not_found",
        status: 404,
      }),
    );

    render(<App />);

    expect(await screen.findByText("Shared inventory unavailable")).toBeInTheDocument();
    expect(screen.getByText("Shared inventory link was not found.")).toBeInTheDocument();
    expect(getAccessSummary).not.toHaveBeenCalled();
    expect(listInventories).not.toHaveBeenCalled();
  });

  it("shows an unavailable state for malformed public share paths", () => {
    window.history.pushState({}, "", "/shared/inventories/%E0%A4%A");

    render(<App />);

    expect(screen.getByText("Shared inventory unavailable")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This public inventory link is malformed. Check the link and try again.",
      ),
    ).toBeInTheDocument();
    expect(getPublicInventoryShare).not.toHaveBeenCalled();
    expect(getAccessSummary).not.toHaveBeenCalled();
    expect(listInventories).not.toHaveBeenCalled();
  });
});
