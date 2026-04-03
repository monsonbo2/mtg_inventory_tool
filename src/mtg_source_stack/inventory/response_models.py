"""Typed service response models for API-facing inventory operations."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

from .money import format_decimal
from .normalize import text_or_none


class ResponseModel:
    """Common serializer so service models can be written to JSON cleanly."""

    def to_dict(self) -> dict[str, Any]:
        serialized = serialize_response(self)
        if not isinstance(serialized, dict):
            raise TypeError("ResponseModel.to_dict() expected a dataclass-backed mapping.")
        return serialized


def serialize_response(value: Any) -> Any:
    # JSON-facing responses keep money values as decimal strings so callers do
    # not inherit binary-float surprises from Python or JavaScript runtimes.
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        return format_decimal(value)
    if is_dataclass(value):
        return {field.name: serialize_response(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, list):
        return [serialize_response(item) for item in value]
    if isinstance(value, tuple):
        return [serialize_response(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_response(item) for key, item in value.items()}
    return value


def inventory_item_response_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the common inventory item fields shared by write responses."""

    return {
        "inventory": payload["inventory"],
        "card_name": payload["card_name"],
        "set_code": payload["set_code"],
        "set_name": payload["set_name"],
        "collector_number": payload["collector_number"],
        "scryfall_id": payload["scryfall_id"],
        "item_id": payload["item_id"],
        "quantity": payload["quantity"],
        "finish": payload["finish"],
        "condition_code": payload["condition_code"],
        "language_code": payload["language_code"],
        "location": text_or_none(payload["location"]),
        "acquisition_price": payload["acquisition_price"],
        "acquisition_currency": payload["acquisition_currency"],
        "notes": payload["notes"],
        "tags": list(payload["tags"]),
    }


@dataclass(frozen=True, slots=True)
class CatalogSearchRow(ResponseModel):
    scryfall_id: str
    name: str
    set_code: str
    set_name: str
    collector_number: str
    lang: str
    rarity: str | None
    finishes: list[str]
    tcgplayer_product_id: str | None
    image_uri_small: str | None
    image_uri_normal: str | None


@dataclass(frozen=True, slots=True)
class CatalogNameSearchRow(ResponseModel):
    oracle_id: str
    name: str
    printings_count: int
    available_languages: list[str]
    image_uri_small: str | None
    image_uri_normal: str | None


@dataclass(frozen=True, slots=True)
class InventoryListRow(ResponseModel):
    slug: str
    display_name: str
    description: str | None
    item_rows: int
    total_cards: int


@dataclass(frozen=True, slots=True)
class InventoryCreateResult(ResponseModel):
    inventory_id: int
    slug: str
    display_name: str
    description: str | None


@dataclass(frozen=True, slots=True)
class DefaultInventoryBootstrapResult(ResponseModel):
    created: bool
    inventory: InventoryCreateResult


@dataclass(frozen=True, slots=True)
class BulkInventoryItemMutationResult(ResponseModel):
    inventory: str
    operation: str
    requested_item_ids: list[int]
    updated_item_ids: list[int]
    updated_count: int


@dataclass(frozen=True, slots=True)
class InventoryAuditEvent(ResponseModel):
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


@dataclass(frozen=True, slots=True)
class OwnedInventoryRow(ResponseModel):
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
    condition_code: str
    finish: str
    allowed_finishes: list[str]
    language_code: str
    location: str | None
    tags: list[str]
    acquisition_price: Decimal | None
    acquisition_currency: str | None
    currency: str | None
    unit_price: Decimal | None
    est_value: Decimal | None
    price_date: str | None
    notes: str | None


@dataclass(frozen=True, slots=True)
class InventoryItemMutationRow(ResponseModel):
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
    acquisition_price: Decimal | None
    acquisition_currency: str | None
    notes: str | None
    tags: list[str]


@dataclass(frozen=True, slots=True)
class AddCardResult(InventoryItemMutationRow):
    pass


@dataclass(frozen=True, slots=True)
class SetQuantityResult(InventoryItemMutationRow):
    operation: str
    old_quantity: int


@dataclass(frozen=True, slots=True)
class RemoveCardResult(InventoryItemMutationRow):
    pass


@dataclass(frozen=True, slots=True)
class SetTagsResult(InventoryItemMutationRow):
    operation: str
    old_tags: list[str]


@dataclass(frozen=True, slots=True)
class SetFinishResult(InventoryItemMutationRow):
    operation: str
    old_finish: str


@dataclass(frozen=True, slots=True)
class SetLocationResult(InventoryItemMutationRow):
    operation: str
    old_location: str | None
    merged: bool
    merged_source_item_id: int | None = None


