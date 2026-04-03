-- Track one default inventory per authenticated actor so first-run shared
-- service bootstrap can create a personal collection exactly once.

CREATE TABLE IF NOT EXISTS actor_default_inventories (
    actor_id TEXT PRIMARY KEY,
    inventory_id INTEGER NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inventory_id) REFERENCES inventories (id) ON DELETE CASCADE
);
