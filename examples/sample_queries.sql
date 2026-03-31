-- Latest known retail price per owned inventory row, preferring the newest
-- snapshot for each provider/finish/currency combination.
WITH latest_prices AS (
    SELECT
        ps.scryfall_id,
        ps.provider,
        ps.finish,
        ps.currency,
        ps.price_value,
        ps.snapshot_date,
        ROW_NUMBER() OVER (
            PARTITION BY ps.scryfall_id, ps.provider, ps.finish, ps.currency
            ORDER BY ps.snapshot_date DESC, ps.id DESC
        ) AS rn
    FROM price_snapshots ps
    WHERE ps.price_kind = 'retail'
)
SELECT
    i.display_name AS inventory_name,
    c.name,
    c.set_code,
    c.collector_number,
    ii.condition_code,
    ii.finish,
    ii.language_code,
    ii.location,
    ii.quantity,
    lp.provider,
    lp.currency,
    lp.price_value AS unit_price,
    ii.quantity * lp.price_value AS estimated_value
FROM inventory_items ii
JOIN inventories i ON i.id = ii.inventory_id
JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
LEFT JOIN latest_prices lp
    ON lp.scryfall_id = ii.scryfall_id
   AND lp.finish = ii.finish
   AND lp.rn = 1
ORDER BY i.display_name, c.name, c.set_code, c.collector_number, ii.id;

-- Find a local printing by marketplace identifier stored on the live card row.
SELECT
    c.tcgplayer_product_id,
    c.cardkingdom_id,
    c.cardmarket_id,
    c.cardsphere_id,
    c.name,
    c.set_code,
    c.collector_number,
    c.lang,
    c.scryfall_id
FROM mtg_cards c
WHERE c.tcgplayer_product_id = '534658';

-- Inventory valuation by provider.
WITH latest_provider_prices AS (
    SELECT
        ps.scryfall_id,
        ps.provider,
        ps.finish,
        ps.currency,
        ps.price_value,
        ROW_NUMBER() OVER (
            PARTITION BY ps.scryfall_id, ps.provider, ps.finish, ps.currency
            ORDER BY ps.snapshot_date DESC, ps.id DESC
        ) AS rn
    FROM price_snapshots ps
    WHERE ps.price_kind = 'retail'
)
SELECT
    i.display_name AS inventory_name,
    lpp.provider,
    lpp.currency,
    ROUND(SUM(ii.quantity * lpp.price_value), 2) AS total_value
FROM inventory_items ii
JOIN inventories i ON i.id = ii.inventory_id
JOIN latest_provider_prices lpp
    ON lpp.scryfall_id = ii.scryfall_id
   AND lpp.finish = ii.finish
   AND lpp.rn = 1
GROUP BY i.display_name, lpp.provider, lpp.currency
ORDER BY i.display_name, lpp.provider;

-- Inventory rows that do not currently have any retail price for their finish.
SELECT
    i.display_name AS inventory_name,
    c.name,
    c.set_code,
    c.collector_number,
    ii.finish,
    ii.quantity
FROM inventory_items ii
JOIN inventories i ON i.id = ii.inventory_id
JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
LEFT JOIN price_snapshots ps
    ON ps.scryfall_id = ii.scryfall_id
   AND ps.price_kind = 'retail'
   AND ps.finish = ii.finish
WHERE ps.id IS NULL
ORDER BY i.display_name, c.name, c.set_code, c.collector_number;

-- Most recent inventory audit events.
SELECT
    ial.id,
    ial.occurred_at,
    ial.inventory_slug,
    ial.action,
    ial.item_id,
    ial.actor_type,
    ial.actor_id,
    ial.request_id,
    ial.before_json,
    ial.after_json
FROM inventory_audit_log ial
ORDER BY ial.id DESC
LIMIT 20;
