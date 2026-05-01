"""Inventory row lifecycle operations."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable

from ...db.connection import connect
from ...db.schema import require_current_schema
from ...errors import ConflictError, ValidationError
from ..audit import load_inventory_item_snapshot, write_inventory_audit_event
from ..money import coerce_decimal
from ..normalize import (
    normalize_condition_code,
    normalize_finish,
    normalize_inventory_slug,
    normalize_language_code,
    text_or_none,
    validate_supported_finish,
)
from ..policies import resolve_merge_acquisition, row_matches_identity
from ..query_inventory import (
    find_inventory_item_collision,
    get_inventory_item_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)
from ..response_models import MergeRowsResult, RemoveCardResult, SplitRowResult, inventory_item_response_kwargs

__all__ = ["merge_rows", "remove_card", "split_row"]


def _prepared_db_path(db_path: str | Path) -> Path:
    return require_current_schema(db_path)


def _split_row_concurrent_collision_error() -> ConflictError:
    return ConflictError(
        "Splitting row would collide with an existing inventory row due to a concurrent write. Retry the request."
    )


def split_row(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    quantity: int,
    condition_code: str | None,
    finish: str | None,
    language_code: str | None,
    location: str | None,
    clear_location: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], object] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SplitRowResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if quantity <= 0:
        raise ValidationError("--quantity must be a positive integer.")
    if clear_location and location is not None:
        raise ValidationError("Use either --location or --clear-location, not both.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        source_item = get_inventory_item_row(connection, inventory_slug, item_id)
        source_before_snapshot = inventory_item_result_from_row(source_item)
        source_quantity = int(source_item["quantity"])
        if quantity > source_quantity:
            raise ValidationError("--quantity cannot exceed the current row quantity.")

        target_condition = (
            normalize_condition_code(condition_code) if condition_code is not None else source_item["condition_code"]
        )
        target_finish = normalize_finish(finish) if finish is not None else source_item["finish"]
        target_language = (
            normalize_language_code(language_code) if language_code is not None else source_item["language_code"]
        )
        validate_supported_finish(source_item["finishes_json"], target_finish)
        if clear_location:
            target_location = ""
        elif location is not None:
            target_location = text_or_none(location) or ""
        else:
            target_location = source_item["location"]

        if row_matches_identity(
            source_item,
            condition_code=target_condition,
            finish=target_finish,
            language_code=target_language,
            location=target_location,
        ):
            raise ValidationError(
                "split-row needs a different condition, finish, language, or location for the target row."
            )

        target_item = find_inventory_item_collision(
            connection,
            inventory_id=source_item["inventory_id"],
            scryfall_id=source_item["scryfall_id"],
            condition_code=target_condition,
            finish=target_finish,
            language_code=target_language,
            location=target_location,
            exclude_item_id=item_id,
        )

        if target_item is not None:
            resolve_merge_acquisition(
                source_item,
                target_item,
                acquisition_preference=keep_acquisition,
            )
            target_before_snapshot = inventory_item_result_from_row(target_item)
        else:
            target_before_snapshot = None

        if before_write is not None:
            before_write()
        remaining_quantity = source_quantity - quantity
        if remaining_quantity == 0:
            connection.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
            source_deleted = True
        else:
            connection.execute(
                """
                UPDATE inventory_items
                SET quantity = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (remaining_quantity, item_id),
            )
            source_deleted = False

        if target_item is not None:
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=source_item,
                target_item=target_item,
                source_quantity=quantity,
                delete_source=False,
                acquisition_preference=keep_acquisition,
            )
            result["merged_into_existing"] = True
            target_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=int(result["item_id"]),
            )
        else:
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO inventory_items (
                        inventory_id,
                        scryfall_id,
                        quantity,
                        condition_code,
                        finish,
                        language_code,
                        location,
                        acquisition_price,
                        acquisition_currency,
                        notes,
                        tags_json,
                        printing_selection_mode
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (
                        source_item["inventory_id"],
                        source_item["scryfall_id"],
                        quantity,
                        target_condition,
                        target_finish,
                        target_language,
                        target_location,
                        coerce_decimal(source_item["acquisition_price"]),
                        text_or_none(source_item["acquisition_currency"]),
                        text_or_none(source_item["notes"]),
                        source_item["tags_json"],
                        source_item["printing_selection_mode"],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise _split_row_concurrent_collision_error() from exc
            new_item_id = cursor.fetchone()["id"]
            new_item_row = get_inventory_item_row(connection, inventory_slug, new_item_id)
            result = inventory_item_result_from_row(new_item_row)
            result["merged_into_existing"] = False
            target_after_snapshot = inventory_item_result_from_row(new_item_row)

        if source_deleted:
            source_after_snapshot = None
        else:
            source_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=item_id,
            )

        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="split_row",
            item_id=item_id,
            before=source_before_snapshot,
            after=source_after_snapshot,
            metadata={
                "role": "source",
                "moved_quantity": quantity,
                "source_deleted": source_deleted,
                "target_item_id": int(result["item_id"]),
                "merged_into_existing": bool(result["merged_into_existing"]),
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="split_row",
            item_id=int(result["item_id"]),
            before=target_before_snapshot,
            after=target_after_snapshot,
            metadata={
                "role": "target",
                "source_item_id": item_id,
                "moved_quantity": quantity,
                "merged_into_existing": bool(result["merged_into_existing"]),
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )

        connection.commit()

    return SplitRowResult(
        **inventory_item_response_kwargs(result),
        merged_into_existing=bool(result["merged_into_existing"]),
        source_item_id=item_id,
        source_old_quantity=source_quantity,
        source_quantity=remaining_quantity,
        source_deleted=source_deleted,
        moved_quantity=quantity,
    )


def merge_rows(
    db_path: str | Path,
    *,
    inventory_slug: str,
    source_item_id: int,
    target_item_id: int,
    keep_acquisition: str | None = None,
    before_write: Callable[[], object] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> MergeRowsResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if source_item_id == target_item_id:
        raise ValidationError("Choose two different item ids when using merge-rows.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        source_item = get_inventory_item_row(connection, inventory_slug, source_item_id)
        target_item = get_inventory_item_row(connection, inventory_slug, target_item_id)
        source_before_snapshot = inventory_item_result_from_row(source_item)
        target_before_snapshot = inventory_item_result_from_row(target_item)

        if source_item["scryfall_id"] != target_item["scryfall_id"]:
            raise ValidationError("merge-rows currently requires both rows to reference the same printing.")

        if before_write is not None:
            before_write()
        result = merge_inventory_item_rows(
            connection,
            inventory_slug=inventory_slug,
            source_item=source_item,
            target_item=target_item,
            acquisition_preference=keep_acquisition,
        )
        target_after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=target_item_id,
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="merge_rows",
            item_id=source_item_id,
            before=source_before_snapshot,
            after=None,
            metadata={
                "role": "source",
                "target_item_id": target_item_id,
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="merge_rows",
            item_id=target_item_id,
            before=target_before_snapshot,
            after=target_after_snapshot,
            metadata={
                "role": "target",
                "source_item_id": source_item_id,
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return MergeRowsResult(
        **inventory_item_response_kwargs(result),
        merged_source_item_id=int(result["merged_source_item_id"]),
        source_quantity=int(source_item["quantity"]),
        target_old_quantity=int(target_item["quantity"]),
    )


def remove_card(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    before_write: Callable[[], object] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> RemoveCardResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if before_write is not None:
            before_write()
        connection.execute(
            """
            DELETE FROM inventory_items
            WHERE id = ?
            """,
            (item_id,),
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="remove_card",
            item_id=item_id,
            before=before_snapshot,
            after=None,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return RemoveCardResult(**inventory_item_response_kwargs(before_snapshot))
