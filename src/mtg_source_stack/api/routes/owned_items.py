from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from starlette.concurrency import run_in_threadpool

from ...errors import ValidationError
from ...inventory.export_profiles import supported_csv_export_profiles
from ...inventory.money import coerce_decimal
from ...inventory.normalize import (
    DEFAULT_OWNED_ROWS_PAGE_LIMIT,
    DEFAULT_PROVIDER,
    MAX_OWNED_ROWS_LIMIT,
)
from ...inventory.service import (
    add_card,
    bulk_mutate_inventory_items,
    list_owned_filtered,
    list_owned_filtered_page,
    OWNED_INVENTORY_PAGE_SORT_DIRECTIONS,
    OWNED_INVENTORY_PAGE_SORT_KEYS,
    remove_card,
    render_inventory_csv_export,
    set_acquisition,
    set_condition,
    set_finish,
    set_location,
    set_notes,
    set_printing,
    set_quantity,
    set_tags,
)
from ..dependencies import (
    ApiSettings,
    RequestContext,
    get_inventory_read_request_context,
    get_inventory_write_request_context,
    get_settings,
)
from ..request_models import (
    AddInventoryItemRequest,
    BulkInventoryItemMutationRequest,
    CONDITION_CODE_DESCRIPTION,
    FINISH_INPUT_DESCRIPTION,
    FinishInput,
    LANGUAGE_CODE_DESCRIPTION,
    PatchInventoryItemRequest,
    SetInventoryItemPrintingRequest,
)
from ..response_models import (
    AddInventoryItemResponse,
    BulkInventoryItemMutationResponse,
    InventoryItemPatchResponse,
    OwnedInventoryItemsPageResponse,
    OwnedInventoryRowResponse,
    RemoveInventoryItemResponse,
    SetPrintingResponse,
)
from ._common import _error_responses, _serialize

router = APIRouter()

CSV_EXPORT_PROFILE_DESCRIPTION = (
    "CSV export profile. Omit this parameter or use `default` for the canonical inventory export format."
)
INVENTORY_ITEMS_SORT_KEY_DESCRIPTION = (
    "Server-side inventory table sort key. The paginated endpoint always adds a deterministic item_id tie-breaker."
)
SORT_DIRECTION_DESCRIPTION = "Sort direction."


def _csv_success_response(description: str = "Successful Response") -> dict[int, dict[str, Any]]:
    return {
        200: {
            "description": description,
            "content": {
                "text/csv": {
                    "schema": {
                        "type": "string",
                    }
                }
            },
        }
    }


def _csv_download_response(csv_text: str, filename: str) -> Response:
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@router.get(
    "/inventories/{inventory_slug}/items",
    response_model=list[OwnedInventoryRowResponse],
    responses=_error_responses(401, 403, 400, 404, 503, 500),
)
def inventory_items_list(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_read_request_context)],
    provider: str = DEFAULT_PROVIDER,
    limit: Annotated[int | None, Query(ge=1, le=MAX_OWNED_ROWS_LIMIT)] = None,
    query: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: Annotated[FinishInput | None, Query(description=FINISH_INPUT_DESCRIPTION)] = None,
    condition_code: Annotated[str | None, Query(description=CONDITION_CODE_DESCRIPTION)] = None,
    language_code: Annotated[str | None, Query(description=LANGUAGE_CODE_DESCRIPTION)] = None,
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


