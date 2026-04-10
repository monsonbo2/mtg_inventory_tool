CREATE TABLE IF NOT EXISTS mtgjson_card_links (
    mtgjson_uuid TEXT PRIMARY KEY,
    scryfall_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (scryfall_id) REFERENCES mtg_cards (scryfall_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_mtgjson_card_links_scryfall
    ON mtgjson_card_links (scryfall_id);

INSERT OR IGNORE INTO mtgjson_card_links (mtgjson_uuid, scryfall_id)
SELECT mtgjson_uuid, scryfall_id
FROM mtg_cards
WHERE mtgjson_uuid IS NOT NULL
  AND TRIM(mtgjson_uuid) <> '';
