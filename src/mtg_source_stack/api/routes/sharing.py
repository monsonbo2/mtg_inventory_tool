from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from ...inventory.service import (
    create_inventory_share_link,
    get_inventory_share_link_status,
    get_public_inventory_share,
    revoke_inventory_share_link,
    rotate_inventory_share_link,
)
from ..dependencies import (
    ApiSettings,
    RequestContext,
    get_authenticated_request_context,
    get_settings,
    require_inventory_share_management_access,
)
from ..response_models import (
    InventoryShareLinkStatusResponse,
    InventoryShareLinkTokenResponse,
    PublicInventoryShareResponse,
)
from ._common import _error_responses, _serialize

router = APIRouter()


@router.get(
    "/inventories/{inventory_slug}/share-link",
    response_model=InventoryShareLinkStatusResponse,
    responses=_error_responses(401, 403, 404, 503, 500),
)
def inventory_share_link_status(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_share_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        get_inventory_share_link_status(
            settings.db_path,
            inventory_slug=inventory_slug,
            token_secret=settings.snapshot_signing_secret,
        )
    )


@router.post(
    "/inventories/{inventory_slug}/share-link",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryShareLinkTokenResponse,
    responses=_error_responses(401, 403, 404, 409, 503, 500),
)
def inventory_share_link_create(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_share_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        create_inventory_share_link(
            settings.db_path,
            inventory_slug=inventory_slug,
            actor_id=context.actor_id,
            token_secret=settings.snapshot_signing_secret,
            actor_type=context.actor_type,
            request_id=context.request_id,
        )
    )


@router.post(
    "/inventories/{inventory_slug}/share-link/rotate",
    response_model=InventoryShareLinkTokenResponse,
    responses=_error_responses(401, 403, 404, 503, 500),
)
def inventory_share_link_rotate(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_share_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        rotate_inventory_share_link(
            settings.db_path,
            inventory_slug=inventory_slug,
            actor_id=context.actor_id,
            token_secret=settings.snapshot_signing_secret,
            actor_type=context.actor_type,
            request_id=context.request_id,
        )
    )


@router.delete(
    "/inventories/{inventory_slug}/share-link",
    response_model=InventoryShareLinkStatusResponse,
    responses=_error_responses(401, 403, 404, 503, 500),
)
def inventory_share_link_revoke(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_share_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        revoke_inventory_share_link(
            settings.db_path,
            inventory_slug=inventory_slug,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            request_id=context.request_id,
        )
    )


@router.get(
    "/shared/inventories/{share_token}",
    response_model=PublicInventoryShareResponse,
    responses=_error_responses(404, 503, 500),
)
def public_inventory_share(
    share_token: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
) -> Any:
    return _serialize(
        get_public_inventory_share(
            settings.db_path,
            token=share_token,
            token_secret=settings.snapshot_signing_secret,
        )
    )
