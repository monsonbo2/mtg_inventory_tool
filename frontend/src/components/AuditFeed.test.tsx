import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuditFeed } from "./AuditFeed";
import type { InventoryAuditEvent, InventorySummary } from "../types";

const inventory: InventorySummary = {
  slug: "personal",
  display_name: "Personal Collection",
  description: "Main demo inventory",
  default_location: null,
  default_tags: null,
  notes: null,
  acquisition_price: null,
  acquisition_currency: null,
  item_rows: 1,
  total_cards: 3,
  role: "owner",
  can_read: true,
  can_write: true,
  can_manage_share: true,
  can_transfer_to: true,
};

const event: InventoryAuditEvent = {
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
};

describe("AuditFeed", () => {
  it("renders ISO audit timestamps through the browser date formatter", () => {
    render(
      <AuditFeed
        auditEvents={[event]}
        selectedInventoryRow={inventory}
        viewError={null}
        viewStatus="ready"
      />,
    );

    expect(screen.getByText("Set Finish")).toBeInTheDocument();
    expect(screen.queryByText("2026-04-02T01:07:30Z")).not.toBeInTheDocument();
    expect(screen.getByText(/Apr/i)).toBeInTheDocument();
  });
});
