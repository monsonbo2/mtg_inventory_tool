-- Normalize legacy price snapshot finish aliases so pricing reads use the
-- same finish vocabulary as inventory rows.

DELETE FROM price_snapshots
WHERE id IN (
    SELECT older.id
    FROM price_snapshots AS older
    JOIN price_snapshots AS newer
      ON older.scryfall_id = newer.scryfall_id
     AND older.provider = newer.provider
     AND older.price_kind = newer.price_kind
     AND older.currency = newer.currency
     AND older.snapshot_date = newer.snapshot_date
     AND older.source_name = newer.source_name
     AND CASE
             WHEN LOWER(TRIM(older.finish)) IN ('normal', 'nonfoil') THEN 'normal'
             WHEN LOWER(TRIM(older.finish)) = 'foil' THEN 'foil'
             WHEN LOWER(TRIM(older.finish)) IN ('etched', 'etched foil') THEN 'etched'
             ELSE LOWER(TRIM(older.finish))
         END = CASE
             WHEN LOWER(TRIM(newer.finish)) IN ('normal', 'nonfoil') THEN 'normal'
             WHEN LOWER(TRIM(newer.finish)) = 'foil' THEN 'foil'
             WHEN LOWER(TRIM(newer.finish)) IN ('etched', 'etched foil') THEN 'etched'
             ELSE LOWER(TRIM(newer.finish))
         END
     AND older.id < newer.id
);

UPDATE price_snapshots
SET finish = CASE
    WHEN LOWER(TRIM(finish)) IN ('normal', 'nonfoil') THEN 'normal'
    WHEN LOWER(TRIM(finish)) = 'foil' THEN 'foil'
    WHEN LOWER(TRIM(finish)) IN ('etched', 'etched foil') THEN 'etched'
    ELSE LOWER(TRIM(finish))
END;
