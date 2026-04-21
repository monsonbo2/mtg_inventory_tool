-- Add owner-managed read-only inventory share links.
--
-- Public links use signed reusable tokens. The database stores the nonce needed
-- to rebuild an active link for owners, but not the full bearer token.
-- Rotating the API signing secret invalidates existing public share URLs.

CREATE TABLE IF NOT EXISTS inventory_share_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL UNIQUE,
    token_nonce TEXT NOT NULL UNIQUE,
    issued_by_actor_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    revoked_by_actor_id TEXT,
    FOREIGN KEY (inventory_id) REFERENCES inventories (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inventory_share_links_token_nonce
    ON inventory_share_links (token_nonce);
