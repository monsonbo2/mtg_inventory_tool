"""Pydantic response models for the local-demo web API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


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


class CatalogSearchRowResponse(ApiBaseModel):
    scryfall_id: str
    name: str
    set_code: str
    set_name: str
    collector_number: str
    lang: str
    rarity: str | None
    finishes: list[str]
    tcgplayer_product_id: str | None


class OwnedInventoryRowResponse(ApiBaseModel):
    item_id: int
    scryfall_id: str
    name: str
    set_code: str
    set_name: str
    rarity: str | None
    collector_number: str
    quantity: int
    condition_code: str
    finish: str
    language_code: str
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
    finish: str
    condition_code: str
    language_code: str
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
    old_quantity: int


class SetFinishResponse(InventoryItemMutationBaseResponse):
    old_finish: str


class SetLocationResponse(InventoryItemMutationBaseResponse):
    old_location: str | None
    merged: bool
    merged_source_item_id: int | None = None


class SetConditionResponse(InventoryItemMutationBaseResponse):
    old_condition_code: str
    merged: bool
    merged_source_item_id: int | None = None


class SetNotesResponse(InventoryItemMutationBaseResponse):
    old_notes: str | None


class SetTagsResponse(InventoryItemMutationBaseResponse):
    old_tags: list[str]


class SetAcquisitionResponse(InventoryItemMutationBaseResponse):
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
