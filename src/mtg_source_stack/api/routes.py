"""Minimal demo routes built directly on the inventory service facade."""

from __future__ import annotations

from io import TextIOWrapper
import json
import sqlite3
from typing import Annotated, Any, Callable

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile, status
from starlette.concurrency import run_in_threadpool

from ..errors import AuthorizationError, MtgStackError, ValidationError
from ..inventory.access import actor_inventory_role_with_connection, can_write_inventory
from ..inventory.export_profiles import supported_csv_export_profiles
from ..inventory.money import coerce_decimal
from ..inventory.normalize import (
    DEFAULT_AUDIT_EVENT_LIMIT,
    DEFAULT_PROVIDER,
    DEFAULT_SEARCH_LIMIT,
    MAX_AUDIT_EVENT_LIMIT,
    MAX_OWNED_ROWS_LIMIT,
    MAX_SEARCH_LIMIT,
)
from ..inventory.response_models import serialize_response
from ..inventory.service import (
    add_card,
    bulk_mutate_inventory_items,
    create_inventory,
    duplicate_inventory,
    ensure_default_inventory,
    import_csv_stream,
    import_decklist_text,
    import_deck_url,
    list_card_printings_for_oracle,
    list_inventory_audit_events,
    list_visible_inventories,
    list_owned_filtered,
    remove_card,
    render_inventory_csv_export,
    search_card_names,
    search_cards,
    set_acquisition,
    set_condition,
    set_finish,
    set_location,
    set_notes,
    set_printing,
    set_quantity,
    set_tags,
    summarize_actor_access,
    transfer_inventory_items,
)
from .dependencies import (
    ApiSettings,
    RequestContext,
    get_inventory_read_request_context,
    get_inventory_write_request_context,
    get_inventory_scoped_read_request_context,
    get_authenticated_request_context,
    get_settings,
    require_inventory_write_access,
)
from .request_models import (
    AddInventoryItemRequest,
    BulkInventoryItemMutationRequest,
    CONDITION_CODE_DESCRIPTION,
    DecklistImportRequest,
    DeckUrlImportRequest,
    FINISH_INPUT_DESCRIPTION,
    FinishInput,
    InventoryCreateRequest,
    InventoryDuplicateRequest,
    InventoryTransferRequest,
    LANGUAGE_CODE_DESCRIPTION,
    PatchInventoryItemRequest,
    SEARCH_LANG_DESCRIPTION,
    SetInventoryItemPrintingRequest,
)
from .response_models import (
    AccessSummaryResponse,
    AddInventoryItemResponse,
    ApiErrorResponse,
    BulkInventoryItemMutationResponse,
    CatalogNameSearchResponse,
    CatalogNameSearchRowResponse,
    CatalogPrintingLookupRowResponse,
    CatalogSearchRowResponse,
    CsvImportResponse,
    DecklistImportResponse,
    DeckUrlImportResponse,
    DefaultInventoryBootstrapResponse,
    HealthResponse,
    InventoryAuditEventResponse,
    InventoryCreateResponse,
    InventoryDuplicateResponse,
    InventoryItemPatchResponse,
    InventoryTransferResponse,
    InventoryListRowResponse,
    OwnedInventoryRowResponse,
    RemoveInventoryItemResponse,
    SetPrintingResponse,
)


router = APIRouter()

PRINTINGS_LANG_DESCRIPTION = (
    f"{SEARCH_LANG_DESCRIPTION} Omit this parameter to prefer English printings by default. "
    "Use `all` to include every available catalog language."
)
SEARCH_SCOPE_DESCRIPTION = (
    "Catalog scope to search. Omit this parameter or use `default` for the mainline card-add flow. "
    "Use `all` to include auxiliary catalog objects such as tokens, emblems, and art-series rows."
)
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
CSV_EXPORT_PROFILE_DESCRIPTION = (
    "CSV export profile. Omit this parameter or use `default` for the canonical inventory export format."
)

ERROR_RESPONSE_DESCRIPTIONS = {
    401: "Authentication required",
    403: "Forbidden",
    400: "Validation error",
    404: "Not found",
    409: "Conflict",
    500: "Internal server error",
    503: "Schema not ready",
}


def _error_responses(*status_codes: int) -> dict[int, dict[str, Any]]:
    return {
        status_code: {
            "model": ApiErrorResponse,
            "description": ERROR_RESPONSE_DESCRIPTIONS[status_code],
        }
        for status_code in status_codes
    }


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


def _serialize(payload: Any) -> Any:
    return serialize_response(payload)


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


@router.get("/health", response_model=HealthResponse, responses=_error_responses(500))
def health(settings: Annotated[ApiSettings, Depends(get_settings)]) -> dict[str, Any]:
    return {
        "status": "ok",
        "auto_migrate": settings.auto_migrate,
        "trusted_actor_headers": settings.trust_actor_headers,
    }


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


@router.get(
    "/cards/search",
    response_model=list[CatalogSearchRowResponse],
    responses=_error_responses(401, 403, 400, 503, 500),
)
def cards_search(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_scoped_read_request_context)],
    query: str,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: Annotated[FinishInput | None, Query(description=FINISH_INPUT_DESCRIPTION)] = None,
    lang: Annotated[str | None, Query(description=SEARCH_LANG_DESCRIPTION)] = None,
    scope: Annotated[
        str | None,
        Query(description=SEARCH_SCOPE_DESCRIPTION, json_schema_extra={"enum": ["default", "all"]}),
    ] = None,
    exact: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)] = DEFAULT_SEARCH_LIMIT,
) -> Any:
    return _serialize(
        search_cards(
            settings.db_path,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            lang=lang,
            scope=scope,
            exact=exact,
            limit=limit,
        )
    )


@router.get(
    "/cards/search/names",
    response_model=CatalogNameSearchResponse,
    responses=_error_responses(401, 403, 400, 503, 500),
)
def card_names_search(
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_scoped_read_request_context)],
    query: str,
    scope: Annotated[
        str | None,
        Query(description=SEARCH_SCOPE_DESCRIPTION, json_schema_extra={"enum": ["default", "all"]}),
    ] = None,
    exact: bool = False,
    limit: Annotated[int, Query(ge=1, le=MAX_SEARCH_LIMIT)] = DEFAULT_SEARCH_LIMIT,
) -> Any:
    return _serialize(
        search_card_names(
            settings.db_path,
            query=query,
            scope=scope,
            exact=exact,
            limit=limit,
        )
    )


@router.get(
    "/cards/oracle/{oracle_id}/printings",
    response_model=list[CatalogPrintingLookupRowResponse],
    responses=_error_responses(401, 403, 400, 404, 503, 500),
)
def card_printings_lookup(
    oracle_id: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_scoped_read_request_context)],
    lang: Annotated[str | None, Query(description=PRINTINGS_LANG_DESCRIPTION)] = None,
    scope: Annotated[
        str | None,
        Query(description=SEARCH_SCOPE_DESCRIPTION, json_schema_extra={"enum": ["default", "all"]}),
    ] = None,
) -> Any:
    rows = list_card_printings_for_oracle(
        settings.db_path,
        oracle_id=oracle_id,
        lang=lang,
        scope=scope,
    )
    return _serialize(rows)


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
