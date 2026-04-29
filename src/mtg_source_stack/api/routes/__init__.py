"""Minimal demo routes built directly on the inventory service facade."""

from __future__ import annotations

from io import TextIOWrapper
import json
import sqlite3
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from ...errors import AuthorizationError, MtgStackError, ValidationError
from ...inventory.access import actor_inventory_role_with_connection, can_write_inventory
from ...inventory.service import import_csv_stream, import_decklist_text, import_deck_url
from ..dependencies import (
    ApiSettings,
    RequestContext,
    get_authenticated_request_context,
    get_settings,
)
from ..request_models import (
    DecklistImportRequest,
    DeckUrlImportRequest,
)
from ..response_models import (
    CsvImportResponse,
    DecklistImportResponse,
    DeckUrlImportResponse,
)
from ._common import _error_responses, _serialize
from .audit import router as audit_router
from .catalog import router as catalog_router
from .health import router as health_router
from .inventories import router as inventories_router
from .memberships import router as memberships_router
from .owned_items import router as owned_items_router
from .sharing import router as sharing_router


router = APIRouter()
router.include_router(health_router)
router.include_router(inventories_router)
router.include_router(memberships_router)
router.include_router(sharing_router)
router.include_router(catalog_router)
router.include_router(owned_items_router)
router.include_router(audit_router)

CSV_IMPORT_FILE_DESCRIPTION = "CSV file to import."
CSV_IMPORT_DEFAULT_INVENTORY_DESCRIPTION = (
    "Optional default inventory slug when the CSV does not include an inventory column."
)
CSV_IMPORT_DRY_RUN_DESCRIPTION = (
    "When true, validate and resolve the import using the real add-card workflow but roll back before commit."
)
CSV_IMPORT_RESOLUTIONS_JSON_DESCRIPTION = (
    "Optional JSON array of explicit row resolutions for ambiguous CSV rows. "
    "Each item selects one suggested printing and finish for a specific csv_row."
)
def _parse_resolutions_json_form(raw_value: str | None) -> list[dict[str, Any]]:
    if raw_value is None or not raw_value.strip():
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValidationError("Multipart field 'resolutions_json' must be valid JSON.") from exc
    if not isinstance(parsed, list):
        raise ValidationError("Multipart field 'resolutions_json' must decode to a JSON array.")
    if not all(isinstance(item, dict) for item in parsed):
        raise ValidationError(
            "Multipart field 'resolutions_json' must decode to a JSON array of objects."
        )
    return list(parsed)


def _validate_uploaded_csv_size(upload: UploadFile, *, max_bytes: int) -> None:
    handle = upload.file
    # Starlette's multipart parser does not guarantee the current stream
    # position for uploaded files, and file-only multipart requests can arrive
    # with the spooled file already positioned at EOF. Always rewind after the
    # size probe so the CSV reader sees the full upload body.
    handle.seek(0, 2)
    size = handle.tell()
    handle.seek(0)
    if size > max_bytes:
        raise ValidationError(f"CSV upload must not exceed {max_bytes} bytes.")


def _require_import_inventory_write_access(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    context: RequestContext,
) -> None:
    inventory_role = actor_inventory_role_with_connection(
        connection,
        inventory_slug=inventory_slug,
        actor_id=context.actor_id,
    )
    if can_write_inventory(inventory_role=inventory_role, actor_roles=context.roles):
        return
    raise AuthorizationError(
        f"Write access to inventory '{inventory_slug}' is required for this shared_service request."
    )


def _require_csv_import_inventory_write_access(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    context: RequestContext,
) -> None:
    _require_import_inventory_write_access(
        connection,
        inventory_slug=inventory_slug,
        context=context,
    )


InventoryValidator = Callable[[sqlite3.Connection, str], None]


