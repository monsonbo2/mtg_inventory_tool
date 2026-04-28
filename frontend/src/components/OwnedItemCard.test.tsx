import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OwnedItemCard } from "./OwnedItemCard";
import type { OwnedInventoryRow } from "../types";

const item: OwnedInventoryRow = {
  item_id: 7,
  scryfall_id: "card-1",
  oracle_id: "lightning-bolt-oracle",
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

function renderCard(overrides: Partial<OwnedInventoryRow> = {}) {
  return render(
    <OwnedItemCard
      busyAction={null}
      item={{ ...item, ...overrides }}
      onDelete={async () => "applied"}
      onNotice={() => {}}
      onPatch={async () => "applied"}
    />,
  );
}

describe("OwnedItemCard", () => {
  it("locks the finish editor when the owned row only supports one finish", () => {
    renderCard({ allowed_finishes: ["normal"] });

    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(
      screen.getByText("This printing only supports Normal."),
    ).toBeInTheDocument();
  });

  it("unlocks the finish editor when the owned row publishes multiple finishes", () => {
    renderCard({ allowed_finishes: ["normal", "foil"] });

    const finishSelect = screen.getByRole("combobox");
    expect(finishSelect).toBeEnabled();
    expect(screen.getByText("Available: Normal, Foil.")).toBeInTheDocument();
  });
});
