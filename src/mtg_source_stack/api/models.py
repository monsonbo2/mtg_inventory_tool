"""Pydantic request models for the demo web API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    lang: str | None = None
    quantity: int = 1
    condition_code: str = "NM"
    finish: str = "normal"
    language_code: str = "en"
    location: str = ""
    acquisition_price: str | None = None
    acquisition_currency: str | None = None
    notes: str | None = None
    tags: list[str] | None = None


class PatchInventoryItemRequest(ApiBaseModel):
    quantity: int | None = None
    finish: str | None = None
    location: str | None = None
    clear_location: bool = False
    condition_code: str | None = None
    merge: bool = False
    keep_acquisition: Literal["target", "source"] | None = None
    notes: str | None = None
    clear_notes: bool = False
    tags: list[str] | None = None
    clear_tags: bool = False
    acquisition_price: str | None = None
    acquisition_currency: str | None = None
    clear_acquisition: bool = False
