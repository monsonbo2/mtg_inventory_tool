"""Pydantic response models for the MTG Inventory Tool web API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..inventory.normalize import CANONICAL_CONDITION_CODES, CANONICAL_FINISHES, CANONICAL_LANGUAGE_CODES


_CANONICAL_FINISHES_TEXT = ", ".join(CANONICAL_FINISHES)
_CANONICAL_CONDITION_CODES_TEXT = ", ".join(CANONICAL_CONDITION_CODES)
_CANONICAL_LANGUAGE_CODES_TEXT = ", ".join(CANONICAL_LANGUAGE_CODES)

FINISH_RESPONSE_DESCRIPTION = f"Canonical finish values: {_CANONICAL_FINISHES_TEXT}."
CONDITION_CODE_RESPONSE_DESCRIPTION = (
    f"Canonical condition codes: {_CANONICAL_CONDITION_CODES_TEXT}. "
    "Stored rows are normally normalized to these values."
)
LANGUAGE_CODE_RESPONSE_DESCRIPTION = (
    f"Canonical language codes: {_CANONICAL_LANGUAGE_CODES_TEXT}. "
    "Stored rows are normally normalized to these values."
)
PRINTING_SELECTION_MODE_RESPONSE_DESCRIPTION = (
    "How the concrete printing was chosen. "
    "`explicit` means the caller directly identified the printing. "
    "`defaulted` means backend resolution selected the printing."
)
SEARCH_LANG_RESPONSE_DESCRIPTION = (
    f"Catalog language code. Common values include: {_CANONICAL_LANGUAGE_CODES_TEXT}."
)
AVAILABLE_LANGUAGES_RESPONSE_DESCRIPTION = (
    f"Catalog language codes available for the matched card. Common values include: {_CANONICAL_LANGUAGE_CODES_TEXT}."
)
DEFAULT_ADD_CHOICE_RESPONSE_DESCRIPTION = (
    "True when this printing matches the backend's current default quick-add choice for the same oracle_id. "
    "When omitted-finish quick-add would fail, every row is false."
)
SHARE_LINK_TOKEN_RESPONSE_DESCRIPTION = (
    "Reusable signed share token. Store/copy this only as part of the public share URL; it grants anonymous "
    "read-only access to this inventory's public share projection until rotated or revoked."
)
SHARE_LINK_PUBLIC_PATH_RESPONSE_DESCRIPTION = (
    "Browser-facing public share page path, for example `/shared/inventories/{share_token}`. "
    "In shared-service deployments, that page should fetch backend JSON through the proxied API route "
    "`/api/shared/inventories/{share_token}`; this field is not a proxy-aware API fetch URL."
)


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiErrorBody(ApiBaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiErrorResponse(ApiBaseModel):
    error: ApiErrorBody


class HealthResponse(ApiBaseModel):
    status: str
    auto_migrate: bool
    trusted_actor_headers: bool


class InventoryListRowResponse(ApiBaseModel):
    slug: str
    display_name: str
    description: str | None
    default_location: str | None
    default_tags: str | None
    notes: str | None
    acquisition_price: str | None
    acquisition_currency: str | None
    item_rows: int
    total_cards: int
    role: Literal["viewer", "editor", "owner", "admin"] | None
    can_read: bool
    can_write: bool
    can_manage_share: bool
    can_transfer_to: bool


class InventoryCreateResponse(ApiBaseModel):
    inventory_id: int
    slug: str
    display_name: str
    description: str | None
    default_location: str | None
    default_tags: str | None
    notes: str | None
    acquisition_price: str | None
    acquisition_currency: str | None


class InventoryMembershipResponse(ApiBaseModel):
    inventory: str
    actor_id: str
    role: Literal["viewer", "editor", "owner"]
    created_at: str
    updated_at: str


class InventoryMembershipRemovalResponse(ApiBaseModel):
    inventory: str
    actor_id: str
    role: Literal["viewer", "editor", "owner"]


class DefaultInventoryBootstrapResponse(ApiBaseModel):
    created: bool
    inventory: InventoryCreateResponse


class AccessSummaryResponse(ApiBaseModel):
    can_bootstrap: bool
    has_readable_inventory: bool
    visible_inventory_count: int
    default_inventory_slug: str | None


class InventoryShareLinkStatusResponse(ApiBaseModel):
    inventory: str
    active: bool
    public_path: str | None = Field(
        description=SHARE_LINK_PUBLIC_PATH_RESPONSE_DESCRIPTION,
    )
    created_at: str | None
    updated_at: str | None
    revoked_at: str | None


class InventoryShareLinkTokenResponse(ApiBaseModel):
    inventory: str
    token: str = Field(description=SHARE_LINK_TOKEN_RESPONSE_DESCRIPTION)
    public_path: str = Field(description=SHARE_LINK_PUBLIC_PATH_RESPONSE_DESCRIPTION)
    active: bool
    created_at: str
    updated_at: str
    revoked_at: str | None


class BulkInventoryItemMutationResponse(ApiBaseModel):
    inventory: str
    operation: Literal[
        "add_tags",
        "remove_tags",
        "set_tags",
        "clear_tags",
        "set_quantity",
        "set_notes",
        "set_acquisition",
        "set_finish",
        "set_location",
        "set_condition",
    ]
    selection_kind: Literal["items", "filtered", "all_items"]
    matched_count: int
    unchanged_count: int
    updated_item_ids: list[int]
    updated_count: int
    updated_item_ids_truncated: bool


class InventoryTransferItemResultResponse(ApiBaseModel):
    source_item_id: int
    target_item_id: int | None
    status: Literal["would_copy", "would_move", "would_merge", "would_fail", "copied", "moved", "merged"]
    source_removed: bool
    message: str | None


class InventoryTransferResponse(ApiBaseModel):
    source_inventory: str
    target_inventory: str
    mode: Literal["copy", "move"]
    dry_run: bool
    selection_kind: Literal["items", "all_items"]
    requested_item_ids: list[int] | None
    requested_count: int
    copied_count: int
    moved_count: int
    merged_count: int
    failed_count: int
    results_returned: int
    results_truncated: bool
    results: list[InventoryTransferItemResultResponse]


class InventoryDuplicateResponse(ApiBaseModel):
    source_inventory: str
    inventory: InventoryCreateResponse
    transfer: InventoryTransferResponse


class CatalogSearchRowResponse(ApiBaseModel):
    scryfall_id: str
    name: str
    set_code: str
    set_name: str
    collector_number: str
    lang: str = Field(description=SEARCH_LANG_RESPONSE_DESCRIPTION)
    rarity: str | None
    finishes: list[Literal["normal", "foil", "etched"]] = Field(description=FINISH_RESPONSE_DESCRIPTION)
    tcgplayer_product_id: str | None
    image_uri_small: str | None
    image_uri_normal: str | None


class CatalogPrintingLookupRowResponse(CatalogSearchRowResponse):
    is_default_add_choice: bool = Field(description=DEFAULT_ADD_CHOICE_RESPONSE_DESCRIPTION)


class CatalogPrintingSummaryResponse(ApiBaseModel):
    oracle_id: str
    default_printing: CatalogPrintingLookupRowResponse | None
    available_languages: list[str] = Field(description=AVAILABLE_LANGUAGES_RESPONSE_DESCRIPTION)
    printings_count: int
    has_more_printings: bool
    printings: list[CatalogPrintingLookupRowResponse]


class CatalogNameSearchRowResponse(ApiBaseModel):
    oracle_id: str
    name: str
    printings_count: int
    available_languages: list[str] = Field(description=AVAILABLE_LANGUAGES_RESPONSE_DESCRIPTION)
    image_uri_small: str | None
    image_uri_normal: str | None


class CatalogNameSearchResponse(ApiBaseModel):
    items: list[CatalogNameSearchRowResponse]
    total_count: int
    has_more: bool


class OwnedInventoryRowResponse(ApiBaseModel):
    item_id: int
    scryfall_id: str
    oracle_id: str
    name: str
    set_code: str
    set_name: str
    rarity: str | None
    collector_number: str
    image_uri_small: str | None
    image_uri_normal: str | None
    quantity: int
    condition_code: str = Field(description=CONDITION_CODE_RESPONSE_DESCRIPTION)
    finish: Literal["normal", "foil", "etched"] = Field(description=FINISH_RESPONSE_DESCRIPTION)
    allowed_finishes: list[Literal["normal", "foil", "etched"]] = Field(
        description=FINISH_RESPONSE_DESCRIPTION
    )
    language_code: str = Field(description=LANGUAGE_CODE_RESPONSE_DESCRIPTION)
    location: str | None
    tags: list[str]
    acquisition_price: str | None
    acquisition_currency: str | None
    currency: str | None
    unit_price: str | None
    est_value: str | None
    price_date: str | None
    notes: str | None
    printing_selection_mode: Literal["explicit", "defaulted"] = Field(
        description=PRINTING_SELECTION_MODE_RESPONSE_DESCRIPTION
    )


class OwnedInventoryItemsPageResponse(ApiBaseModel):
    inventory: str
    items: list[OwnedInventoryRowResponse]
    total_count: int
    limit: int
    offset: int
    has_more: bool
    sort_key: Literal[
        "name",
        "set",
        "quantity",
        "finish",
        "condition_code",
        "language_code",
        "location",
        "tags",
        "est_value",
        "item_id",
    ]
    sort_direction: Literal["asc", "desc"]


class PublicInventorySummaryResponse(ApiBaseModel):
    display_name: str
    description: str | None
    item_rows: int
    total_cards: int


class PublicInventoryItemResponse(ApiBaseModel):
    scryfall_id: str
    oracle_id: str
    name: str
    set_code: str
    set_name: str
    rarity: str | None
    collector_number: str
    image_uri_small: str | None
    image_uri_normal: str | None
    quantity: int
    condition_code: str = Field(description=CONDITION_CODE_RESPONSE_DESCRIPTION)
    finish: Literal["normal", "foil", "etched"] = Field(description=FINISH_RESPONSE_DESCRIPTION)
    allowed_finishes: list[Literal["normal", "foil", "etched"]] = Field(
        description=FINISH_RESPONSE_DESCRIPTION
    )
    language_code: str = Field(description=LANGUAGE_CODE_RESPONSE_DESCRIPTION)


class PublicInventoryShareResponse(ApiBaseModel):
    inventory: PublicInventorySummaryResponse
    items: list[PublicInventoryItemResponse]


class InventoryAuditEventResponse(ApiBaseModel):
    id: int
    inventory: str
    item_id: int | None
    action: str
    actor_type: str
    actor_id: str | None
    request_id: str | None
    occurred_at: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    metadata: dict[str, Any]


class InventoryItemMutationBaseResponse(ApiBaseModel):
    inventory: str
    card_name: str
    oracle_id: str
    set_code: str
    set_name: str
    collector_number: str
    scryfall_id: str
    item_id: int
    quantity: int
    finish: Literal["normal", "foil", "etched"] = Field(description=FINISH_RESPONSE_DESCRIPTION)
    condition_code: str = Field(description=CONDITION_CODE_RESPONSE_DESCRIPTION)
    language_code: str = Field(description=LANGUAGE_CODE_RESPONSE_DESCRIPTION)
    location: str | None
    acquisition_price: str | None
    acquisition_currency: str | None
    notes: str | None
    tags: list[str]
    printing_selection_mode: Literal["explicit", "defaulted"] = Field(
        description=PRINTING_SELECTION_MODE_RESPONSE_DESCRIPTION
    )


class CsvImportRowResponse(InventoryItemMutationBaseResponse):
    csv_row: int


class ImportSummaryResponse(ApiBaseModel):
    total_card_quantity: int
    distinct_card_names: int
    distinct_printings: int


class DeckImportSummaryResponse(ImportSummaryResponse):
    section_card_quantities: dict[str, int]


class CsvImportSummaryResponse(ImportSummaryResponse):
    requested_card_quantity: int
    unresolved_card_quantity: int


class DecklistImportSummaryResponse(DeckImportSummaryResponse):
    requested_card_quantity: int
    unresolved_card_quantity: int


class DeckUrlImportSummaryResponse(DeckImportSummaryResponse):
    requested_card_quantity: int
    unresolved_card_quantity: int


class DecklistImportRowResponse(InventoryItemMutationBaseResponse):
    decklist_line: int
    section: str


class DecklistImportRequestedCardResponse(ApiBaseModel):
    name: str
    quantity: int
    set_code: str | None
    collector_number: str | None
    finish: Literal["normal", "foil", "etched"] | None = Field(default=None, description=FINISH_RESPONSE_DESCRIPTION)


class ImportResolutionOptionResponse(ApiBaseModel):
    scryfall_id: str
    finish: Literal["normal", "foil", "etched"] = Field(description=FINISH_RESPONSE_DESCRIPTION)
    name: str
    set_code: str
    set_name: str
    collector_number: str
    lang: str = Field(description=SEARCH_LANG_RESPONSE_DESCRIPTION)
    image_uri_small: str | None
    image_uri_normal: str | None


class DecklistImportResolutionIssueResponse(ApiBaseModel):
    kind: Literal["ambiguous_card_name", "ambiguous_printing", "finish_required"]
    decklist_line: int
    section: str
    requested: DecklistImportRequestedCardResponse
    options: list[ImportResolutionOptionResponse]


class CsvImportRequestedCardResponse(ApiBaseModel):
    scryfall_id: str | None
    oracle_id: str | None
    tcgplayer_product_id: str | None
    name: str | None
    quantity: int
    set_code: str | None
    set_name: str | None
    collector_number: str | None
    lang: str | None = Field(default=None, description=SEARCH_LANG_RESPONSE_DESCRIPTION)
    finish: Literal["normal", "foil", "etched"] | None = Field(default=None, description=FINISH_RESPONSE_DESCRIPTION)


class CsvImportResolutionIssueResponse(ApiBaseModel):
    kind: Literal["ambiguous_card_name", "ambiguous_printing", "finish_required"]
    csv_row: int
    requested: CsvImportRequestedCardResponse
    options: list[ImportResolutionOptionResponse]


class CsvImportResponse(ApiBaseModel):
    csv_filename: str
    detected_format: str
    default_inventory: str | None
    rows_seen: int
    rows_written: int
    ready_to_commit: bool
    summary: CsvImportSummaryResponse
    resolution_issues: list[CsvImportResolutionIssueResponse]
    dry_run: bool
    imported_rows: list[CsvImportRowResponse]


class DecklistImportResponse(ApiBaseModel):
    deck_name: str | None
    default_inventory: str | None
    rows_seen: int
    rows_written: int
    ready_to_commit: bool
    summary: DecklistImportSummaryResponse
    resolution_issues: list[DecklistImportResolutionIssueResponse]
    dry_run: bool
    imported_rows: list[DecklistImportRowResponse]


class DeckUrlImportRowResponse(InventoryItemMutationBaseResponse):
    source_position: int
    section: str


class DeckUrlImportRequestedCardResponse(ApiBaseModel):
    name: str | None
    quantity: int
    set_code: str | None
    collector_number: str | None
    finish: Literal["normal", "foil", "etched"] | None = Field(default=None, description=FINISH_RESPONSE_DESCRIPTION)


class DeckUrlImportResolutionIssueResponse(ApiBaseModel):
    kind: Literal["ambiguous_card_name", "ambiguous_printing", "finish_required"]
    source_position: int
    section: str
    requested: DeckUrlImportRequestedCardResponse
    options: list[ImportResolutionOptionResponse]


class DeckUrlImportResponse(ApiBaseModel):
    source_url: str
    provider: str
    deck_name: str | None
    default_inventory: str | None
    rows_seen: int
    rows_written: int
    ready_to_commit: bool
    source_snapshot_token: str | None
    summary: DeckUrlImportSummaryResponse
    resolution_issues: list[DeckUrlImportResolutionIssueResponse]
    dry_run: bool
    imported_rows: list[DeckUrlImportRowResponse]


class AddInventoryItemResponse(InventoryItemMutationBaseResponse):
    pass


class RemoveInventoryItemResponse(InventoryItemMutationBaseResponse):
    pass


class SetQuantityResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_quantity"]
    old_quantity: int


class SetFinishResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_finish"]
    old_finish: str


class SetPrintingResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_printing"]
    old_scryfall_id: str
    old_finish: str
    old_language_code: str = Field(description=LANGUAGE_CODE_RESPONSE_DESCRIPTION)
    merged: bool
    merged_source_item_id: int | None = None


class SetLocationResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_location"]
    old_location: str | None
    merged: bool
    merged_source_item_id: int | None = None


class SetConditionResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_condition"]
    old_condition_code: str
    merged: bool
    merged_source_item_id: int | None = None


class SetNotesResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_notes"]
    old_notes: str | None


class SetTagsResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_tags"]
    old_tags: list[str]


class SetAcquisitionResponse(InventoryItemMutationBaseResponse):
    operation: Literal["set_acquisition"]
    old_acquisition_price: str | None
    old_acquisition_currency: str | None


InventoryItemPatchResponse = (
    SetQuantityResponse
    | SetFinishResponse
    | SetLocationResponse
    | SetConditionResponse
    | SetNotesResponse
    | SetTagsResponse
    | SetAcquisitionResponse
)