@router.get(
    "/inventories/{inventory_slug}/items/page",
    response_model=OwnedInventoryItemsPageResponse,
    responses=_error_responses(401, 403, 400, 404, 503, 500),
)
def inventory_items_page(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_read_request_context)],
    provider: str = DEFAULT_PROVIDER,
    limit: Annotated[int, Query(ge=1, le=MAX_OWNED_ROWS_LIMIT)] = DEFAULT_OWNED_ROWS_PAGE_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
    sort_key: Annotated[
        str | None,
        Query(
            description=INVENTORY_ITEMS_SORT_KEY_DESCRIPTION,
            json_schema_extra={"enum": list(OWNED_INVENTORY_PAGE_SORT_KEYS)},
        ),
    ] = None,
    sort_direction: Annotated[
        str | None,
        Query(
            description=SORT_DIRECTION_DESCRIPTION,
            json_schema_extra={"enum": list(OWNED_INVENTORY_PAGE_SORT_DIRECTIONS)},
        ),
    ] = None,
    query: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: Annotated[FinishInput | None, Query(description=FINISH_INPUT_DESCRIPTION)] = None,
    condition_code: Annotated[str | None, Query(description=CONDITION_CODE_DESCRIPTION)] = None,
    language_code: Annotated[str | None, Query(description=LANGUAGE_CODE_DESCRIPTION)] = None,
    location: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
) -> Any:
    return _serialize(
        list_owned_filtered_page(
            settings.db_path,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=limit,
            offset=offset,
            sort_key=sort_key,
            sort_direction=sort_direction,
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


@router.get(
    "/inventories/{inventory_slug}/export.csv",
    responses={**_csv_success_response("CSV export download"), **_error_responses(401, 403, 400, 404, 503, 500)},
)
async def inventory_export_csv_download(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_read_request_context)],
    provider: str = DEFAULT_PROVIDER,
    profile: Annotated[
        str,
        Query(
            description=CSV_EXPORT_PROFILE_DESCRIPTION,
            json_schema_extra={"enum": supported_csv_export_profiles()},
        ),
    ] = "default",
    limit: Annotated[int | None, Query(ge=1, le=MAX_OWNED_ROWS_LIMIT)] = None,
    query: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: Annotated[FinishInput | None, Query(description=FINISH_INPUT_DESCRIPTION)] = None,
    condition_code: Annotated[str | None, Query(description=CONDITION_CODE_DESCRIPTION)] = None,
    language_code: Annotated[str | None, Query(description=LANGUAGE_CODE_DESCRIPTION)] = None,
    location: str | None = None,
    tags: Annotated[list[str] | None, Query()] = None,
) -> Response:
    rendered = await run_in_threadpool(
        render_inventory_csv_export,
        settings.db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        profile=profile,
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
    return _csv_download_response(rendered.csv_text, rendered.filename)


@router.post(
    "/inventories/{inventory_slug}/items",
    status_code=status.HTTP_201_CREATED,
    response_model=AddInventoryItemResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventory_items_add(
    inventory_slug: str,
    payload: AddInventoryItemRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_inventory_write_request_context)],
) -> Any:
    return _serialize(
        add_card(
            settings.db_path,
            inventory_slug=inventory_slug,
            inventory_display_name=None,
            scryfall_id=payload.scryfall_id,
            oracle_id=payload.oracle_id,
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


@router.post(
    "/inventories/{inventory_slug}/items/bulk",
    response_model=BulkInventoryItemMutationResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventory_items_bulk_mutate(
    inventory_slug: str,
    payload: BulkInventoryItemMutationRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_inventory_write_request_context)],
) -> Any:
    return _serialize(
        bulk_mutate_inventory_items(
            settings.db_path,
            inventory_slug=inventory_slug,
            operation=payload.operation,
            item_ids=payload.item_ids,
            tags=payload.tags,
            quantity=payload.quantity,
            notes=payload.notes,
            clear_notes=payload.clear_notes,
            acquisition_price=coerce_decimal(payload.acquisition_price),
            acquisition_currency=payload.acquisition_currency,
            clear_acquisition=payload.clear_acquisition,
            finish=payload.finish,
            location=payload.location,
            clear_location=payload.clear_location,
            condition_code=payload.condition_code,
            merge=payload.merge,
            keep_acquisition=payload.keep_acquisition,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            request_id=context.request_id,
        )
    )


@router.patch(
    "/inventories/{inventory_slug}/items/{item_id}",
    response_model=InventoryItemPatchResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventory_items_patch(
    inventory_slug: str,
    item_id: int,
    payload: PatchInventoryItemRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_inventory_write_request_context)],
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


@router.patch(
    "/inventories/{inventory_slug}/items/{item_id}/printing",
    response_model=SetPrintingResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventory_items_set_printing(
    inventory_slug: str,
    item_id: int,
    payload: SetInventoryItemPrintingRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_inventory_write_request_context)],
) -> Any:
    return _serialize(
        set_printing(
            settings.db_path,
            inventory_slug=inventory_slug,
            item_id=item_id,
            scryfall_id=payload.scryfall_id,
            finish=payload.finish,
            merge=payload.merge,
            keep_acquisition=payload.keep_acquisition,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            request_id=context.request_id,
        )
    )


@router.delete(
    "/inventories/{inventory_slug}/items/{item_id}",
    response_model=RemoveInventoryItemResponse,
    responses=_error_responses(401, 403, 404, 503, 500),
)
def inventory_items_delete(
    inventory_slug: str,
    item_id: int,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_inventory_write_request_context)],
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
