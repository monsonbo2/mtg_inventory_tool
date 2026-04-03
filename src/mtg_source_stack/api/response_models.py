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
SEARCH_LANG_RESPONSE_DESCRIPTION = (
    f"Catalog language code. Common values include: {_CANONICAL_LANGUAGE_CODES_TEXT}."
)
AVAILABLE_LANGUAGES_RESPONSE_DESCRIPTION = (
    f"Catalog language codes available for the matched card. Common values include: {_CANONICAL_LANGUAGE_CODES_TEXT}."
)


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApiErrorBody(ApiBaseModel):
    code: str
    message: str


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
    item_rows: int
    total_cards: int


class InventoryCreateResponse(ApiBaseModel):
    inventory_id: int
    slug: str
    display_name: str
    description: str | None


class DefaultInventoryBootstrapResponse(ApiBaseModel):
    created: bool
    inventory: InventoryCreateResponse


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
    requested_item_ids: list[int]
    updated_item_ids: list[int]
    updated_count: int


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


class CatalogNameSearchRowResponse(ApiBaseModel):
    oracle_id: str
    name: str
    printings_count: int
    available_languages: list[str] = Field(description=AVAILABLE_LANGUAGES_RESPONSE_DESCRIPTION)
    image_uri_small: str | None
    image_uri_normal: str | None


class OwnedInventoryRowResponse(ApiBaseModel):
    item_id: int
    scryfall_id: str
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
