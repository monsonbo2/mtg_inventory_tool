-- Latest known retail price per owned position, preferring the newest snapshot.
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
            ORDER BY ps.snapshot_date DESC
        ) AS rn
    FROM price_snapshots ps
    WHERE ps.price_kind = 'retail'
)
SELECT
    i.display_name AS inventory_name,
    oc.name AS oracle_name,
    cp.set_code,
    cp.collector_number,
    ip.condition_code,
    ip.finish,
    ip.quantity,
    lp.provider,
    lp.currency,
    lp.price_value AS unit_price,
    ip.quantity * lp.price_value AS estimated_value
FROM inventory_positions ip
JOIN inventories i ON i.id = ip.inventory_id
JOIN card_printings cp ON cp.scryfall_id = ip.scryfall_id
JOIN oracle_cards oc ON oc.oracle_id = cp.oracle_id
LEFT JOIN latest_prices lp
    ON lp.scryfall_id = ip.scryfall_id
   AND lp.finish = ip.finish
   AND lp.rn = 1
ORDER BY i.display_name, oc.name, cp.set_code, cp.collector_number;

-- Find a local printing by external marketplace ID.
SELECT
    pe.provider,
    pe.external_id,
    oc.name,
    cp.set_code,
    cp.collector_number,
    cp.lang,
    cp.scryfall_id
FROM printing_external_ids pe
JOIN card_printings cp ON cp.scryfall_id = pe.scryfall_id
JOIN oracle_cards oc ON oc.oracle_id = cp.oracle_id
WHERE pe.provider = 'tcgplayer'
  AND pe.external_id = '534658';

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
            ORDER BY ps.snapshot_date DESC
        ) AS rn
    FROM price_snapshots ps
    WHERE ps.price_kind = 'retail'
)
SELECT
    i.display_name AS inventory_name,
    lpp.provider,
    lpp.currency,
    ROUND(SUM(ip.quantity * lpp.price_value), 2) AS total_value
FROM inventory_positions ip
JOIN inventories i ON i.id = ip.inventory_id
JOIN latest_provider_prices lpp
    ON lpp.scryfall_id = ip.scryfall_id
   AND lpp.finish = ip.finish
   AND lpp.rn = 1
GROUP BY i.display_name, lpp.provider, lpp.currency
ORDER BY i.display_name, lpp.provider;

-- Printings present in inventory but missing any retail price snapshots.
SELECT
    i.display_name AS inventory_name,
    oc.name,
    cp.set_code,
    cp.collector_number,
    ip.finish,
    ip.quantity
FROM inventory_positions ip
JOIN inventories i ON i.id = ip.inventory_id
JOIN card_printings cp ON cp.scryfall_id = ip.scryfall_id
JOIN oracle_cards oc ON oc.oracle_id = cp.oracle_id
LEFT JOIN price_snapshots ps
    ON ps.scryfall_id = ip.scryfall_id
   AND ps.price_kind = 'retail'
WHERE ps.id IS NULL
ORDER BY i.display_name, oc.name;
