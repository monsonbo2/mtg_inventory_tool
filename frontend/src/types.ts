export interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown> | null;
  };
}

export type CatalogScope = "default" | "all";
export type FinishValue = "normal" | "foil" | "etched";
export type FinishInput = FinishValue | "nonfoil";
export type PrintingSelectionMode = "explicit" | "defaulted";
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
export type InventoryAcquisitionMergePolicy = "target" | "source";
export type InventoryTransferMode = "copy" | "move";
export type InventoryTransferConflictPolicy = "fail" | "merge";
export type InventoryTransferSelectionKind = "items" | "all_items";
export type BulkInventorySelectionKind = "items" | "filtered" | "all_items";
export type InventoryCapabilityRole = "viewer" | "editor" | "owner" | "admin";
export type InventoryTransferItemStatus =
  | "would_copy"
  | "would_move"
  | "would_merge"
  | "would_fail"
  | "copied"
  | "moved"
  | "merged";
export type ImportResolutionIssueKind =
  | "ambiguous_card_name"
  | "ambiguous_printing"
  | "unknown_card"
  | "finish_required";
export type CsvImportDetectedFormat =
  | "deckbox_collection_csv"
  | "deckstats_collection_csv"
  | "generic_csv"
  | "manabox_collection_csv"
  | "mtggoldfish_collection_csv"
  | "mtgstocks_collection_csv"
  | "tcgplayer_app_collection_csv"
  | "tcgplayer_legacy_collection_csv"
  | (string & {});
export type DeckUrlProvider =
  | "archidekt"
  | "aetherhub"
  | "manabox"
  | "moxfield"
  | "mtggoldfish"
  | "mtgtop8"
  | "tappedout"
  | (string & {});

export interface InventorySummary {
  slug: string;
  display_name: string;
  description: string | null;
  default_location: string | null;
  default_tags: string | null;
  notes: string | null;
  acquisition_price: string | null;
  acquisition_currency: string | null;
  item_rows: number;
  total_cards: number;
  role: InventoryCapabilityRole | null;
  can_read: boolean;
  can_write: boolean;
  can_manage_share: boolean;
  can_transfer_to: boolean;
}

export interface InventoryCreateRequest {
  slug: string;
  display_name: string;
  description?: string | null;
  default_location?: string | null;
  default_tags?: string | null;
  notes?: string | null;
  acquisition_price?: string | null;
  acquisition_currency?: string | null;
}

export interface InventoryCreateResponse {
  inventory_id: number;
  slug: string;
  display_name: string;
  description: string | null;
  default_location: string | null;
  default_tags: string | null;
  notes: string | null;
  acquisition_price: string | null;
  acquisition_currency: string | null;
}

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

export interface CatalogPrintingLookupRow extends CatalogSearchRow {
  is_default_add_choice: boolean;
}

export interface CatalogPrintingSummaryResponse {
  oracle_id: string;
  default_printing: CatalogPrintingLookupRow | null;
  available_languages: LanguageCode[];
  printings_count: number;
  has_more_printings: boolean;
  printings: CatalogPrintingLookupRow[];
}

export interface CatalogNameSearchRow {
  oracle_id: string;
  name: string;
  printings_count: number;
  available_languages: LanguageCode[];
  image_uri_small: string | null;
  image_uri_normal: string | null;
}

export interface CatalogNameSearchResult {
  items: CatalogNameSearchRow[];
  total_count: number;
  has_more: boolean;
}

