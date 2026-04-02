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


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryCreateRequest(ApiBaseModel):
    slug: str
    display_name: str
    description: str | None = None


class AddInventoryItemRequest(ApiBaseModel):
    scryfall_id: str | None = None
    tcgplayer_product_id: str | None = None
    name: str | None = None
    set_code: str | None = None
    collector_number: str | None = None
    lang: str | None = Field(default=None, description=SEARCH_LANG_DESCRIPTION)
    quantity: int = 1
    condition_code: str = Field(default=DEFAULT_CONDITION_CODE, description=CONDITION_CODE_DESCRIPTION)
    finish: FinishInput = Field(default=DEFAULT_FINISH, description=FINISH_INPUT_DESCRIPTION)
    language_code: str = Field(default=DEFAULT_LANGUAGE_CODE, description=LANGUAGE_CODE_DESCRIPTION)
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
