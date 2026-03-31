CREATE TABLE IF NOT EXISTS inventory_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_slug TEXT NOT NULL,
    item_id INTEGER,
    action TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT,
    request_id TEXT,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    before_json TEXT,
    after_json TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_inventory_audit_log_inventory_time
    ON inventory_audit_log (inventory_slug, occurred_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_inventory_audit_log_item_time
    ON inventory_audit_log (item_id, occurred_at DESC, id DESC);
