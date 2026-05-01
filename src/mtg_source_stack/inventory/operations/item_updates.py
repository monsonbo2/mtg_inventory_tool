"""Simple inventory item field updates."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
from pathlib import Path
from typing import Callable

from ...db.connection import connect
from ...db.schema import require_current_schema
from ...errors import ConflictError, ValidationError
from ..audit import load_inventory_item_snapshot, write_inventory_audit_event
from ..money import coerce_decimal
from ..normalize import (
    normalize_currency_code,
    normalize_finish,
    normalize_inventory_slug,
    parse_tags,
    tags_to_json,
    text_or_none,
    validate_supported_finish,
)
from ..query_inventory import get_inventory_item_row, inventory_item_result_from_row
from ..response_models import (
    SetAcquisitionResult,
    SetFinishResult,
    SetNotesResult,
    SetQuantityResult,
    SetTagsResult,
    inventory_item_response_kwargs,
)

__all__ = [
    "set_acquisition",
    "set_finish",
    "set_finish_with_connection",
    "set_notes",
    "set_quantity",
    "set_tags",
]


def _prepared_db_path(db_path: str | Path) -> Path:
    return require_current_schema(db_path)


def _set_finish_collision_error() -> ConflictError:
    return ConflictError(
        "Changing finish would collide with an existing inventory row. Resolve the duplicate row first."
    )


def set_quantity(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    quantity: int,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetQuantityResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if quantity <= 0:
        raise ValidationError("--quantity must be a positive integer. Use remove-card to delete a row.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        connection.execute(
            """
            UPDATE inventory_items
            SET quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (quantity, item_id),
        )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_quantity",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={"old_quantity": int(item["quantity"]), "new_quantity": quantity},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetQuantityResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_quantity",
        old_quantity=int(item["quantity"]),
    )


def set_acquisition(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    clear: bool = False,
    before_write: Callable[[], object] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetAcquisitionResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if clear and (acquisition_price is not None or acquisition_currency is not None):
        raise ValidationError("Use either --clear or --price / --currency, not both.")
    if not clear and acquisition_price is None and acquisition_currency is None:
        raise ValidationError("Provide at least one of --price or --currency, or use --clear.")
    normalized_acquisition_price = coerce_decimal(acquisition_price)
    if normalized_acquisition_price is not None and normalized_acquisition_price < 0:
        raise ValidationError("--price must be zero or greater.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        current_currency = text_or_none(item["acquisition_currency"])
        new_price = None if clear else coerce_decimal(item["acquisition_price"])
        new_currency = None if clear else current_currency

        if normalized_acquisition_price is not None:
            new_price = normalized_acquisition_price
        if acquisition_currency is not None:
            new_currency = normalize_currency_code(acquisition_currency)

        if new_price is None and new_currency is not None:
            raise ValidationError(
                "Cannot store an acquisition currency without an acquisition price. Use --price too, or --clear."
            )

        if before_write is not None:
            before_write()
        connection.execute(
            """
            UPDATE inventory_items
            SET acquisition_price = ?, acquisition_currency = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_price, new_currency, item_id),
        )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_acquisition",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={"clear": clear},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetAcquisitionResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_acquisition",
        old_acquisition_price=coerce_decimal(item["acquisition_price"]),
        old_acquisition_currency=current_currency,
    )


def set_finish_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_id: int,
    finish: str,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetFinishResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    item = get_inventory_item_row(connection, inventory_slug, item_id)
    before_snapshot = inventory_item_result_from_row(item)
    normalized_finish = normalize_finish(finish)
    validate_supported_finish(item["finishes_json"], normalized_finish)
    if normalized_finish == item["finish"]:
        return SetFinishResult(
            **inventory_item_response_kwargs(before_snapshot),
            operation="set_finish",
            old_finish=str(item["finish"]),
        )

    try:
        connection.execute(
            """
            UPDATE inventory_items
            SET finish = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_finish, item_id),
        )
    except sqlite3.IntegrityError as exc:
        raise _set_finish_collision_error() from exc

    after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
    after_row = get_inventory_item_row(connection, inventory_slug, item_id)
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_finish",
        item_id=item_id,
        before=before_snapshot,
        after=after_snapshot,
        metadata={"old_finish": item["finish"], "new_finish": normalized_finish},
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )

    return SetFinishResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_finish",
        old_finish=str(item["finish"]),
    )


def set_finish(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    finish: str,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetFinishResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        result = set_finish_with_connection(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
            finish=finish,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()
    return result


def set_notes(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    notes: str | None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetNotesResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_notes = text_or_none(notes)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        connection.execute(
            """
            UPDATE inventory_items
            SET notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_notes, item_id),
        )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_notes",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetNotesResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_notes",
        old_notes=text_or_none(item["notes"]),
    )


def set_tags(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    tags: str | None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetTagsResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        normalized_tags = parse_tags(tags)
        connection.execute(
            """
            UPDATE inventory_items
            SET tags_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (tags_to_json(normalized_tags), item_id),
        )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_tags",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetTagsResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_tags",
        old_tags=list(before_snapshot["tags"]),
    )