def _build_import_inventory_validator(
    settings: ApiSettings,
    context: RequestContext,
    *,
    checker: Callable[..., None],
) -> InventoryValidator | None:
    if settings.runtime_mode != "shared_service":
        return None

    def inventory_validator(connection: sqlite3.Connection, inventory_slug: str) -> None:
        checker(
            connection,
            inventory_slug=inventory_slug,
            context=context,
        )

    return inventory_validator

@router.post(
    "/imports/csv",
    response_model=CsvImportResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
async def imports_csv(
    file: Annotated[UploadFile, File(description=CSV_IMPORT_FILE_DESCRIPTION)],
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
    default_inventory: Annotated[
        str | None,
        Form(description=CSV_IMPORT_DEFAULT_INVENTORY_DESCRIPTION),
    ] = None,
    dry_run: Annotated[
        bool,
        Form(description=CSV_IMPORT_DRY_RUN_DESCRIPTION),
    ] = False,
    resolutions_json: Annotated[
        str | None,
        Form(description=CSV_IMPORT_RESOLUTIONS_JSON_DESCRIPTION),
    ] = None,
) -> Any:
    _validate_uploaded_csv_size(file, max_bytes=settings.csv_import_max_bytes)
    resolutions = _parse_resolutions_json_form(resolutions_json)
    inventory_validator = _build_import_inventory_validator(
        settings,
        context,
        checker=_require_csv_import_inventory_write_access,
    )
    csv_handle = TextIOWrapper(file.file, encoding="utf-8-sig", newline="")
    try:
        try:
            result = await run_in_threadpool(
                import_csv_stream,
                settings.db_path,
                csv_handle=csv_handle,
                csv_filename=(file.filename or "upload.csv").strip() or "upload.csv",
                default_inventory=default_inventory,
                dry_run=dry_run,
                resolutions=resolutions,
                allow_inventory_auto_create=False,
                inventory_validator=inventory_validator,
                actor_type=context.actor_type,
                actor_id=context.actor_id,
                request_id=context.request_id,
                schema_policy="require_current",
            )
        except MtgStackError:
            raise
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
    finally:
        try:
            csv_handle.detach()
        except Exception:
            pass
        await file.close()
    return _serialize(result)


@router.post(
    "/imports/decklist",
    response_model=DecklistImportResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
async def imports_decklist(
    payload: DecklistImportRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    inventory_validator = _build_import_inventory_validator(
        settings,
        context,
        checker=_require_import_inventory_write_access,
    )
    result = await run_in_threadpool(
        import_decklist_text,
        settings.db_path,
        deck_text=payload.deck_text,
        default_inventory=payload.default_inventory,
        dry_run=payload.dry_run,
        resolutions=[selection.model_dump() for selection in payload.resolutions],
        inventory_validator=inventory_validator,
        actor_type=context.actor_type,
        actor_id=context.actor_id,
        request_id=context.request_id,
        schema_policy="require_current",
    )
    return _serialize(result)


@router.post(
    "/imports/deck-url",
    response_model=DeckUrlImportResponse,
    responses=_error_responses(401, 403, 400, 404, 409, 503, 500),
)
async def imports_deck_url(
    payload: DeckUrlImportRequest,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    context: Annotated[RequestContext, Depends(get_authenticated_request_context)],
) -> Any:
    inventory_validator = _build_import_inventory_validator(
        settings,
        context,
        checker=_require_import_inventory_write_access,
    )
    result = await run_in_threadpool(
        import_deck_url,
        settings.db_path,
        source_url=payload.source_url,
        default_inventory=payload.default_inventory,
        dry_run=payload.dry_run,
        source_snapshot_token=payload.source_snapshot_token,
        snapshot_signing_secret=settings.snapshot_signing_secret,
        resolutions=[selection.model_dump() for selection in payload.resolutions],
        inventory_validator=inventory_validator,
        actor_type=context.actor_type,
        actor_id=context.actor_id,
        request_id=context.request_id,
        schema_policy="require_current",
    )
    return _serialize(result)
