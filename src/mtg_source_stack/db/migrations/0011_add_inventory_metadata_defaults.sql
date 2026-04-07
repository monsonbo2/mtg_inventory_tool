ALTER TABLE inventories
ADD COLUMN default_location TEXT;

ALTER TABLE inventories
ADD COLUMN default_tags TEXT;

ALTER TABLE inventories
ADD COLUMN notes TEXT;

ALTER TABLE inventories
ADD COLUMN acquisition_price NUMERIC;

ALTER TABLE inventories
ADD COLUMN acquisition_currency TEXT;