@dataclass(frozen=True, slots=True)
class SetConditionResult(InventoryItemMutationRow):
    operation: str
    old_condition_code: str
    merged: bool
    merged_source_item_id: int | None = None


@dataclass(frozen=True, slots=True)
class SetNotesResult(InventoryItemMutationRow):
    operation: str
    old_notes: str | None


@dataclass(frozen=True, slots=True)
class SetAcquisitionResult(InventoryItemMutationRow):
    operation: str
    old_acquisition_price: Decimal | None
    old_acquisition_currency: str | None


@dataclass(frozen=True, slots=True)
class SplitRowResult(InventoryItemMutationRow):
    merged_into_existing: bool
    source_item_id: int
    source_old_quantity: int
    source_quantity: int
    source_deleted: bool
    moved_quantity: int


@dataclass(frozen=True, slots=True)
class MergeRowsResult(InventoryItemMutationRow):
    merged_source_item_id: int
    source_quantity: int
    target_old_quantity: int


@dataclass(frozen=True, slots=True)
class PriceGapRow(ResponseModel):
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
    acquisition_price: Decimal | None
    acquisition_currency: str | None
    notes: str | None
    tags: list[str]
    available_finishes: list[str]
    suggested_finish: str | None
    reconcile_status: str


@dataclass(frozen=True, slots=True)
class ReconcilePricesResult(ResponseModel):
    inventory: str
    provider: str
    rows_seen: int
    rows_fixable: int
    suggested_rows: list[PriceGapRow]
    remaining_rows: list[PriceGapRow]


@dataclass(frozen=True, slots=True)
class InventoryHealthSummary(ResponseModel):
    item_rows: int
    total_cards: int
    missing_price_rows: int
    missing_location_rows: int
    missing_tag_rows: int
    merge_note_rows: int
    stale_price_rows: int
    duplicate_groups: int


@dataclass(frozen=True, slots=True)
class MissingPricePreviewRow(ResponseModel):
    item_id: int
    name: str
    set: str
    number: str
    finish: str
    priced_finishes: str
    status: str


@dataclass(frozen=True, slots=True)
class HealthItemPreviewRow(ResponseModel):
    item_id: int
    name: str
    set: str
    number: str
    qty: int
    cond: str
    finish: str
    location: str
    tags: str
    note: str


@dataclass(frozen=True, slots=True)
class StalePricePreviewRow(ResponseModel):
    item_id: int
    name: str
    set: str
    number: str
    finish: str
    price_date: str
    age_days: int


@dataclass(frozen=True, slots=True)
class DuplicateGroupRow(ResponseModel):
    scryfall_id: str
    condition_code: str
    language_code: str
    name: str
    set: str
    number: str
    cond: str
    finish: str
    rows: int
    qty: int
    locations: str


@dataclass(frozen=True, slots=True)
class InventoryHealthResult(ResponseModel):
    inventory: str
    provider: str
    stale_days: int
    current_date: str
    preview_limit: int
    summary: InventoryHealthSummary
    missing_price_rows: list[MissingPricePreviewRow]
    missing_location_rows: list[HealthItemPreviewRow]
    missing_tag_rows: list[HealthItemPreviewRow]
    merge_note_rows: list[HealthItemPreviewRow]
    stale_price_rows: list[StalePricePreviewRow]
    duplicate_groups: list[DuplicateGroupRow]


@dataclass(frozen=True, slots=True)
class ExportInventoryCsvResult(ResponseModel):
    inventory: str
    provider: str
    output_path: str
    rows_exported: int
    filters_text: str
    rows: list[OwnedInventoryRow]


@dataclass(frozen=True, slots=True)
class ValuationRow(ResponseModel):
    provider: str | None
    currency: str | None
    item_rows: int
    total_cards: int
    total_value: Decimal


@dataclass(frozen=True, slots=True)
class CurrencyTotalRow(ResponseModel):
    currency: str
    item_rows: int
    total_cards: int
    total_amount: Decimal


@dataclass(frozen=True, slots=True)
class TopValueRow(ResponseModel):
    item_id: int
    name: str
    set: str
    number: str
    qty: int
    finish: str
    location: str
    est_value: Decimal | None
    currency: str | None


@dataclass(frozen=True, slots=True)
class InventoryReportSummary(ResponseModel):
    item_rows: int
    total_cards: int
    unique_printings: int
    unique_card_names: int
    valued_rows: int
    unpriced_rows: int


@dataclass(frozen=True, slots=True)
class InventoryReportResult(ResponseModel):
    generated_at: str
    inventory: str
    provider: str
    filters_text: str
    summary: InventoryReportSummary
    valuation_rows: list[ValuationRow]
    acquisition_totals: list[CurrencyTotalRow]
    top_rows: list[TopValueRow]
    health: InventoryHealthResult
    rows: list[OwnedInventoryRow]
