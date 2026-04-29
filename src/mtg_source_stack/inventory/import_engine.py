"""Shared inventory import commit helpers."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..db.connection import connect
from ..errors import MtgStackError, ValidationError
from .catalog import resolve_card_row
from .mutations import add_card_with_connection
from .normalize import normalize_external_id, normalized_catalog_finish_list
from .response_models import serialize_response


InventoryValidator = Callable[[sqlite3.Connection, str], Any]


@dataclass(frozen=True, slots=True)
class PendingImportRow:
    row_number: int
    add_kwargs: dict[str, Any]
    response_metadata: dict[str, Any]
    error_label: str
    finish_source: str = "finish"


def _resolve_pending_row_finish(
    connection: sqlite3.Connection,
    *,
    add_kwargs: dict[str, Any],
    finish_source: str,
) -> sqlite3.Row | None:
    if finish_source != "default":
        return None

    card = resolve_card_row(
        connection,
        scryfall_id=add_kwargs["scryfall_id"],
        oracle_id=add_kwargs["oracle_id"],
        tcgplayer_product_id=normalize_external_id(add_kwargs["tcgplayer_product_id"]),
        name=add_kwargs["name"],
        set_code=add_kwargs["set_code"],
        set_name=add_kwargs["set_name"],
        collector_number=add_kwargs["collector_number"],
        lang=add_kwargs["lang"],
        finish=None,
    )
    available_finishes = normalized_catalog_finish_list(card["finishes_json"])
    if len(available_finishes) == 1:
        add_kwargs["finish"] = available_finishes[0]
        return card
    if len(available_finishes) > 1:
        raise ValidationError(
            "finish is required for this printing when multiple finishes are available. "
            f"Available finishes: {', '.join(available_finishes)}."
        )
    return card


def _import_pending_rows(
    prepared_db_path: str | Path,
    *,
    pending_rows: list[PendingImportRow],
    dry_run: bool = False,
    before_write: Callable[[], Any] | None = None,
    allow_inventory_auto_create: bool = True,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    imported_rows: list[dict[str, Any]] = []
    inventory_cache: dict[str, sqlite3.Row] = {}

    with connect(prepared_db_path) as connection:
        validated_inventories: set[str] = set()
        for pending_row in pending_rows:
            inventory_slug = str(pending_row.add_kwargs["inventory_slug"])
            if inventory_slug in validated_inventories:
                continue
            if inventory_validator is not None:
                inventory_validator(connection, inventory_slug)
            validated_inventories.add(inventory_slug)

        for pending_row in pending_rows:
            row_add_kwargs = dict(pending_row.add_kwargs)
            if not allow_inventory_auto_create:
                row_add_kwargs["inventory_display_name"] = None

            finish_source = pending_row.finish_source
            row_add_kwargs.pop("_finish_source", None)
            try:
                resolved_card = _resolve_pending_row_finish(
                    connection,
                    add_kwargs=row_add_kwargs,
                    finish_source=finish_source,
                )
                result = add_card_with_connection(
                    connection,
                    inventory_cache=inventory_cache,
                    before_write=None if dry_run else before_write,
                    resolved_card=resolved_card,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    request_id=request_id,
                    **row_add_kwargs,
                )
            except MtgStackError as exc:
                raise type(exc)(
                    f"{pending_row.error_label} {pending_row.row_number}: {exc}",
                    error_code=exc.error_code,
                ) from exc
            except ValueError as exc:
                raise ValueError(f"{pending_row.error_label} {pending_row.row_number}: {exc}") from exc
            imported_rows.append({**pending_row.response_metadata, **serialize_response(result)})

        if dry_run:
            # Preview mode reuses the real add-card workflow, then rolls
            # back at the end so validation and reporting stay identical.
            connection.rollback()
        else:
            connection.commit()

    return imported_rows
