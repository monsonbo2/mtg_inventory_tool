import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OwnedItemCard } from "./OwnedItemCard";
import type { OwnedInventoryRow } from "../types";
import type { FinishSupportState } from "../uiTypes";

const allowedFinishes: OwnedInventoryRow["allowed_finishes"] = ["normal", "foil"];

const item: OwnedInventoryRow = {
  item_id: 7,
  scryfall_id: "card-1",
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
  allowed_finishes: allowedFinishes,
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

function renderCard(finishSupport: FinishSupportState | null) {
  return render(
    <OwnedItemCard
      busyAction={null}
      finishSupport={finishSupport}
      item={item}
      onDelete={async () => {}}
      onNotice={() => {}}
      onPatch={async () => {}}
    />,
  );
}

describe("OwnedItemCard", () => {
  it("locks the finish editor while compatibility is still loading", () => {
    renderCard({ status: "loading" });

    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(
      screen.getByText("Checking which finishes this printing supports..."),
    ).toBeInTheDocument();
  });

  it("unlocks the finish editor when multiple supported finishes are known", () => {
    renderCard({ status: "ready", finishes: ["normal", "foil"] });

    const finishSelect = screen.getByRole("combobox");
    expect(finishSelect).toBeEnabled();
    expect(screen.getByText("Available: Normal, Foil.")).toBeInTheDocument();
  });
});
