export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
  };
}

export interface InventorySummary {
  slug: string;
  display_name: string;
  description: string | null;
  item_rows: number;
  total_cards: number;
}

export interface CatalogSearchRow {
  scryfall_id: string;
  name: string;
  set_code: string;
  set_name: string;
  collector_number: string;
  lang: string;
  rarity: string | null;
  finishes: string[];
  tcgplayer_product_id: string | null;
}

export interface OwnedInventoryRow {
  item_id: number;
  scryfall_id: string;
  name: string;
  set_code: string;
  set_name: string;
  rarity: string | null;
  collector_number: string;
  quantity: number;
  condition_code: string;
  finish: string;
  language_code: string;
  location: string | null;
  tags: string[];
  acquisition_price: string | null;
  acquisition_currency: string | null;
  currency: string | null;
  unit_price: string | null;
  est_value: string | null;
  price_date: string | null;
  notes: string | null;
}

export interface InventoryAuditEvent {
  id: number;
  inventory: string;
  item_id: number | null;
  action: string;
  actor_type: string;
  actor_id: string | null;
  request_id: string | null;
  occurred_at: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
}

export interface AddInventoryItemRequest {
  scryfall_id: string;
  quantity?: number;
  finish?: string;
  location?: string;
  notes?: string | null;
  tags?: string[];
}

export interface PatchInventoryItemRequest {
  quantity?: number;
  finish?: string;
  location?: string;
  clear_location?: boolean;
  notes?: string;
  clear_notes?: boolean;
  tags?: string[];
  clear_tags?: boolean;
}

export interface InventoryItemMutationResponse {
  inventory: string;
  card_name: string;
  set_code: string;
  set_name: string;
  collector_number: string;
  scryfall_id: string;
  item_id: number;
  quantity: number;
  finish: string;
  condition_code: string;
  language_code: string;
  location: string | null;
  acquisition_price: string | null;
  acquisition_currency: string | null;
  notes: string | null;
  tags: string[];
  old_quantity?: number;
  old_finish?: string;
  old_location?: string | null;
  old_notes?: string | null;
  old_tags?: string[];
  merged?: boolean;
  merged_source_item_id?: number | null;
}

export interface SearchCardsParams {
  query: string;
  set_code?: string;
  rarity?: string;
  finish?: string;
  lang?: string;
  exact?: boolean;
  limit?: number;
}
