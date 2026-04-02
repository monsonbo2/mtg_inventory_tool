import type { InventorySummary } from "../types";
import type { AsyncStatus } from "../uiTypes";
import { PanelState } from "./ui/PanelState";
import { StatusPill } from "./ui/StatusPill";

export function InventorySidebar(props: {
  inventories: InventorySummary[];
  selectedInventory: string | null;
  selectedInventoryRow: InventorySummary | null;
  inventoryStatus: AsyncStatus;
  inventoryError: string | null;
  onSelectInventory: (inventorySlug: string) => void;
}) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <p className="section-kicker">Collection Scope</p>
          <h2>Inventories</h2>
        </div>
        <StatusPill status={props.inventoryStatus} />
      </div>

      {props.inventoryError && props.inventories.length ? (
        <p className="panel-error">{props.inventoryError}</p>
      ) : null}

      <div className="inventory-nav">
        {props.inventoryStatus === "loading" && props.inventories.length === 0 ? (
          <PanelState
            body="Looking for available local demo inventories."
            compact
            title="Loading inventories"
            variant="loading"
          />
        ) : props.inventoryStatus === "error" && props.inventories.length === 0 ? (
          <PanelState
            body={props.inventoryError || "Could not load inventories right now."}
            compact
            title="Inventories unavailable"
            variant="error"
          />
        ) : props.inventories.length ? (
          props.inventories.map((inventory) => (
            <button
              key={inventory.slug}
              className={
                inventory.slug === props.selectedInventory
                  ? "inventory-button inventory-button-active"
                  : "inventory-button"
              }
              onClick={() => props.onSelectInventory(inventory.slug)}
              type="button"
            >
              <div className="inventory-button-head">
                <span className="inventory-button-title">{inventory.display_name}</span>
                <span
                  className={
                    inventory.total_cards === 0
                      ? "inventory-state-chip inventory-state-chip-empty"
                      : "inventory-state-chip"
                  }
                >
                  {inventory.total_cards === 0 ? "Empty" : "Active"}
                </span>
              </div>
              <span className="inventory-button-meta">
                {inventory.item_rows} rows · {inventory.total_cards} cards
              </span>
              {inventory.description ? (
                <span className="inventory-button-description">{inventory.description}</span>
              ) : null}
            </button>
          ))
        ) : (
          <PanelState
            body="Create or seed an inventory to start the local demo."
            compact
            title="No inventories yet"
          />
        )}
      </div>

      {props.selectedInventoryRow ? (
        <div className="inventory-focus-card">
          <div className="inventory-focus-header">
            <strong>{props.selectedInventoryRow.display_name}</strong>
            <span
              className={
                props.selectedInventoryRow.total_cards === 0
                  ? "inventory-state-chip inventory-state-chip-empty"
                  : "inventory-state-chip"
              }
            >
              {props.selectedInventoryRow.total_cards === 0 ? "Ready for first add" : "Loaded"}
            </span>
          </div>
          <p>
            {props.selectedInventoryRow.description || "No description provided for this inventory."}
          </p>
        </div>
      ) : null}
    </section>
  );
}
