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
    "The first shipped bulk route supports only tag operations: add_tags, remove_tags, "
    "set_tags, or clear_tags."
)
BULK_TAGS_DESCRIPTION = (
    "Required for add_tags, remove_tags, and set_tags. Omit this field for clear_tags. "
    "Use clear_tags instead of sending an empty tag list."
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
    "When supplied, the backend reuses the normalized remote deck payload instead of refetching the provider."
)


class ApiBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InventoryCreateRequest(ApiBaseModel):
    slug: str
    display_name: str
    description: str | None = None


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


class BulkInventoryItemMutationRequest(ApiBaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"description": BULK_ITEM_MUTATION_REQUEST_DESCRIPTION},
    )

    operation: Literal["add_tags", "remove_tags", "set_tags", "clear_tags"]
    item_ids: list[int] = Field(min_length=1, max_length=100)
    tags: list[str] | None = Field(default=None, description=BULK_TAGS_DESCRIPTION)
