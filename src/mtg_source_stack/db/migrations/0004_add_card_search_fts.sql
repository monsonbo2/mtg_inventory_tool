CREATE VIRTUAL TABLE IF NOT EXISTS mtg_cards_fts USING fts5(
    scryfall_id UNINDEXED,
    name,
    set_code,
    set_name,
    collector_number,
    lang,
    tokenize = 'unicode61'
);

INSERT INTO mtg_cards_fts (scryfall_id, name, set_code, set_name, collector_number, lang)
SELECT
    c.scryfall_id,
    c.name,
    c.set_code,
    c.set_name,
    c.collector_number,
    c.lang
FROM mtg_cards c
WHERE NOT EXISTS (
    SELECT 1
    FROM mtg_cards_fts f
    WHERE f.scryfall_id = c.scryfall_id
);

CREATE TRIGGER IF NOT EXISTS trg_mtg_cards_ai_fts
AFTER INSERT ON mtg_cards
BEGIN
    INSERT INTO mtg_cards_fts (scryfall_id, name, set_code, set_name, collector_number, lang)
    VALUES (new.scryfall_id, new.name, new.set_code, new.set_name, new.collector_number, new.lang);
END;

CREATE TRIGGER IF NOT EXISTS trg_mtg_cards_ad_fts
AFTER DELETE ON mtg_cards
BEGIN
    DELETE FROM mtg_cards_fts
    WHERE scryfall_id = old.scryfall_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_mtg_cards_au_fts
AFTER UPDATE ON mtg_cards
BEGIN
    DELETE FROM mtg_cards_fts
    WHERE scryfall_id = old.scryfall_id;

    INSERT INTO mtg_cards_fts (scryfall_id, name, set_code, set_name, collector_number, lang)
    VALUES (new.scryfall_id, new.name, new.set_code, new.set_name, new.collector_number, new.lang);
END;
