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
SET_PRINTING_REQUEST_DESCRIPTION = (
    "Change an existing owned row to a different printing of the same oracle card. "
    "Clients may also resubmit the current scryfall_id to confirm a defaulted row as explicit "
    "when finish and language stay unchanged. "
    "When finish is omitted, the backend keeps the current finish if the target printing supports it; "
    "otherwise it auto-selects the first supported finish in normal > foil > etched order."
)
SET_PRINTING_FINISH_DESCRIPTION = (
    f"Optional explicit target finish. Accepted input values: {_ACCEPTED_FINISH_INPUTS_TEXT}. "
    f"Canonical response values: {_CANONICAL_FINISHES_TEXT}. "
    "When omitted, the backend preserves the current finish if valid on the target printing; "
    "otherwise it auto-selects the first supported finish in normal > foil > etched order. "
    "Resubmitting the current scryfall_id is confirmation-only and cannot be used as a same-printing "
    "finish change."
)
SET_PRINTING_MERGE_DESCRIPTION = (
    "When true, a collision with an existing row identity after the printing change is merged "
    "instead of returning a conflict."
)
SET_PRINTING_KEEP_ACQUISITION_DESCRIPTION = (
    "Only applies when merge is true for printing changes. Choose whether the merged row keeps "
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
TRANSFER_REQUEST_DESCRIPTION = (
    "Transfer selected inventory rows, or the entire source inventory, into another inventory. "
    "The live mutation is atomic and all-or-nothing; if any requested row would fail, no rows are "
    "transferred. Use dry_run=true to preview copy, move, merge, or failure outcomes without "
    "mutating either inventory."
)
TRANSFER_MODE_DESCRIPTION = "Transfer mode. Use `copy` to leave source rows in place or `move` to remove them."
TRANSFER_CONFLICT_DESCRIPTION = (
    "Conflict policy for target-inventory row identity collisions. Use `fail` to reject duplicate rows "
    "or `merge` to combine rows using the existing inventory merge rules."
)
TRANSFER_KEEP_ACQUISITION_DESCRIPTION = (
    "Only applies when on_conflict is `merge`. Choose whether merged target rows keep the source row "
    "or target row acquisition metadata."
)
TRANSFER_DRY_RUN_DESCRIPTION = (
    "When true, return the planned transfer outcomes without mutating either inventory."
)
TRANSFER_ALL_ITEMS_DESCRIPTION = (
    "When true, transfer every row in the source inventory. Use either item_ids or all_items=true, not both."
)
DUPLICATE_REQUEST_DESCRIPTION = (
    "Create a new inventory and copy every source inventory row into it atomically. "
    "If duplication fails, the new inventory is not created."
)
DUPLICATE_DESCRIPTION_FALLBACK = (
    "Optional description for the duplicated inventory. When omitted, the source inventory description is copied."
)
DECKLIST_IMPORT_TEXT_DESCRIPTION = (
    "Pasted decklist text. Supported v1 forms include '4 Lightning Bolt', '4x Lightning Bolt', "
    "'SB: 2 Pyroblast', exact-printing hints like '3 Verdant Catacombs (MH2) 260', "
    "and exported deck text with preambles like 'About' / 'Name <deck>' from deck sites such as Moxfield."
)
DECKLIST_IMPORT_DEFAULT_INVENTORY_DESCRIPTION = "Target inventory slug for the pasted decklist import."
DECKLIST_IMPORT_DRY_RUN_DESCRIPTION = (
    "When true, validate and resolve the import using the real add-card workflow but roll back before commit."
)
DECKLIST_IMPORT_RESOLUTIONS_DESCRIPTION = (
    "Optional explicit row resolutions for ambiguous decklist lines. "
    "Each item selects one suggested printing and finish for a specific decklist_line."
)
DECK_URL_IMPORT_SOURCE_URL_DESCRIPTION = (
    "Public deck URL to import. V1 currently supports Archidekt, AetherHub, ManaBox, "
    "Moxfield, MTGGoldfish, MTGTop8, and TappedOut deck URLs."
)
DECK_URL_IMPORT_DEFAULT_INVENTORY_DESCRIPTION = "Target inventory slug for the remote deck URL import."
DECK_URL_IMPORT_DRY_RUN_DESCRIPTION = DECKLIST_IMPORT_DRY_RUN_DESCRIPTION
DECK_URL_IMPORT_RESOLUTIONS_DESCRIPTION = (
    "Optional explicit row resolutions for ambiguous remote deck rows. "
    "Each item selects one suggested printing and finish for a specific source_position."
)
DECK_URL_IMPORT_SOURCE_SNAPSHOT_TOKEN_DESCRIPTION = (
    "Optional snapshot token returned by a prior dry-run deck URL import. "
    "When supplied, the backend reuses the short-lived signed normalized remote deck payload "
    "instead of refetching the provider."
)


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryCreateRequest(ApiBaseModel):
    slug: str
    display_name: str
    description: str | None = None
    default_location: str | None = None
    default_tags: str | None = None
    notes: str | None = None
    acquisition_price: str | None = None
    acquisition_currency: str | None = None


class DecklistImportResolutionRequest(ApiBaseModel):
    decklist_line: int
    scryfall_id: str
    finish: FinishInput = Field(description=FINISH_INPUT_DESCRIPTION)


class DecklistImportRequest(ApiBaseModel):
    deck_text: str = Field(description=DECKLIST_IMPORT_TEXT_DESCRIPTION)
    default_inventory: str = Field(description=DECKLIST_IMPORT_DEFAULT_INVENTORY_DESCRIPTION)
    dry_run: bool = Field(default=False, description=DECKLIST_IMPORT_DRY_RUN_DESCRIPTION)
    resolutions: list[DecklistImportResolutionRequest] = Field(
        default_factory=list,
        description=DECKLIST_IMPORT_RESOLUTIONS_DESCRIPTION,
    )


class DeckUrlImportResolutionRequest(ApiBaseModel):
    source_position: int
    scryfall_id: str
    finish: FinishInput = Field(description=FINISH_INPUT_DESCRIPTION)


class DeckUrlImportRequest(ApiBaseModel):
    source_url: str = Field(description=DECK_URL_IMPORT_SOURCE_URL_DESCRIPTION)
    default_inventory: str = Field(description=DECK_URL_IMPORT_DEFAULT_INVENTORY_DESCRIPTION)
    dry_run: bool = Field(default=False, description=DECK_URL_IMPORT_DRY_RUN_DESCRIPTION)
    source_snapshot_token: str | None = Field(
        default=None,
        description=DECK_URL_IMPORT_SOURCE_SNAPSHOT_TOKEN_DESCRIPTION,
    )
    resolutions: list[DeckUrlImportResolutionRequest] = Field(
        default_factory=list,
        description=DECK_URL_IMPORT_RESOLUTIONS_DESCRIPTION,
    )


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


class SetInventoryItemPrintingRequest(ApiBaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": SET_PRINTING_REQUEST_DESCRIPTION},
    )

    scryfall_id: str
    finish: FinishInput | None = Field(default=None, description=SET_PRINTING_FINISH_DESCRIPTION)
    merge: bool = Field(default=False, description=SET_PRINTING_MERGE_DESCRIPTION)
    keep_acquisition: Literal["target", "source"] | None = Field(
        default=None,
        description=SET_PRINTING_KEEP_ACQUISITION_DESCRIPTION,
    )


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
    item_ids: list[int] = Field(min_length=1, max_length=200)
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


class InventoryTransferRequest(ApiBaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": TRANSFER_REQUEST_DESCRIPTION},
    )

    target_inventory_slug: str
    mode: Literal["copy", "move"] = Field(description=TRANSFER_MODE_DESCRIPTION)
    item_ids: list[int] | None = Field(default=None, min_length=1, max_length=100)
    all_items: bool = Field(default=False, description=TRANSFER_ALL_ITEMS_DESCRIPTION)
    on_conflict: Literal["fail", "merge"] = Field(description=TRANSFER_CONFLICT_DESCRIPTION)
    keep_acquisition: Literal["target", "source"] | None = Field(
        default=None,
        description=TRANSFER_KEEP_ACQUISITION_DESCRIPTION,
    )
    dry_run: bool = Field(default=False, description=TRANSFER_DRY_RUN_DESCRIPTION)


class InventoryDuplicateRequest(ApiBaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": DUPLICATE_REQUEST_DESCRIPTION},
    )

    target_slug: str
    target_display_name: str
    target_description: str | None = Field(default=None, description=DUPLICATE_DESCRIPTION_FALLBACK)
