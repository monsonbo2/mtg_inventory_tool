"""Remote deck URL import helpers."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from ..errors import MtgStackError, NotFoundError, ValidationError
from ..db.connection import connect
from ..db.schema import SchemaPreparationPolicy, prepare_database
from .catalog import (
    determine_printing_selection_mode,
    list_default_card_name_candidate_rows,
    list_printing_candidate_rows,
    resolve_card_row,
    resolve_default_card_row_for_name,
)
from .import_engine import InventoryValidator, PendingImportRow, import_pending_rows
from .import_resolution import (
    RemoteDeckRequestedCard,
    RemoteDeckResolutionIssue,
    RemoteDeckResolutionSelection,
    build_resolution_options_for_catalog_row,
)
from .import_summary import build_resolvable_deck_import_summary
from .normalize import DEFAULT_CONDITION_CODE, DEFAULT_FINISH, normalize_finish, text_or_none
from .query_inventory import get_inventory_row
from .remote_deck_providers import (
    _aetherhub_deck_slug_from_url,
    _archidekt_deck_id_from_url,
    _extract_mtggoldfish_download_id,
    _manabox_deck_id_from_url,
    _mtggoldfish_deck_id_from_url,
    _moxfield_public_id_from_url,
    _mtgtop8_dec_export_url_from_url,
    _remote_source_from_aetherhub_page,
    _remote_source_from_archidekt_payload,
    _remote_source_from_manabox_page,
    _remote_source_from_mtggoldfish_downloads,
    _remote_source_from_moxfield_payload,
    _remote_source_from_mtgtop8_export,
    _remote_source_from_tappedout_page,
    _tappedout_deck_slug_from_url,
    fetch_remote_deck_source,
)
from .remote_deck_sources import (
    RemoteDeckCard,
    RemoteDeckSource,
    _RemoteDeckSourceError,
    _decode_remote_source_snapshot_token,
    _encode_remote_source_snapshot_token,
    _fetch_json,
    _fetch_text,
)
from .response_models import serialize_response


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PlannedRemoteDeckImport:
    source: RemoteDeckSource
    rows_seen: int
    requested_card_quantity: int
    source_snapshot_token: str
    pending_rows: list[PendingImportRow]
    resolution_issues: list[RemoteDeckResolutionIssue]


def _load_remote_source_for_import(
    source_url: str,
    *,
    source_snapshot_token: str | None = None,
    snapshot_signing_secret: str | None = None,
) -> tuple[RemoteDeckSource, str]:
    if text_or_none(source_snapshot_token) is not None:
        source = _decode_remote_source_snapshot_token(
            text_or_none(source_snapshot_token) or "",
            source_url=source_url,
            snapshot_signing_secret=snapshot_signing_secret,
        )
        return source, text_or_none(source_snapshot_token) or ""

    source = fetch_remote_deck_source(source_url)
    return source, _encode_remote_source_snapshot_token(
        source,
        snapshot_signing_secret=snapshot_signing_secret,
    )


def _build_add_card_kwargs_from_remote_card(
    card: RemoteDeckCard,
    *,
    default_inventory: str | None,
    printing_selection_mode: str = "explicit",
) -> dict[str, Any]:
    inventory_slug = text_or_none(default_inventory)
    if inventory_slug is None:
        raise ValidationError("default_inventory is required for deck URL imports.")
    if card.scryfall_id is None and text_or_none(card.name) is None:
        raise ValidationError("Remote deck import requires either a printing id or a card name.")
    return {
        "inventory_slug": inventory_slug,
        "inventory_display_name": None,
        "scryfall_id": card.scryfall_id,
        "oracle_id": None,
        "tcgplayer_product_id": None,
        "name": card.name,
        "set_code": card.set_code,
        "collector_number": card.collector_number,
        "lang": None,
        "quantity": card.quantity,
        "condition_code": DEFAULT_CONDITION_CODE,
        "finish": card.finish,
        "language_code": None,
        "location": "",
        "acquisition_price": None,
        "acquisition_currency": None,
        "notes": None,
        "tags": None,
        "printing_selection_mode": printing_selection_mode,
    }


def _build_pending_remote_row(
    card: RemoteDeckCard,
    *,
    default_inventory: str | None,
    printing_selection_mode: str,
) -> PendingImportRow:
    return PendingImportRow(
        row_number=card.source_position,
        add_kwargs=_build_add_card_kwargs_from_remote_card(
            card,
            default_inventory=default_inventory,
            printing_selection_mode=printing_selection_mode,
        ),
        response_metadata={"source_position": card.source_position, "section": card.section},
        error_label="Remote deck card",
    )


def _remote_card_with_resolved_printing(
    card: RemoteDeckCard,
    *,
    scryfall_id: str,
    finish: str | None = None,
) -> RemoteDeckCard:
    return RemoteDeckCard(
        source_position=card.source_position,
        quantity=card.quantity,
        section=card.section,
        scryfall_id=scryfall_id,
        finish=finish or card.finish,
        name=card.name,
        set_code=card.set_code,
        collector_number=card.collector_number,
    )


def _build_remote_requested_card(card: RemoteDeckCard) -> RemoteDeckRequestedCard:
    return RemoteDeckRequestedCard(
        scryfall_id=card.scryfall_id,
        name=card.name,
        quantity=card.quantity,
        set_code=card.set_code,
        collector_number=card.collector_number,
        finish=card.finish,
    )


def _normalize_remote_resolution_selections(
    resolutions: list[Mapping[str, Any]] | None,
) -> dict[int, RemoteDeckResolutionSelection]:
    if not resolutions:
        return {}

    normalized: dict[int, RemoteDeckResolutionSelection] = {}
    for raw_selection in resolutions:
        source_position = raw_selection.get("source_position")
        if not isinstance(source_position, int):
            raise ValidationError("Each remote deck resolution must include an integer source_position.")
        if source_position in normalized:
            raise ValidationError("remote deck resolutions must not repeat the same source_position.")
        scryfall_id = text_or_none(raw_selection.get("scryfall_id"))
        if scryfall_id is None:
            raise ValidationError("Each remote deck resolution must include a scryfall_id.")
        finish_raw = text_or_none(raw_selection.get("finish"))
        if finish_raw is None:
            raise ValidationError("Each remote deck resolution must include a finish.")
        normalized[source_position] = RemoteDeckResolutionSelection(
            source_position=source_position,
            scryfall_id=scryfall_id,
            finish=normalize_finish(finish_raw),
        )
    return normalized


def _build_remote_resolution_issue(
    kind: str,
    card: RemoteDeckCard,
    *,
    options: list[Any],
) -> RemoteDeckResolutionIssue:
    return RemoteDeckResolutionIssue(
        kind=kind,
        source_position=card.source_position,
        section=card.section,
        requested=_build_remote_requested_card(card),
        options=options,
    )


def _build_unknown_remote_card_issue(card: RemoteDeckCard) -> RemoteDeckResolutionIssue:
    return _build_remote_resolution_issue("unknown_card", card, options=[])


def _remote_card_without_exact_printing(card: RemoteDeckCard) -> RemoteDeckCard:
    return RemoteDeckCard(
        source_position=card.source_position,
        quantity=card.quantity,
        section=card.section,
        scryfall_id=None,
        finish=card.finish,
        name=card.name,
        set_code=card.set_code,
        collector_number=card.collector_number,
    )


def _probe_remote_card_resolution(
    connection: sqlite3.Connection,
    *,
    card: RemoteDeckCard,
    default_inventory: str | None,
    requested_card: RemoteDeckCard | None = None,
) -> tuple[PendingImportRow | None, RemoteDeckResolutionIssue | None]:
    issue_card = requested_card or card
    if card.scryfall_id is not None:
        try:
            resolve_card_row(
                connection,
                scryfall_id=card.scryfall_id,
                oracle_id=None,
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                finish=card.finish,
            )
        except NotFoundError:
            if text_or_none(card.name) is None:
                return None, _build_unknown_remote_card_issue(issue_card)
            return _probe_remote_card_resolution(
                connection,
                card=_remote_card_without_exact_printing(card),
                default_inventory=default_inventory,
                requested_card=issue_card,
            )
        return _build_pending_remote_row(
            card,
            default_inventory=default_inventory,
            printing_selection_mode="explicit",
        ), None

    if text_or_none(card.name) is None:
        raise ValidationError("Remote deck import requires either a printing id or a card name.")

    if text_or_none(card.set_code) is None and text_or_none(card.collector_number) is None:
        try:
            candidate_rows = list_default_card_name_candidate_rows(
                connection,
                name=card.name or "",
                lang=None,
                finish=card.finish,
            )
        except NotFoundError:
            return None, _build_unknown_remote_card_issue(issue_card)
        oracle_ids = sorted({str(row["oracle_id"]) for row in candidate_rows})
        if len(oracle_ids) > 1:
            options: list[Any] = []
            for oracle_id in oracle_ids:
                resolved_card = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id=oracle_id,
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish=card.finish,
                )
                row_options, _ = build_resolution_options_for_catalog_row(
                    resolved_card,
                    requested_finish=card.finish,
                )
                options.extend(row_options)
            return None, _build_remote_resolution_issue("ambiguous_card_name", issue_card, options=options)

        resolved_card = resolve_default_card_row_for_name(
            connection,
            name=card.name or "",
            lang=None,
            finish=card.finish,
        )
        return _build_pending_remote_row(
            _remote_card_with_resolved_printing(
                card,
                scryfall_id=str(resolved_card["scryfall_id"]),
            ),
            default_inventory=default_inventory,
            printing_selection_mode=determine_printing_selection_mode(
                connection,
                scryfall_id=None,
                oracle_id=None,
                tcgplayer_product_id=None,
                name=card.name or "",
                set_code=None,
                set_name=None,
                collector_number=None,
                lang=None,
                finish=card.finish,
            ),
        ), None

    try:
        candidate_rows = list_printing_candidate_rows(
            connection,
            name=card.name or "",
            set_code=card.set_code,
            set_name=None,
            collector_number=card.collector_number,
            lang=None,
            finish=card.finish,
        )
    except NotFoundError:
        return None, _build_unknown_remote_card_issue(issue_card)
    if len(candidate_rows) > 1:
        options: list[Any] = []
        for row in candidate_rows:
            row_options, _ = build_resolution_options_for_catalog_row(
                row,
                requested_finish=card.finish,
            )
            options.extend(row_options)
        return None, _build_remote_resolution_issue("ambiguous_printing", issue_card, options=options)

    return _build_pending_remote_row(
        _remote_card_with_resolved_printing(
            card,
            scryfall_id=str(candidate_rows[0]["scryfall_id"]),
        ),
        default_inventory=default_inventory,
        printing_selection_mode="explicit",
    ), None


def _build_pending_remote_row_from_selection(
    connection: sqlite3.Connection,
    *,
    card: RemoteDeckCard,
    default_inventory: str | None,
    selection: RemoteDeckResolutionSelection,
) -> PendingImportRow:
    pending_row, resolution_issue = _probe_remote_card_resolution(
        connection,
        card=card,
        default_inventory=default_inventory,
    )
    if resolution_issue is None:
        raise ValidationError(f"Remote deck card {card.source_position} does not require an explicit resolution.")

    valid_options = {
        (option.scryfall_id, option.finish)
        for option in resolution_issue.options
    }
    if (selection.scryfall_id, selection.finish) not in valid_options:
        raise ValidationError(
            f"Remote deck card {card.source_position} resolution does not match any suggested option.",
            details={"resolution_issue": serialize_response(resolution_issue)},
        )

    resolve_card_row(
        connection,
        scryfall_id=selection.scryfall_id,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
        finish=selection.finish,
    )
    return _build_pending_remote_row(
        _remote_card_with_resolved_printing(
            card,
            scryfall_id=selection.scryfall_id,
            finish=selection.finish,
        ),
        default_inventory=default_inventory,
        printing_selection_mode="explicit",
    )


def _plan_remote_deck_import(
    prepared_db_path: str | Path,
    *,
    source_url: str,
    source_snapshot_token: str | None,
    snapshot_signing_secret: str | None,
    resolutions: list[Mapping[str, Any]] | None,
    inventory_validator: InventoryValidator | None,
    default_inventory: str,
) -> PlannedRemoteDeckImport:
    with connect(prepared_db_path) as connection:
        if inventory_validator is not None:
            inventory_validator(connection, default_inventory)
        get_inventory_row(connection, default_inventory)

    source, snapshot_token = _load_remote_source_for_import(
        source_url,
        source_snapshot_token=source_snapshot_token,
        snapshot_signing_secret=snapshot_signing_secret,
    )
    requested_card_quantity = sum(card.quantity for card in source.cards)
    selection_map = _normalize_remote_resolution_selections(resolutions)
    pending_rows: list[PendingImportRow] = []
    resolution_issues: list[RemoteDeckResolutionIssue] = []

    with connect(prepared_db_path) as connection:
        for card in source.cards:
            selection = selection_map.pop(card.source_position, None)
            if selection is not None:
                pending_rows.append(
                    _build_pending_remote_row_from_selection(
                        connection,
                        card=card,
                        default_inventory=default_inventory,
                        selection=selection,
                    )
                )
                continue

            pending_row, resolution_issue = _probe_remote_card_resolution(
                connection,
                card=card,
                default_inventory=default_inventory,
            )
            if resolution_issue is not None:
                resolution_issues.append(resolution_issue)
                continue
            if pending_row is None:
                raise AssertionError("Remote deck probe returned neither a pending row nor a resolution issue.")
            pending_rows.append(pending_row)

    if selection_map:
        unknown_positions = ", ".join(str(position) for position in sorted(selection_map))
        raise ValidationError(f"remote deck resolutions reference unknown source positions: {unknown_positions}.")

    return PlannedRemoteDeckImport(
        source=source,
        rows_seen=len(source.cards),
        requested_card_quantity=requested_card_quantity,
        source_snapshot_token=snapshot_token,
        pending_rows=pending_rows,
        resolution_issues=resolution_issues,
    )


def import_deck_url(
    db_path: str | Path,
    *,
    source_url: str,
    default_inventory: str | None,
    dry_run: bool = False,
    source_snapshot_token: str | None = None,
    snapshot_signing_secret: str | None = None,
    resolutions: list[Mapping[str, Any]] | None = None,
    before_write: Callable[[], Any] | None = None,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
    schema_policy: SchemaPreparationPolicy = "initialize_if_needed",
) -> dict[str, Any]:
    logger.info(
        "remote_deck_import_start source_url=%s default_inventory=%s dry_run=%s",
        source_url,
        default_inventory,
        dry_run,
    )
    inventory_slug = text_or_none(default_inventory)
    if inventory_slug is None:
        raise ValidationError("default_inventory is required for deck URL imports.")
    prepared_db_path = prepare_database(
        db_path,
        schema_policy=schema_policy,
    )
    plan = _plan_remote_deck_import(
        prepared_db_path,
        source_url=source_url,
        source_snapshot_token=source_snapshot_token,
        snapshot_signing_secret=snapshot_signing_secret,
        resolutions=resolutions,
        inventory_validator=inventory_validator,
        default_inventory=inventory_slug,
    )
    blocking_resolution_issues = [issue for issue in plan.resolution_issues if issue.options]
    if blocking_resolution_issues and not dry_run:
        raise ValidationError(
            "Unresolved remote deck import ambiguities remain.",
            details={
                "resolution_issues": serialize_response(plan.resolution_issues),
                "source_snapshot_token": plan.source_snapshot_token,
            },
        )
    imported_rows = _import_pending_remote_deck_rows(
        prepared_db_path,
        pending_rows=plan.pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    logger.info(
        "remote_deck_import_complete provider=%s source_url=%s default_inventory=%s dry_run=%s rows_seen=%s rows_written=%s",
        plan.source.provider,
        plan.source.source_url,
        default_inventory,
        dry_run,
        plan.rows_seen,
        len(imported_rows),
    )
    return {
        "source_url": plan.source.source_url,
        "provider": plan.source.provider,
        "deck_name": plan.source.deck_name,
        "default_inventory": default_inventory,
        "rows_seen": plan.rows_seen,
        "rows_written": len(imported_rows),
        "ready_to_commit": not blocking_resolution_issues,
        "source_snapshot_token": plan.source_snapshot_token,
        "summary": build_resolvable_deck_import_summary(
            imported_rows,
            requested_card_quantity=plan.requested_card_quantity,
        ),
        "resolution_issues": serialize_response(plan.resolution_issues),
        "dry_run": dry_run,
        "imported_rows": imported_rows,
    }


def _import_pending_remote_deck_rows(
    prepared_db_path: str | Path,
    *,
    pending_rows: list[PendingImportRow],
    dry_run: bool = False,
    before_write: Callable[[], Any] | None = None,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    return import_pending_rows(
        prepared_db_path,
        pending_rows=pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        allow_inventory_auto_create=False,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
