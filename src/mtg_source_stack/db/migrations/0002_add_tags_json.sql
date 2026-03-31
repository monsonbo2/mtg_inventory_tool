-- Add and backfill the tags_json column introduced after the initial MVP
-- schema launch.

UPDATE inventory_items
SET tags_json = '[]'
WHERE tags_json IS NULL OR TRIM(tags_json) = '';
