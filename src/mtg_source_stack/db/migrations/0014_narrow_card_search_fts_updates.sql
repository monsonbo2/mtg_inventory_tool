DROP TRIGGER IF EXISTS trg_mtg_cards_au_fts;

CREATE TRIGGER IF NOT EXISTS trg_mtg_cards_au_fts
AFTER UPDATE OF scryfall_id, name, set_code, set_name, collector_number, lang ON mtg_cards
WHEN
    old.scryfall_id IS NOT new.scryfall_id
    OR old.name IS NOT new.name
    OR old.set_code IS NOT new.set_code
    OR old.set_name IS NOT new.set_name
    OR old.collector_number IS NOT new.collector_number
    OR old.lang IS NOT new.lang
BEGIN
    DELETE FROM mtg_cards_fts
    WHERE scryfall_id = old.scryfall_id;

    INSERT INTO mtg_cards_fts (scryfall_id, name, set_code, set_name, collector_number, lang)
    VALUES (new.scryfall_id, new.name, new.set_code, new.set_name, new.collector_number, new.lang);
END;
