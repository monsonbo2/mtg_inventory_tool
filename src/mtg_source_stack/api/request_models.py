"""Pydantic request models for the MTG Inventory Tool web API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..inventory.normalize import (
    ACCEPTED_FINISH_INPUTS,
    CANONICAL_CONDITION_CODES,
    CANONICAL_FINISHES,
    CANONICAL_LANGUAGE_CODES,
    DEFAULT_CONDITION_CODE,
    DEFAULT_FINISH,
    DEFAULT_LANGUAGE_CODE,
)


FinishInput = Literal["normal", "nonfoil", "foil", "etched"]

_CANONICAL_FINISHES_TEXT = ", ".join(CANONICAL_FINISHES)
_ACCEPTED_FINISH_INPUTS_TEXT = ", ".join(ACCEPTED_FINISH_INPUTS)
_CANONICAL_CONDITION_CODES_TEXT = ", ".join(CANONICAL_CONDITION_CODES)
_CANONICAL_LANGUAGE_CODES_TEXT = ", ".join(CANONICAL_LANGUAGE_CODES)

FINISH_INPUT_DESCRIPTION = (
    f"Accepted input values: {_ACCEPTED_FINISH_INPUTS_TEXT}. "
    f"Canonical response values: {_CANONICAL_FINISHES_TEXT}. "
    "The input alias `nonfoil` is normalized to `normal`."
)
CONDITION_CODE_DESCRIPTION = (
    f"Canonical condition codes: {_CANONICAL_CONDITION_CODES_TEXT}. "
    f"Default: {DEFAULT_CONDITION_CODE}. Human-readable aliases such as "
    "`near mint` and `lightly played` are accepted and normalized."
)
LANGUAGE_CODE_DESCRIPTION = (
    f"Canonical language codes: {_CANONICAL_LANGUAGE_CODES_TEXT}. "
    f"Default: {DEFAULT_LANGUAGE_CODE}. Common language-name aliases such as "
    "`english` and `japanese` are accepted and normalized."
)
ADD_LANGUAGE_CODE_DESCRIPTION = (
    f"Canonical language codes: {_CANONICAL_LANGUAGE_CODES_TEXT}. "
    "When omitted, the added inventory row inherits the resolved printing language. "
    "Common language-name aliases such as `english` and `japanese` are accepted and normalized."
)
ORACLE_ID_ADD_DESCRIPTION = (
    "Card-level Oracle ID to resolve to one default printing by backend policy. "
    "When language is omitted, quick-add prefers English mainstream-paper printings "
    "in the default add scope before newer promo-like rows."
)
SEARCH_LANG_DESCRIPTION = (
    f"Catalog search language filter. Recommended codes include: {_CANONICAL_LANGUAGE_CODES_TEXT}. "
    "Search currently accepts the raw stored catalog language codes."
)
PATCH_REQUEST_DESCRIPTION = (
    "Specify exactly one mutation family per request: quantity, finish, location, "
    "condition_code, notes, tags, or acquisition. PATCH does not currently support "
    "true multi-field updates in one request."
)
PATCH_MERGE_DESCRIPTION = (
    "Only applies to location or condition changes. When true, a collision with an existing "
    "row is merged instead of returning a conflict."
)
PATCH_KEEP_ACQUISITION_DESCRIPTION = (
    "Only applies to merged location or condition changes. Choose whether the merged row keeps "
    "the target row or source row acquisition metadata."
)
BULK_ITEM_MUTATION_REQUEST_DESCRIPTION = (
    "Specify exactly one bulk mutation operation per request. "
    "The current runtime supports add_tags, remove_tags, set_tags, clear_tags, "
    "set_quantity, set_notes, set_acquisition, set_finish, set_location, and set_condition."
)
BULK_TAGS_DESCRIPTION = (
    "Required for add_tags, remove_tags, and set_tags. Omit this field for clear_tags. "
    "Omit this field for non-tag bulk operations."
)
BULK_QUANTITY_DESCRIPTION = (
    "Required for set_quantity. Omit this field for every other bulk operation."
)
BULK_NOTES_DESCRIPTION = (
    "Used by set_notes. Provide notes to set/replace notes, or omit it when clear_notes is true. "
    "Omit this field for every other bulk operation."
)
BULK_CLEAR_NOTES_DESCRIPTION = (
    "Only applies to set_notes. When true, notes must be omitted and notes are cleared."
)
BULK_ACQUISITION_PRICE_DESCRIPTION = (
    "Used by set_acquisition. Provide this field to set/replace acquisition_price. "
    "Omit this field for every other bulk operation."
)
BULK_ACQUISITION_CURRENCY_DESCRIPTION = (
    "Used by set_acquisition. Provide this field to set/replace acquisition_currency. "
    "Omit this field for every other bulk operation."
)
BULK_CLEAR_ACQUISITION_DESCRIPTION = (
    "Only applies to set_acquisition. When true, acquisition_price and acquisition_currency are cleared."
)
BULK_FINISH_DESCRIPTION = (
    f"Used by set_finish. Accepted input values: {_ACCEPTED_FINISH_INPUTS_TEXT}. "
    f"Canonical response values: {_CANONICAL_FINISHES_TEXT}. "
    "The input alias `nonfoil` is normalized to `normal`. Omit this field for every other bulk operation."
)
BULK_LOCATION_DESCRIPTION = (
    "Used by set_location. Provide a location to set/replace location, or omit it when "
    "clear_location is true. Omit this field for every other bulk operation."
)
BULK_CLEAR_LOCATION_DESCRIPTION = (
    "Only applies to set_location. When true, location must be omitted and location is cleared."
)
BULK_MERGE_DESCRIPTION = (
    "Only applies to set_location or set_condition. When true, a collision with an existing "
    "row is merged instead of returning a conflict."
)
BULK_KEEP_ACQUISITION_DESCRIPTION = (
    "Only applies to merged set_location or set_condition changes. Choose whether the merged "
    "row keeps the target row or source row acquisition metadata."
)
BULK_CONDITION_CODE_DESCRIPTION = (
    f"Used by set_condition. Canonical condition codes: {_CANONICAL_CONDITION_CODES_TEXT}. "
    "Human-readable aliases such as `near mint` and `lightly played` are accepted and normalized. "
    "Omit this field for every other bulk operation."
)


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryCreateRequest(ApiBaseModel):
    slug: str
    display_name: str
    description: str | None = None


class AddInventoryItemRequest(ApiBaseModel):
    scryfall_id: str | None = None
    oracle_id: str | None = Field(default=None, description=ORACLE_ID_ADD_DESCRIPTION)
    tcgplayer_product_id: str | None = None
    name: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    lang: str | None = Field(default=None, description=SEARCH_LANG_DESCRIPTION)
    quantity: int = 1
    condition_code: str = Field(default=DEFAULT_CONDITION_CODE, description=CONDITION_CODE_DESCRIPTION)
    finish: FinishInput = Field(default=DEFAULT_FINISH, description=FINISH_INPUT_DESCRIPTION)
    language_code: str | None = Field(default=None, description=ADD_LANGUAGE_CODE_DESCRIPTION)
    location: str = ""
    acquisition_price: str | None = None
    acquisition_currency: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class PatchInventoryItemRequest(ApiBaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": PATCH_REQUEST_DESCRIPTION},
    )

    quantity: int | None = None
    finish: FinishInput | None = Field(default=None, description=FINISH_INPUT_DESCRIPTION)
    location: str | None = None
    clear_location: bool = False
    condition_code: str | None = Field(default=None, description=CONDITION_CODE_DESCRIPTION)
    merge: bool = Field(default=False, description=PATCH_MERGE_DESCRIPTION)
    keep_acquisition: Literal["target", "source"] | None = Field(
        default=None,
        description=PATCH_KEEP_ACQUISITION_DESCRIPTION,
    )
    notes: str | None = None
    clear_notes: bool = False
    tags: list[str] | None = None
    clear_tags: bool = False
    acquisition_price: str | None = None
    acquisition_currency: str | None = None
    clear_acquisition: bool = False


class BulkInventoryItemMutationRequest(ApiBaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": BULK_ITEM_MUTATION_REQUEST_DESCRIPTION},
    )

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
    item_ids: list[int] = Field(min_length=1, max_length=100)
    tags: list[str] | None = Field(default=None, description=BULK_TAGS_DESCRIPTION)
    quantity: int | None = Field(default=None, description=BULK_QUANTITY_DESCRIPTION)
    notes: str | None = Field(default=None, description=BULK_NOTES_DESCRIPTION)
    clear_notes: bool = Field(default=False, description=BULK_CLEAR_NOTES_DESCRIPTION)
    acquisition_price: str | None = Field(default=None, description=BULK_ACQUISITION_PRICE_DESCRIPTION)
    acquisition_currency: str | None = Field(default=None, description=BULK_ACQUISITION_CURRENCY_DESCRIPTION)
    clear_acquisition: bool = Field(default=False, description=BULK_CLEAR_ACQUISITION_DESCRIPTION)
    finish: FinishInput | None = Field(default=None, description=BULK_FINISH_DESCRIPTION)
    location: str | None = Field(default=None, description=BULK_LOCATION_DESCRIPTION)
    clear_location: bool = Field(default=False, description=BULK_CLEAR_LOCATION_DESCRIPTION)
    condition_code: str | None = Field(default=None, description=BULK_CONDITION_CODE_DESCRIPTION)
    merge: bool = Field(default=False, description=BULK_MERGE_DESCRIPTION)
    keep_acquisition: Literal["target", "source"] | None = Field(
        default=None,
        description=BULK_KEEP_ACQUISITION_DESCRIPTION,
    )
