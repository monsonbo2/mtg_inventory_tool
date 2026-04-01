"""Minimal demo routes built directly on the inventory service facade."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status

from ..errors import ValidationError
from ..inventory.money import coerce_decimal
from ..inventory.normalize import DEFAULT_PROVIDER
from ..inventory.response_models import serialize_response
from ..inventory.service import (
    add_card,
    create_inventory,
    list_inventories,
    list_inventory_audit_events,
    list_owned_filtered,
    remove_card,
    search_cards,
    set_acquisition,
    set_condition,
    set_finish,
    set_location,
    set_notes,
    set_quantity,
    set_tags,
)
from .dependencies import ApiSettings, RequestContext, get_request_context, get_settings
from .models import AddInventoryItemRequest, InventoryCreateRequest, PatchInventoryItemRequest


router = APIRouter()


def _serialize(payload: Any) -> Any:
    return serialize_response(payload)


def _tags_to_csv(tags: list[str] | None) -> str | None:
    if not tags:
        return None
    return ",".join(tags)


def _patch_operation(payload: PatchInventoryItemRequest) -> str:
    if payload.clear_location and payload.location is not None:
        raise ValidationError("Use either location or clear_location, not both.")
    if payload.clear_notes and payload.notes is not None:
        raise ValidationError("Use either notes or clear_notes, not both.")
    if payload.clear_tags and payload.tags is not None:
        raise ValidationError("Use either tags or clear_tags, not both.")
    if payload.clear_acquisition and (
        payload.acquisition_price is not None or payload.acquisition_currency is not None
    ):
        raise ValidationError("Use either acquisition fields or clear_acquisition, not both.")

    requested: list[str] = []
    if payload.quantity is not None:
        requested.append("quantity")
    if payload.finish is not None:
        requested.append("finish")
    if payload.location is not None or payload.clear_location:
        requested.append("location")
    if payload.condition_code is not None:
        requested.append("condition")
    if payload.notes is not None or payload.clear_notes:
        requested.append("notes")
    if payload.tags is not None or payload.clear_tags:
        requested.append("tags")
    if payload.acquisition_price is not None or payload.acquisition_currency is not None or payload.clear_acquisition:
        requested.append("acquisition")

    if len(requested) != 1:
        raise ValidationError(
            "PATCH requests must specify exactly one mutation family: quantity, finish, location, "
            "condition_code, notes, tags, or acquisition."
        )
    operation = requested[0]
    if operation not in {"location", "condition"} and (payload.merge or payload.keep_acquisition is not None):
        raise ValidationError("merge and keep_acquisition only apply to location or condition changes.")
    return operation


@router.get("/health")
def health(settings: Annotated[ApiSettings, Depends(get_settings)]) -> dict[str, Any]:
    return {
        "status": "ok",
        "db_path": str(settings.db_path),
        "auto_migrate": settings.auto_migrate,
    }


@router.get("/inventories")
def inventories_list(settings: Annotated[ApiSettings, Depends(get_settings)]) -> Any:
    return _serialize(list_inventories(settings.db_path))


@router.post("/inventories", status_code=status.HTTP_201_CREATED)
def inventories_create(
    payload: InventoryCreateRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
) -> Any:
    return _serialize(
        create_inventory(
            settings.db_path,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
        )
    )


@router.get("/cards/search")
def cards_search(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    query: str,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: str | None = None,
    lang: str | None = None,
    exact: bool = False,
    limit: int = 10,
) -> Any:
    return _serialize(
        search_cards(
            settings.db_path,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            lang=lang,
            exact=exact,
            limit=limit,
        )
    )


@router.get("/inventories/{inventory_slug}/items")
def inventory_items_list(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    provider: str = DEFAULT_PROVIDER,
    limit: int | None = None,
    query: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: str | None = None,
    condition_code: str | None = None,
    language_code: str | None = None,
    location: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
) -> Any:
    return _serialize(
        list_owned_filtered(
            settings.db_path,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=limit,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        )
    )


@router.post("/inventories/{inventory_slug}/items", status_code=status.HTTP_201_CREATED)
def inventory_items_add(
    inventory_slug: str,
    payload: AddInventoryItemRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> Any:
    return _serialize(
        add_card(
            settings.db_path,
            inventory_slug=inventory_slug,
            inventory_display_name=None,
            scryfall_id=payload.scryfall_id,
            tcgplayer_product_id=payload.tcgplayer_product_id,
            name=payload.name,
            set_code=payload.set_code,
            collector_number=payload.collector_number,
            lang=payload.lang,
            quantity=payload.quantity,
            condition_code=payload.condition_code,
            finish=payload.finish,
            language_code=payload.language_code,
            location=payload.location,
            acquisition_price=coerce_decimal(payload.acquisition_price),
            acquisition_currency=payload.acquisition_currency,
            notes=payload.notes,
            tags=_tags_to_csv(payload.tags),
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            request_id=context.request_id,
        )
    )


@router.patch("/inventories/{inventory_slug}/items/{item_id}")
def inventory_items_patch(
    inventory_slug: str,
    item_id: int,
    payload: PatchInventoryItemRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> Any:
    operation = _patch_operation(payload)
    db_path = settings.db_path
    common_kwargs = {
        "inventory_slug": inventory_slug,
        "item_id": item_id,
        "actor_type": context.actor_type,
        "actor_id": context.actor_id,
        "request_id": context.request_id,
    }

    if operation == "quantity":
        result = set_quantity(db_path, quantity=payload.quantity, **common_kwargs)
    elif operation == "finish":
        result = set_finish(db_path, finish=payload.finish, **common_kwargs)
    elif operation == "location":
        result = set_location(
            db_path,
            location=None if payload.clear_location else payload.location,
            merge=payload.merge,
            keep_acquisition=payload.keep_acquisition,
            **common_kwargs,
        )
    elif operation == "condition":
        result = set_condition(
            db_path,
            condition_code=payload.condition_code,
            merge=payload.merge,
            keep_acquisition=payload.keep_acquisition,
            **common_kwargs,
        )
    elif operation == "notes":
        result = set_notes(
            db_path,
            notes=None if payload.clear_notes else payload.notes,
            **common_kwargs,
        )
    elif operation == "tags":
        result = set_tags(
            db_path,
            tags=None if payload.clear_tags else _tags_to_csv(payload.tags),
            **common_kwargs,
        )
    else:
        result = set_acquisition(
            db_path,
            acquisition_price=coerce_decimal(payload.acquisition_price),
            acquisition_currency=payload.acquisition_currency,
            clear=payload.clear_acquisition,
            **common_kwargs,
        )

    return _serialize(result)


@router.delete("/inventories/{inventory_slug}/items/{item_id}")
def inventory_items_delete(
    inventory_slug: str,
    item_id: int,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_request_context)],
) -> Any:
    return _serialize(
        remove_card(
            settings.db_path,
            inventory_slug=inventory_slug,
            item_id=item_id,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            request_id=context.request_id,
        )
    )


@router.get("/inventories/{inventory_slug}/audit")
def inventory_audit_list(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    limit: int = 50,
    item_id: int | None = None,
) -> Any:
    return _serialize(
        list_inventory_audit_events(
            settings.db_path,
            inventory_slug=inventory_slug,
            limit=limit,
            item_id=item_id,
        )
    )
