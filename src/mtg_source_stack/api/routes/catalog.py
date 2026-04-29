from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ...inventory.normalize import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT
from ...inventory.service import (
    list_card_printings_for_oracle,
    search_card_names,
    search_cards,
    summarize_card_printings_for_oracle,
)
from ..dependencies import (
    ApiSettings,
    RequestContext,
    get_inventory_scoped_read_request_context,
    get_settings,
)
from ..request_models import FINISH_INPUT_DESCRIPTION, FinishInput, SEARCH_LANG_DESCRIPTION
from ..response_models import (
    CatalogNameSearchResponse,
    CatalogPrintingLookupRowResponse,
    CatalogPrintingSummaryResponse,
    CatalogSearchRowResponse,
)
from ._common import (
    PRINTINGS_LANG_DESCRIPTION,
    SEARCH_SCOPE_DESCRIPTION,
    _error_responses,
    _serialize,
)

router = APIRouter()


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
    "/cards/oracle/{oracle_id}/printings/summary",
    response_model=CatalogPrintingSummaryResponse,
    responses=_error_responses(401, 403, 400, 404, 503, 500),
)
def card_printings_summary(
    oracle_id: str,
    settings: Annotated[ApiSettings, Depends(get_settings)],
    _context: Annotated[RequestContext, Depends(get_inventory_scoped_read_request_context)],
    scope: Annotated[
        str | None,
        Query(description=SEARCH_SCOPE_DESCRIPTION, json_schema_extra={"enum": ["default", "all"]}),
    ] = None,
) -> Any:
    return _serialize(
        summarize_card_printings_for_oracle(
            settings.db_path,
            oracle_id=oracle_id,
            scope=scope,
        )
    )
