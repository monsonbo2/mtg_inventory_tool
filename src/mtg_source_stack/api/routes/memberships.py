from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from ...inventory.service import (
    list_inventory_memberships,
    remove_inventory_membership,
    set_inventory_membership_role,
    summarize_actor_access,
    update_inventory_membership_role,
)
from ..dependencies import (
    ApiSettings,
    RequestContext,
    get_authenticated_request_context,
    get_settings,
    require_inventory_membership_management_access,
)
from ..request_models import (
    InventoryMembershipGrantRequest,
    InventoryMembershipUpdateRequest,
)
from ..response_models import (
    AccessSummaryResponse,
    InventoryMembershipRemovalResponse,
    InventoryMembershipResponse,
)
from ._common import _error_responses, _serialize

router = APIRouter()


@router.get(
    "/inventories/{inventory_slug}/members",
    response_model=list[InventoryMembershipResponse],
    responses=_error_responses(401, 403, 404, 503, 500),
)
def inventory_members_list(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_membership_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        list_inventory_memberships(
            settings.db_path,
            inventory_slug=inventory_slug,
        )
    )


@router.post(
    "/inventories/{inventory_slug}/members",
    status_code=status.HTTP_201_CREATED,
    response_model=InventoryMembershipResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventory_member_grant(
    inventory_slug: str,
    payload: InventoryMembershipGrantRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_membership_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        set_inventory_membership_role(
            settings.db_path,
            inventory_slug=inventory_slug,
            member_actor_id=payload.actor_id,
            role=payload.role,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            request_id=context.request_id,
        )
    )


@router.patch(
    "/inventories/{inventory_slug}/members/{actor_id}",
    response_model=InventoryMembershipResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
def inventory_member_update(
    inventory_slug: str,
    actor_id: str,
    payload: InventoryMembershipUpdateRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_membership_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        update_inventory_membership_role(
            settings.db_path,
            inventory_slug=inventory_slug,
            member_actor_id=actor_id,
            role=payload.role,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            request_id=context.request_id,
        )
    )


@router.delete(
    "/inventories/{inventory_slug}/members/{actor_id}",
    response_model=InventoryMembershipRemovalResponse,
    responses=_error_responses(401, 403, 404, 409, 503, 500),
)
def inventory_member_revoke(
    inventory_slug: str,
    actor_id: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    require_inventory_membership_management_access(settings, context, inventory_slug=inventory_slug)
    return _serialize(
        remove_inventory_membership(
            settings.db_path,
            inventory_slug=inventory_slug,
            member_actor_id=actor_id,
            actor_id=context.actor_id,
            actor_type=context.actor_type,
            request_id=context.request_id,
        )
    )


@router.get(
    "/me/access-summary",
    response_model=AccessSummaryResponse,
    responses=_error_responses(401, 403, 503, 500),
)
def get_access_summary(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    return _serialize(
        summarize_actor_access(
            settings.db_path,
            actor_id=context.actor_id,
            actor_roles=context.roles,
        )
    )
