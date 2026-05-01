"""Remote deck URL import helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Mapping

from ..db.schema import SchemaPreparationPolicy, prepare_database
from ..errors import ValidationError
from .import_engine import InventoryValidator, PendingImportRow
from .import_summary import build_resolvable_deck_import_summary
from .normalize import text_or_none
from .remote_deck_planning import (
    PlannedRemoteDeckImport,
    _build_add_card_kwargs_from_remote_card,
    _build_pending_remote_row,
    _build_pending_remote_row_from_selection,
    _build_remote_requested_card,
    _build_remote_resolution_issue,
    _build_unknown_remote_card_issue,
    _import_pending_remote_deck_rows as _import_pending_remote_deck_rows_impl,
    _load_remote_source_for_import as _load_remote_source_for_import_impl,
    _normalize_remote_resolution_selections,
    _plan_remote_deck_import as _plan_remote_deck_import_impl,
    _probe_remote_card_resolution,
    _remote_card_with_resolved_printing,
    _remote_card_without_exact_printing,
)
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


def _load_remote_source_for_import(
    source_url: str,
    *,
    source_snapshot_token: str | None = None,
    snapshot_signing_secret: str | None = None,
) -> tuple[RemoteDeckSource, str]:
    return _load_remote_source_for_import_impl(
        source_url,
        source_snapshot_token=source_snapshot_token,
        snapshot_signing_secret=snapshot_signing_secret,
        fetch_remote_source=fetch_remote_deck_source,
        decode_snapshot_token=_decode_remote_source_snapshot_token,
        encode_snapshot_token=_encode_remote_source_snapshot_token,
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
    return _plan_remote_deck_import_impl(
        prepared_db_path,
        source_url=source_url,
        source_snapshot_token=source_snapshot_token,
        snapshot_signing_secret=snapshot_signing_secret,
        resolutions=resolutions,
        inventory_validator=inventory_validator,
        default_inventory=default_inventory,
        load_remote_source_for_import=_load_remote_source_for_import,
    )


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
    return _import_pending_remote_deck_rows_impl(
        prepared_db_path,
        pending_rows=pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
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
