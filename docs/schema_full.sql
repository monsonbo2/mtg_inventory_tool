-- Future-target normalized schema for a later backend migration.
-- This file is a design reference only.
-- The current web-v1 runtime contract uses docs/schema_mvp.sql and
-- src/mtg_source_stack/mtg_mvp_schema.sql instead.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS source_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_version TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    rows_seen INTEGER NOT NULL DEFAULT 0,
    rows_upserted INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_sync_runs_source_started_at
    ON source_sync_runs (source_name, started_at DESC);

CREATE TABLE IF NOT EXISTS mtg_sets (
    set_code TEXT PRIMARY KEY,
    set_name TEXT NOT NULL,
    set_type TEXT,
    released_at TEXT,
    parent_set_code TEXT,
    scryfall_set_id TEXT,
    card_count INTEGER,
    digital_only INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_set_code) REFERENCES mtg_sets (set_code)
);

CREATE TABLE IF NOT EXISTS oracle_cards (
    oracle_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mana_cost TEXT,
    type_line TEXT,
    oracle_text TEXT,
    color_identity_json TEXT NOT NULL DEFAULT '[]',
    colors_json TEXT,
    cmc REAL,
    reserved INTEGER NOT NULL DEFAULT 0,
    edhrec_rank INTEGER,
    legalities_json TEXT,
    keywords_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS card_printings (
    scryfall_id TEXT PRIMARY KEY,
    oracle_id TEXT NOT NULL,
    mtgjson_uuid TEXT UNIQUE,
    set_code TEXT NOT NULL,
    collector_number TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'en',
    printed_name TEXT,
    printed_text TEXT,
    rarity TEXT,
    layout TEXT,
    released_at TEXT,
    border_color TEXT,
    frame TEXT,
    artist TEXT,
    illustration_id TEXT,
    image_status TEXT,
    image_uris_json TEXT,
    purchase_uris_json TEXT,
    finishes_json TEXT NOT NULL DEFAULT '[]',
    games_json TEXT NOT NULL DEFAULT '[]',
    scryfall_uri TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (oracle_id) REFERENCES oracle_cards (oracle_id),
    FOREIGN KEY (set_code) REFERENCES mtg_sets (set_code),
    UNIQUE (set_code, collector_number, lang)
);

CREATE INDEX IF NOT EXISTS idx_card_printings_oracle_id
    ON card_printings (oracle_id);

CREATE INDEX IF NOT EXISTS idx_card_printings_set_code_collector
    ON card_printings (set_code, collector_number);

CREATE TABLE IF NOT EXISTS card_faces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scryfall_id TEXT NOT NULL,
    face_index INTEGER NOT NULL,
    name TEXT NOT NULL,
    mana_cost TEXT,
    type_line TEXT,
    oracle_text TEXT,
    colors_json TEXT,
    power TEXT,
    toughness TEXT,
    loyalty TEXT,
    defense TEXT,
    artist TEXT,
    image_uris_json TEXT,
    FOREIGN KEY (scryfall_id) REFERENCES card_printings (scryfall_id) ON DELETE CASCADE,
    UNIQUE (scryfall_id, face_index)
);

CREATE INDEX IF NOT EXISTS idx_card_faces_scryfall_id
    ON card_faces (scryfall_id);

CREATE TABLE IF NOT EXISTS printing_external_ids (
    scryfall_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    id_kind TEXT NOT NULL DEFAULT 'product',
    external_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scryfall_id) REFERENCES card_printings (scryfall_id) ON DELETE CASCADE,
    PRIMARY KEY (scryfall_id, provider, id_kind)
);

CREATE INDEX IF NOT EXISTS idx_printing_external_ids_provider_external
    ON printing_external_ids (provider, external_id);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scryfall_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    channel TEXT NOT NULL,
    price_kind TEXT NOT NULL,
    finish TEXT NOT NULL,
    currency TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    price_value NUMERIC NOT NULL,
    source_name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scryfall_id) REFERENCES card_printings (scryfall_id) ON DELETE CASCADE,
    UNIQUE (
        scryfall_id,
        provider,
        channel,
        price_kind,
        finish,
        currency,
        snapshot_date,
        source_name
    )
);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_lookup
    ON price_snapshots (scryfall_id, snapshot_date DESC);

CREATE INDEX IF NOT EXISTS idx_price_snapshots_provider_date
    ON price_snapshots (provider, snapshot_date DESC);

CREATE TABLE IF NOT EXISTS inventories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL,
    scryfall_id TEXT NOT NULL,
    condition_code TEXT NOT NULL,
    finish TEXT NOT NULL DEFAULT 'normal',
    language_code TEXT NOT NULL DEFAULT 'en',
    quantity INTEGER NOT NULL DEFAULT 0,
    acquisition_price NUMERIC,
    acquisition_currency TEXT,
    current_price_override NUMERIC,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT,
    is_signed INTEGER NOT NULL DEFAULT 0,
    is_altered INTEGER NOT NULL DEFAULT 0,
    is_playset INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inventory_id) REFERENCES inventories (id) ON DELETE CASCADE,
    FOREIGN KEY (scryfall_id) REFERENCES card_printings (scryfall_id),
    UNIQUE (
        inventory_id,
        scryfall_id,
        condition_code,
        finish,
        language_code,
        location,
        is_signed,
        is_altered,
        is_playset
    )
);

CREATE INDEX IF NOT EXISTS idx_inventory_positions_inventory
    ON inventory_positions (inventory_id);

CREATE INDEX IF NOT EXISTS idx_inventory_positions_printing
    ON inventory_positions (scryfall_id);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_position_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL,
    quantity_delta INTEGER NOT NULL,
    unit_price NUMERIC,
    currency TEXT,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    note TEXT,
    source_ref TEXT,
    FOREIGN KEY (inventory_position_id) REFERENCES inventory_positions (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inventory_movements_position_time
    ON inventory_movements (inventory_position_id, occurred_at DESC);
