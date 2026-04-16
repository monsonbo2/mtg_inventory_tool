PRAGMA foreign_keys = ON;

-- This is a deliberately smaller MTG-specific schema for an MVP.
-- It is meant for a first working build where you want:
-- - exact printing-level inventory
-- - basic vendor ID storage
-- - daily price snapshots
-- - simple valuation queries
--
-- Compared with schema.sql, this version intentionally avoids:
-- - separate oracle and face tables
-- - sync-run bookkeeping
-- - movement history
-- - a fully normalized external-ID model

CREATE TABLE IF NOT EXISTS mtg_cards (
    scryfall_id TEXT PRIMARY KEY,
    oracle_id TEXT NOT NULL,
    mtgjson_uuid TEXT UNIQUE,
    name TEXT NOT NULL,
    set_code TEXT NOT NULL,
    set_name TEXT NOT NULL,
    collector_number TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    rarity TEXT,
    released_at TEXT,
    mana_cost TEXT,
    type_line TEXT,
    oracle_text TEXT,
    colors_json TEXT NOT NULL DEFAULT '[]',
    color_identity_json TEXT NOT NULL DEFAULT '[]',
    finishes_json TEXT NOT NULL DEFAULT '[]',
    image_uris_json TEXT,
    legalities_json TEXT,
    purchase_uris_json TEXT,
    tcgplayer_product_id TEXT,
    cardkingdom_id TEXT,
    cardmarket_id TEXT,
    cardsphere_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (set_code, collector_number, lang)
);

CREATE INDEX IF NOT EXISTS idx_mtg_cards_name
    ON mtg_cards (name);

CREATE INDEX IF NOT EXISTS idx_mtg_cards_oracle_id
    ON mtg_cards (oracle_id);

CREATE INDEX IF NOT EXISTS idx_mtg_cards_set_collector
    ON mtg_cards (set_code, collector_number);

CREATE TABLE IF NOT EXISTS mtgjson_card_links (
    mtgjson_uuid TEXT PRIMARY KEY,
    scryfall_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scryfall_id) REFERENCES mtg_cards (scryfall_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mtgjson_card_links_scryfall
    ON mtgjson_card_links (scryfall_id);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scryfall_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    price_kind TEXT NOT NULL,
    finish TEXT NOT NULL,
    currency TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    price_value NUMERIC NOT NULL,
    source_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scryfall_id) REFERENCES mtg_cards (scryfall_id) ON DELETE CASCADE,
    UNIQUE (
        scryfall_id,
        provider,
        price_kind,
        finish,
        currency,
        snapshot_date,
        source_name
    )
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_card_date
    ON price_snapshots (scryfall_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_provider_date
    ON price_snapshots (provider, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_kind TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger_kind TEXT NOT NULL DEFAULT 'cli',
    source_name TEXT,
    limit_value INTEGER,
    snapshot_path TEXT,
    summary_json TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_sync_runs_started_at
    ON sync_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_sync_runs_kind_started_at
    ON sync_runs (run_kind, started_at DESC);

CREATE TABLE IF NOT EXISTS sync_run_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL,
    step_name TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_seen INTEGER,
    rows_written INTEGER,
    rows_skipped INTEGER,
    details_json TEXT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    FOREIGN KEY (sync_run_id) REFERENCES sync_runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sync_run_steps_run_step
    ON sync_run_steps (sync_run_id, step_name);

CREATE TABLE IF NOT EXISTS sync_run_artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL,
    artifact_role TEXT NOT NULL,
    source_url TEXT,
    local_path TEXT,
    bytes_written INTEGER,
    sha256 TEXT,
    etag TEXT,
    last_modified TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sync_run_id) REFERENCES sync_runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sync_run_artifacts_run_role
    ON sync_run_artifacts (sync_run_id, artifact_role);

CREATE TABLE IF NOT EXISTS sync_run_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sync_run_id INTEGER NOT NULL,
    step_name TEXT,
    level TEXT NOT NULL,
    code TEXT NOT NULL,
    message TEXT NOT NULL,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (sync_run_id) REFERENCES sync_runs (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sync_run_issues_run_created_at
    ON sync_run_issues (sync_run_id, created_at);

CREATE TABLE IF NOT EXISTS inventories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT,
    default_location TEXT,
    default_tags TEXT,
    notes TEXT,
    acquisition_price NUMERIC,
    acquisition_currency TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL,
    scryfall_id TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    condition_code TEXT NOT NULL DEFAULT 'NM',
    finish TEXT NOT NULL DEFAULT 'normal',
    language_code TEXT NOT NULL DEFAULT 'en',
    location TEXT NOT NULL DEFAULT '',
    acquisition_price NUMERIC,
    acquisition_currency TEXT,
    notes TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inventory_id) REFERENCES inventories (id) ON DELETE CASCADE,
    FOREIGN KEY (scryfall_id) REFERENCES mtg_cards (scryfall_id),
    UNIQUE (
        inventory_id,
        scryfall_id,
        condition_code,
        finish,
        language_code,
        location
    )
);

CREATE INDEX IF NOT EXISTS idx_inventory_items_inventory
    ON inventory_items (inventory_id);

CREATE INDEX IF NOT EXISTS idx_inventory_items_card
    ON inventory_items (scryfall_id);
