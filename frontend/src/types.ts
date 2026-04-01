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

export type FinishValue = "normal" | "foil" | "etched";
export type FinishInput = FinishValue | "nonfoil";
export type ConditionCode =
  | "M"
  | "NM"
  | "LP"
  | "MP"
  | "HP"
  | "DMG"
  | (string & {});
export type LanguageCode =
  | "en"
  | "ja"
  | "de"
  | "fr"
  | "it"
  | "es"
  | "pt"
  | "ru"
  | "ko"
  | "zhs"
  | "zht"
  | "ph"
  | (string & {});

export interface CatalogSearchRow {
  scryfall_id: string;
  name: string;
  set_code: string;
  set_name: string;
  collector_number: string;
  lang: LanguageCode;
  rarity: string | null;
  finishes: FinishValue[];
  tcgplayer_product_id: string | null;
  image_uri_small: string | null;
  image_uri_normal: string | null;
}

export interface OwnedInventoryRow {
  item_id: number;
  scryfall_id: string;
  name: string;
  set_code: string;
  set_name: string;
  rarity: string | null;
  collector_number: string;
  image_uri_small: string | null;
  image_uri_normal: string | null;
  quantity: number;
  condition_code: ConditionCode;
  finish: FinishValue;
  language_code: LanguageCode;
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
  finish?: FinishInput;
  location?: string;
  notes?: string | null;
  tags?: string[];
}

export interface PatchInventoryItemRequest {
  quantity?: number;
  finish?: FinishInput;
  location?: string;
  clear_location?: boolean;
  notes?: string;
  clear_notes?: boolean;
  tags?: string[];
  clear_tags?: boolean;
}

export type InventoryPatchOperation =
  | "set_quantity"
  | "set_finish"
  | "set_location"
  | "set_condition"
  | "set_notes"
  | "set_tags"
  | "set_acquisition";

export interface InventoryItemMutationResponse {
  inventory: string;
  card_name: string;
  set_code: string;
  set_name: string;
  collector_number: string;
  scryfall_id: string;
  item_id: number;
  quantity: number;
  finish: FinishValue;
  condition_code: ConditionCode;
  language_code: LanguageCode;
  location: string | null;
  acquisition_price: string | null;
  acquisition_currency: string | null;
  notes: string | null;
  tags: string[];
  operation?: InventoryPatchOperation;
  old_quantity?: number;
  old_finish?: FinishValue;
  old_location?: string | null;
  old_condition_code?: ConditionCode;
  old_notes?: string | null;
  old_tags?: string[];
  old_acquisition_price?: string | null;
  old_acquisition_currency?: string | null;
  merged?: boolean;
  merged_source_item_id?: number | null;
}

export interface InventoryItemPatchResponse extends InventoryItemMutationResponse {
  operation: InventoryPatchOperation;
}

export interface SearchCardsParams {
  query: string;
  set_code?: string;
  rarity?: string;
  finish?: FinishInput;
  lang?: LanguageCode;
  exact?: boolean;
  limit?: number;
}
