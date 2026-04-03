-- Store upstream Scryfall classification fields so app-facing search scope can
-- be derived from durable catalog metadata instead of type-line heuristics.

ALTER TABLE mtg_cards
ADD COLUMN layout TEXT;

ALTER TABLE mtg_cards
ADD COLUMN set_type TEXT;

ALTER TABLE mtg_cards
ADD COLUMN games_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE mtg_cards
ADD COLUMN digital INTEGER NOT NULL DEFAULT 0;

ALTER TABLE mtg_cards
ADD COLUMN oversized INTEGER NOT NULL DEFAULT 0;

ALTER TABLE mtg_cards
ADD COLUMN booster INTEGER NOT NULL DEFAULT 0;

ALTER TABLE mtg_cards
ADD COLUMN promo_types_json TEXT NOT NULL DEFAULT '[]';

ALTER TABLE mtg_cards
ADD COLUMN is_default_add_searchable INTEGER NOT NULL DEFAULT 1;

UPDATE mtg_cards
SET is_default_add_searchable = CASE
    WHEN LOWER(COALESCE(type_line, '')) LIKE 'token %' THEN 0
    WHEN LOWER(COALESCE(type_line, '')) LIKE 'emblem %' THEN 0
    WHEN LOWER(COALESCE(type_line, '')) = 'card' THEN 0
    WHEN LOWER(COALESCE(type_line, '')) LIKE 'card // %' THEN 0
    ELSE 1
END;
