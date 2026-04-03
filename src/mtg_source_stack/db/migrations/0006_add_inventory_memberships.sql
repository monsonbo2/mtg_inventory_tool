-- Add inventory-scoped membership records so shared-service access can evolve
-- from one global trust group into per-inventory read/write rules.

CREATE TABLE IF NOT EXISTS inventory_memberships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL,
    actor_id TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inventory_id) REFERENCES inventories (id) ON DELETE CASCADE,
    CHECK (role IN ('viewer', 'editor', 'owner')),
    UNIQUE (inventory_id, actor_id)
);

CREATE INDEX IF NOT EXISTS idx_inventory_memberships_inventory
    ON inventory_memberships (inventory_id);

CREATE INDEX IF NOT EXISTS idx_inventory_memberships_actor
    ON inventory_memberships (actor_id);