export interface OwnedInventoryRow {
  item_id: number;
  scryfall_id: string;
  oracle_id: string;
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
  allowed_finishes: FinishValue[];
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
  printing_selection_mode: PrintingSelectionMode;
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

type AddInventoryItemIdentifier =
  | { scryfall_id: string }
  | { oracle_id: string }
  | { tcgplayer_product_id: string }
  | { name: string };

export type AddInventoryItemRequest = AddInventoryItemIdentifier & {
  acquisition_currency?: string | null;
  acquisition_price?: string | null;
  collector_number?: string | null;
  condition_code?: ConditionCode;
  finish?: FinishInput;
  lang?: LanguageCode | null;
  language_code?: LanguageCode | null;
  location?: string;
  notes?: string | null;
  quantity?: number;
  set_code?: string | null;
  tags?: string[];
};

type PatchMergeOptions = {
  keep_acquisition?: InventoryAcquisitionMergePolicy | null;
  merge?: boolean;
};

type PrintingChangeMergeOptions = {
  keep_acquisition?: InventoryAcquisitionMergePolicy | null;
  merge?: boolean;
};

export type PatchInventoryItemRequest =
  | { quantity: number }
  | { finish: FinishInput }
  | ({ location: string } & PatchMergeOptions)
  | ({ clear_location: true } & PatchMergeOptions)
  | ({ condition_code: ConditionCode } & PatchMergeOptions)
  | { notes: string | null }
  | { clear_notes: true }
  | { tags: string[] }
  | { clear_tags: true }
  | {
      acquisition_price?: string | null;
      acquisition_currency?: string | null;
      clear_acquisition?: false | undefined;
    }
  | {
      clear_acquisition: true;
    };

export type SetInventoryItemPrintingRequest = PrintingChangeMergeOptions & {
  scryfall_id: string;
  finish?: FinishInput;
};

export type BulkInventoryItemOperation =
  | "add_tags"
  | "remove_tags"
  | "set_tags"
  | "clear_tags"
  | "set_quantity"
  | "set_notes"
  | "set_acquisition"
  | "set_finish"
  | "set_location"
  | "set_condition";

export type BulkTagMutationOperation = Extract<
  BulkInventoryItemOperation,
  "add_tags" | "remove_tags" | "set_tags" | "clear_tags"
>;

type BulkInventoryItemMutationBase = {
  selection: BulkInventorySelectionRequest;
};

export type BulkInventorySelectionRequest =
  | {
      kind: "items";
      item_ids: number[];
    }
  | {
      kind: "filtered";
      query?: string | null;
      set_code?: string | null;
      rarity?: string | null;
      finish?: FinishInput | null;
      condition_code?: ConditionCode | null;
      language_code?: LanguageCode | null;
      location?: string | null;
      tags?: string[] | null;
    }
  | {
      kind: "all_items";
    };

type BulkInventoryMutationMergeOptions = {
  keep_acquisition?: InventoryAcquisitionMergePolicy | null;
  merge?: boolean;
};

export type BulkInventoryItemMutationRequest =
  | (BulkInventoryItemMutationBase & {
      operation: "add_tags" | "remove_tags" | "set_tags";
      tags: string[];
    })
  | (BulkInventoryItemMutationBase & {
      operation: "clear_tags";
    })
  | (BulkInventoryItemMutationBase & {
      operation: "set_quantity";
      quantity: number;
    })
  | (BulkInventoryItemMutationBase &
      (
        | {
            operation: "set_notes";
            notes: string | null;
          }
        | {
            operation: "set_notes";
            clear_notes: true;
          }
      ))
  | (BulkInventoryItemMutationBase &
      (
        | {
            operation: "set_acquisition";
            acquisition_price?: string | null;
            acquisition_currency?: string | null;
            clear_acquisition?: false | undefined;
          }
        | {
            operation: "set_acquisition";
            clear_acquisition: true;
          }
      ))
  | (BulkInventoryItemMutationBase & {
      operation: "set_finish";
      finish: FinishInput;
    })
  | (BulkInventoryItemMutationBase &
      BulkInventoryMutationMergeOptions &
      (
        | {
            operation: "set_location";
            location: string;
          }
        | {
            operation: "set_location";
            clear_location: true;
          }
      ))
  | (BulkInventoryItemMutationBase &
      BulkInventoryMutationMergeOptions & {
        operation: "set_condition";
        condition_code: ConditionCode;
      });

interface InventoryItemMutationBase {
  inventory: string;
  card_name: string;
  oracle_id: string;
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
  printing_selection_mode: PrintingSelectionMode;
}

export interface InventoryItemMutationResponse extends InventoryItemMutationBase {}

export type InventoryPatchOperation =
  | "set_quantity"
  | "set_finish"
  | "set_location"
  | "set_condition"
  | "set_notes"
  | "set_tags"
  | "set_acquisition";

interface InventoryItemPatchResponseBase extends InventoryItemMutationBase {
  operation: InventoryPatchOperation;
}

export interface SetQuantityPatchResponse extends InventoryItemPatchResponseBase {
  operation: "set_quantity";
  old_quantity: number;
}

export interface SetFinishPatchResponse extends InventoryItemPatchResponseBase {
  operation: "set_finish";
  old_finish: FinishValue;
}

export interface SetLocationPatchResponse extends InventoryItemPatchResponseBase {
  operation: "set_location";
  merged: boolean;
  merged_source_item_id?: number | null;
  old_location: string | null;
}

export interface SetConditionPatchResponse extends InventoryItemPatchResponseBase {
  operation: "set_condition";
  merged: boolean;
  merged_source_item_id?: number | null;
  old_condition_code: ConditionCode;
}

export interface SetNotesPatchResponse extends InventoryItemPatchResponseBase {
  operation: "set_notes";
  old_notes: string | null;
}

export interface SetTagsPatchResponse extends InventoryItemPatchResponseBase {
  operation: "set_tags";
  old_tags: string[];
}

export interface SetAcquisitionPatchResponse
  extends InventoryItemPatchResponseBase {
  operation: "set_acquisition";
  old_acquisition_price: string | null;
  old_acquisition_currency: string | null;
}

export interface SetPrintingResponse extends InventoryItemMutationBase {
  operation: "set_printing";
  old_scryfall_id: string;
  old_finish: FinishValue;
  old_language_code: LanguageCode;
  merged: boolean;
  merged_source_item_id?: number | null;
}

export type InventoryItemPatchResponse =
  | SetQuantityPatchResponse
  | SetFinishPatchResponse
  | SetLocationPatchResponse
  | SetConditionPatchResponse
  | SetNotesPatchResponse
  | SetTagsPatchResponse
  | SetAcquisitionPatchResponse;

export interface BulkInventoryItemMutationResponse {
  inventory: string;
  operation: BulkInventoryItemOperation;
  selection_kind: BulkInventorySelectionKind;
  matched_count: number;
  unchanged_count: number;
  updated_item_ids: number[];
  updated_count: number;
  updated_item_ids_truncated: boolean;
}

export interface SearchCardsParams {
  query: string;
  set_code?: string;
  rarity?: string;
  finish?: FinishInput;
  lang?: LanguageCode;
  scope?: CatalogScope;
  exact?: boolean;
  limit?: number;
}

export interface SearchCardNamesParams {
  query: string;
  scope?: CatalogScope;
  exact?: boolean;
  limit?: number;
}

export interface ListCardPrintingsParams {
  lang?: LanguageCode | "all";
  scope?: CatalogScope;
}

export interface CardPrintingSummaryParams {
  scope?: CatalogScope;
}

export interface ImportResolutionOptionResponse {
  scryfall_id: string;
  finish: FinishValue;
  name: string;
  set_code: string;
  set_name: string;
  collector_number: string;
  lang: LanguageCode;
  image_uri_small: string | null;
  image_uri_normal: string | null;
}

export interface CsvImportResolutionRequest {
  csv_row: number;
  scryfall_id: string;
  finish: FinishInput;
}

export interface CsvImportRequestedCardResponse {
  scryfall_id: string | null;
  oracle_id: string | null;
  tcgplayer_product_id: string | null;
  name: string | null;
  quantity: number;
  set_code: string | null;
  set_name: string | null;
  collector_number: string | null;
  finish?: FinishValue | null;
  lang?: LanguageCode | null;
}

export interface CsvImportResolutionIssueResponse {
  kind: ImportResolutionIssueKind;
  csv_row: number;
  requested: CsvImportRequestedCardResponse;
  options: ImportResolutionOptionResponse[];
}

export interface CsvImportSummaryResponse {
  total_card_quantity: number;
  distinct_card_names: number;
  distinct_printings: number;
  requested_card_quantity: number;
  unresolved_card_quantity: number;
}

export interface CsvImportRowResponse extends InventoryItemMutationResponse {
  csv_row: number;
}

export interface CsvImportRequest {
  file: Blob;
  default_inventory?: string | null;
  dry_run?: boolean;
  resolutions?: CsvImportResolutionRequest[];
}

export interface CsvImportResponse {
  csv_filename: string;
  detected_format: CsvImportDetectedFormat;
  default_inventory: string | null;
  rows_seen: number;
  rows_written: number;
  ready_to_commit: boolean;
  summary: CsvImportSummaryResponse;
  resolution_issues: CsvImportResolutionIssueResponse[];
  dry_run: boolean;
  imported_rows: CsvImportRowResponse[];
}

export interface DecklistImportResolutionRequest {
  decklist_line: number;
  scryfall_id: string;
  finish: FinishInput;
}

export interface DecklistImportRequestedCardResponse {
  name: string;
  quantity: number;
  set_code: string | null;
  collector_number: string | null;
  finish?: FinishValue | null;
}

export interface DecklistImportResolutionIssueResponse {
  kind: ImportResolutionIssueKind;
  decklist_line: number;
  section: string;
  requested: DecklistImportRequestedCardResponse;
  options: ImportResolutionOptionResponse[];
}

export interface DecklistImportSummaryResponse {
  total_card_quantity: number;
  distinct_card_names: number;
  distinct_printings: number;
  section_card_quantities: Record<string, number>;
  requested_card_quantity: number;
  unresolved_card_quantity: number;
}

export interface DecklistImportRowResponse extends InventoryItemMutationResponse {
  decklist_line: number;
  section: string;
}

export interface DecklistImportRequest {
  deck_text: string;
  default_inventory: string;
  dry_run?: boolean;
  resolutions?: DecklistImportResolutionRequest[];
}

export interface DecklistImportResponse {
  deck_name: string | null;
  default_inventory: string | null;
  rows_seen: number;
  rows_written: number;
  ready_to_commit: boolean;
  summary: DecklistImportSummaryResponse;
  resolution_issues: DecklistImportResolutionIssueResponse[];
  dry_run: boolean;
  imported_rows: DecklistImportRowResponse[];
}

export interface DeckUrlImportResolutionRequest {
  source_position: number;
  scryfall_id: string;
  finish: FinishInput;
}

export interface DeckUrlImportRequestedCardResponse {
  scryfall_id: string | null;
  name: string | null;
  quantity: number;
  set_code: string | null;
  collector_number: string | null;
  finish?: FinishValue | null;
}

export interface DeckUrlImportResolutionIssueResponse {
  kind: ImportResolutionIssueKind;
  source_position: number;
  section: string;
  requested: DeckUrlImportRequestedCardResponse;
  options: ImportResolutionOptionResponse[];
}

export interface DeckUrlImportSummaryResponse {
  total_card_quantity: number;
  distinct_card_names: number;
  distinct_printings: number;
  section_card_quantities: Record<string, number>;
  requested_card_quantity: number;
  unresolved_card_quantity: number;
}

export interface DeckUrlImportRowResponse extends InventoryItemMutationResponse {
  source_position: number;
  section: string;
}

export interface DeckUrlImportRequest {
  source_url: string;
  default_inventory: string;
  dry_run?: boolean;
  resolutions?: DeckUrlImportResolutionRequest[];
  source_snapshot_token?: string | null;
}

export interface DeckUrlImportResponse {
  source_url: string;
  provider: DeckUrlProvider;
  deck_name: string | null;
  default_inventory: string | null;
  rows_seen: number;
  rows_written: number;
  ready_to_commit: boolean;
  source_snapshot_token: string | null;
  summary: DeckUrlImportSummaryResponse;
  resolution_issues: DeckUrlImportResolutionIssueResponse[];
  dry_run: boolean;
  imported_rows: DeckUrlImportRowResponse[];
}

export interface DefaultInventoryBootstrapResponse {
  created: boolean;
  inventory: InventoryCreateResponse;
}

export interface AccessSummaryResponse {
  can_bootstrap: boolean;
  has_readable_inventory: boolean;
  visible_inventory_count: number;
  default_inventory_slug: string | null;
}

export interface InventoryTransferItemResultResponse {
  source_item_id: number;
  target_item_id: number | null;
  status: InventoryTransferItemStatus;
  source_removed: boolean;
  message: string | null;
}

type InventoryTransferRequestBase = {
  target_inventory_slug: string;
  mode: InventoryTransferMode;
  on_conflict: InventoryTransferConflictPolicy;
  keep_acquisition?: InventoryAcquisitionMergePolicy | null;
  dry_run?: boolean;
};

export type InventoryTransferRequest =
  | (InventoryTransferRequestBase & {
      item_ids: number[];
      all_items?: false | undefined;
    })
  | (InventoryTransferRequestBase & {
      all_items: true;
      item_ids?: never;
    });

export interface InventoryTransferResponse {
  source_inventory: string;
  target_inventory: string;
  mode: InventoryTransferMode;
  dry_run: boolean;
  selection_kind: InventoryTransferSelectionKind;
  requested_item_ids: number[] | null;
  requested_count: number;
  copied_count: number;
  moved_count: number;
  merged_count: number;
  failed_count: number;
  results_returned: number;
  results_truncated: boolean;
  results: InventoryTransferItemResultResponse[];
}

export interface InventoryDuplicateRequest {
  target_slug: string;
  target_display_name: string;
  target_description?: string | null;
}

export interface InventoryDuplicateResponse {
  source_inventory: string;
  inventory: InventoryCreateResponse;
  transfer: InventoryTransferResponse;
}

export type OwnedInventoryItemsPageSortKey =
  | "name"
  | "set"
  | "quantity"
  | "finish"
  | "condition_code"
  | "language_code"
  | "location"
  | "tags"
  | "est_value"
  | "item_id";

export type OwnedInventoryItemsPageSortDirection = "asc" | "desc";

export interface OwnedInventoryItemsPageParams {
  provider?: string;
  limit?: number | null;
  offset?: number | null;
  sort_key?: OwnedInventoryItemsPageSortKey | null;
  sort_direction?: OwnedInventoryItemsPageSortDirection | null;
  query?: string | null;
  set_code?: string | null;
  rarity?: string | null;
  finish?: FinishInput | null;
  condition_code?: ConditionCode | null;
  language_code?: LanguageCode | null;
  location?: string | null;
  tags?: string[] | null;
}

export interface OwnedInventoryItemsPageResponse {
  inventory: string;
  items: OwnedInventoryRow[];
  total_count: number;
  limit: number;
  offset: number;
  has_more: boolean;
  sort_key: OwnedInventoryItemsPageSortKey;
  sort_direction: OwnedInventoryItemsPageSortDirection;
}

export interface InventoryExportCsvParams {
  provider?: string;
  profile?: "default";
  limit?: number | null;
  query?: string | null;
  set_code?: string | null;
  rarity?: string | null;
  finish?: FinishInput | null;
  condition_code?: ConditionCode | null;
  language_code?: LanguageCode | null;
  location?: string | null;
  tags?: string[] | null;
}

export interface HealthResponse {
  status: string;
  auto_migrate: boolean;
  trusted_actor_headers: boolean;
}
