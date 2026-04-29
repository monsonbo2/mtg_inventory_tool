from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ...inventory.normalize import DEFAULT_AUDIT_EVENT_LIMIT, MAX_AUDIT_EVENT_LIMIT
from ...inventory.service import list_inventory_audit_events
from ..dependencies import (
    ApiSettings,
    RequestContext,
    get_inventory_read_request_context,
    get_settings,
)
from ..response_models import InventoryAuditEventResponse
from ._common import _error_responses, _serialize

router = APIRouter()


@router.get(
    "/inventories/{inventory_slug}/audit",
    response_model=list[InventoryAuditEventResponse],
    responses=_error_responses(401, 403, 400, 404, 503, 500),
)
def inventory_audit_list(
    inventory_slug: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_read_request_context)],
    limit: Annotated[int, Query(ge=1, le=MAX_AUDIT_EVENT_LIMIT)] = DEFAULT_AUDIT_EVENT_LIMIT,
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
