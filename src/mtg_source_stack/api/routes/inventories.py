from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from ...inventory.service import (
    create_inventory,
    duplicate_inventory,
    ensure_default_inventory,
    list_visible_inventories,
    transfer_inventory_items,
)
from ..dependencies import (
    ApiSettings,
    RequestContext,
    get_authenticated_request_context,
    get_settings,
    require_inventory_read_access,
    require_inventory_write_access,
)
from ..request_models import (
    InventoryCreateRequest,
    InventoryDuplicateRequest,
    InventoryTransferRequest,
)
from ..response_models import (
    DefaultInventoryBootstrapResponse,
    InventoryCreateResponse,
    InventoryDuplicateResponse,
    InventoryListRowResponse,
    InventoryTransferResponse,
)
from ._common import _error_responses, _serialize

router = APIRouter()


@router.get(
    "/inventories",
    response_model=list[InventoryListRowResponse],
    responses=_error_responses(401, 403, 503, 500),
)
def inventories_list(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    return _serialize(
        list_visible_inventories(
            settings.db_path,
            actor_id=context.actor_id,
            actor_roles=context.roles,
        )
    )


@router.post(
    "/inventories",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryCreateResponse,
    responses=_error_responses(401, 403, 400, 409, 503, 500),
)
def inventories_create(
    payload: InventoryCreateRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    return _serialize(
        create_inventory(
            settings.db_path,
            slug=payload.slug,
            display_name=payload.display_name,
            description=payload.description,
            default_location=payload.default_location,
            default_tags=payload.default_tags,
            notes=payload.notes,
            acquisition_price=payload.acquisition_price,
            acquisition_currency=payload.acquisition_currency,
            actor_id=context.actor_id,
        )
    )


@router.post(
    "/me/bootstrap",
    response_model=DefaultInventoryBootstrapResponse,
    responses=_error_responses(401, 403, 409, 503, 500),
)
def bootstrap_default_inventory(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    return _serialize(
        ensure_default_inventory(
            settings.db_path,
            actor_id=context.actor_id,
            actor_roles=context.roles,
        )
    )


@router.post(
    "/inventories/{source_inventory_slug}/duplicate",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryDuplicateResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventories_duplicate(
    source_inventory_slug: str,
    payload: InventoryDuplicateRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_write_access(settings, context, inventory_slug=source_inventory_slug)
    return _serialize(
        duplicate_inventory(
            settings.db_path,
            source_inventory_slug=source_inventory_slug,
            target_slug=payload.target_slug,
            target_display_name=payload.target_display_name,
            target_description=payload.target_description,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            request_id=context.request_id,
        )
    )


@router.post(
    "/inventories/{source_inventory_slug}/transfer",
    response_model=InventoryTransferResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventory_items_transfer(
    source_inventory_slug: str,
    payload: InventoryTransferRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    if payload.mode == "copy":
        require_inventory_read_access(settings, context, inventory_slug=source_inventory_slug)
    else:
        require_inventory_write_access(settings, context, inventory_slug=source_inventory_slug)
    require_inventory_write_access(settings, context, inventory_slug=payload.target_inventory_slug)
    return _serialize(
        transfer_inventory_items(
            settings.db_path,
            source_inventory_slug=source_inventory_slug,
            target_inventory_slug=payload.target_inventory_slug,
            mode=payload.mode,
            item_ids=payload.item_ids,
            all_items=payload.all_items,
            on_conflict=payload.on_conflict,
            keep_acquisition=payload.keep_acquisition,
            dry_run=payload.dry_run,
            actor_type=context.actor_type,
            actor_id=context.actor_id,
            request_id=context.request_id,
        )
    )
