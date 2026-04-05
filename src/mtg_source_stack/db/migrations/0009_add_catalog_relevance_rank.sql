-- Store backend-owned relevance metadata from Scryfall so grouped search can
-- tune ordering without changing the public response shape.

ALTER TABLE mtg_cards
ADD COLUMN edhrec_rank INTEGER;
