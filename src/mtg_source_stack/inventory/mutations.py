"""Inventory write operations and row-shaping mutations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ConflictError, NotFoundError, ValidationError
from .audit import load_inventory_item_snapshot, write_inventory_audit_event
from .catalog import resolve_card_row
from .money import coerce_decimal
from .normalize import (
    load_tags_json,
    merge_tags,
    normalize_condition_code,
    normalize_currency_code,
    normalize_external_id,
    normalize_finish,
    normalize_inventory_slug,
    normalize_language_code,
    normalize_tags,
    parse_tags,
    tags_to_json,
    text_or_none,
    validate_supported_finish,
)
from .policies import ensure_add_card_metadata_compatible, resolve_merge_acquisition, row_matches_identity
from .query_inventory import (
    find_inventory_item_collision,
    get_inventory_item_row,
    get_inventory_row,
    get_or_create_inventory_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)
from .response_models import (
    AddCardResult,
    BulkInventoryItemMutationResult,
    MergeRowsResult,
    RemoveCardResult,
    SetAcquisitionResult,
    SetConditionResult,
    SetFinishResult,
    SetLocationResult,
    SetNotesResult,
    SetQuantityResult,
    SetTagsResult,
    SplitRowResult,
    inventory_item_response_kwargs,
)


def _build_add_card_result(payload: dict[str, Any]) -> AddCardResult:
    return AddCardResult(**inventory_item_response_kwargs(payload))


def _prepared_db_path(db_path: str | Path) -> Path:
    return require_current_schema(db_path)


def _add_card_concurrent_collision_error() -> ConflictError:
    return ConflictError(
        "Adding card would collide with an existing inventory row due to a concurrent write. Retry the request."
    )


def _set_location_collision_error() -> ConflictError:
    return ConflictError(
        "Changing location would collide with an existing inventory row. "
        "Re-run with --merge to combine the rows, or resolve the duplicate row first."
    )


def _set_location_concurrent_merge_error() -> ConflictError:
    return ConflictError(
        "Changing location collided with another concurrent write while merging. Retry the request."
    )


def _set_condition_collision_error() -> ConflictError:
    return ConflictError(
        "Changing condition would collide with an existing inventory row. "
        "Re-run with --merge to combine the rows, or resolve the duplicate row first."
    )


def _set_condition_concurrent_merge_error() -> ConflictError:
    return ConflictError(
        "Changing condition collided with another concurrent write while merging. Retry the request."
    )


def _split_row_concurrent_collision_error() -> ConflictError:
    return ConflictError(
        "Splitting row would collide with an existing inventory row due to a concurrent write. Retry the request."
    )


_BULK_TAG_OPERATIONS = frozenset({"add_tags", "clear_tags", "remove_tags", "set_tags"})
_BULK_QUANTITY_OPERATIONS = frozenset({"set_quantity"})
_BULK_NOTES_OPERATIONS = frozenset({"set_notes"})
_BULK_ACQUISITION_OPERATIONS = frozenset({"set_acquisition"})
_BULK_FINISH_OPERATIONS = frozenset({"set_finish"})
_BULK_LOCATION_OPERATIONS = frozenset({"set_location"})
_BULK_CONDITION_OPERATIONS = frozenset({"set_condition"})
_SUPPORTED_BULK_ITEM_OPERATIONS = frozenset(
    _BULK_TAG_OPERATIONS
    | _BULK_QUANTITY_OPERATIONS
    | _BULK_NOTES_OPERATIONS
    | _BULK_ACQUISITION_OPERATIONS
    | _BULK_FINISH_OPERATIONS
    | _BULK_LOCATION_OPERATIONS
    | _BULK_CONDITION_OPERATIONS
)


@dataclass(frozen=True, slots=True)
class _BulkMutationRequest:
    operation: str
    item_ids: list[int]
    tags: list[str] | None = None
    quantity: int | None = None
    notes: str | None = None
    clear_notes: bool = False
    acquisition_price: Decimal | None = None
    acquisition_currency: str | None = None
    clear_acquisition: bool = False
    finish: str | None = None
    location: str | None = None
    clear_location: bool = False
    condition_code: str | None = None
    merge: bool = False
    keep_acquisition: str | None = None


@dataclass(frozen=True, slots=True)
class _BulkPlannedItemUpdate:
    row: sqlite3.Row
    before_snapshot: dict[str, Any]
    column_values: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _PendingBulkAuditEvent:
    item_id: int
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    metadata: dict[str, Any]


def _bulk_item_operation_error() -> ValidationError:
    supported_operations = ", ".join(sorted(_SUPPORTED_BULK_ITEM_OPERATIONS))
    return ValidationError(f"bulk operation must be one of: {supported_operations}.")


def _bulk_item_field_error(*, field_name: str, operation: str) -> ValidationError:
    return ValidationError(f"{field_name} is not valid for {operation}.")


def _set_finish_collision_error() -> ConflictError:
    return ConflictError(
        "Changing finish would collide with an existing inventory row. Resolve the duplicate row first."
    )


def _validate_bulk_fields_omitted(
    *,
    operation: str,
    tags: list[str] | None = None,
    quantity: int | None = None,
    notes: str | None = None,
    clear_notes: bool = False,
    acquisition_price: Decimal | None = None,
    acquisition_currency: str | None = None,
    clear_acquisition: bool = False,
    finish: str | None = None,
    location: str | None = None,
    clear_location: bool = False,
    condition_code: str | None = None,
    merge: bool = False,
    keep_acquisition: str | None = None,
) -> None:
    if tags is not None:
        raise _bulk_item_field_error(field_name="tags", operation=operation)
    if quantity is not None:
        raise _bulk_item_field_error(field_name="quantity", operation=operation)
    if notes is not None:
        raise _bulk_item_field_error(field_name="notes", operation=operation)
    if clear_notes:
        raise _bulk_item_field_error(field_name="clear_notes", operation=operation)
    if acquisition_price is not None:
        raise _bulk_item_field_error(field_name="acquisition_price", operation=operation)
    if acquisition_currency is not None:
        raise _bulk_item_field_error(field_name="acquisition_currency", operation=operation)
    if clear_acquisition:
        raise _bulk_item_field_error(field_name="clear_acquisition", operation=operation)
    if finish is not None:
        raise _bulk_item_field_error(field_name="finish", operation=operation)
    if location is not None:
        raise _bulk_item_field_error(field_name="location", operation=operation)
    if clear_location:
        raise _bulk_item_field_error(field_name="clear_location", operation=operation)
    if condition_code is not None:
        raise _bulk_item_field_error(field_name="condition_code", operation=operation)
    if merge:
        raise _bulk_item_field_error(field_name="merge", operation=operation)
    if keep_acquisition is not None:
        raise _bulk_item_field_error(field_name="keep_acquisition", operation=operation)


def _normalize_bulk_item_ids(item_ids: list[int]) -> list[int]:
    if not item_ids:
        raise ValidationError("item_ids must include at least one item id.")
    if len(set(item_ids)) != len(item_ids):
        raise ValidationError("item_ids must not contain duplicates.")
    if len(item_ids) > 100:
        raise ValidationError("item_ids must not contain more than 100 ids.")
    return list(item_ids)


def _normalized_bulk_tags(*, operation: str, tags: list[str] | None) -> list[str]:
    if operation not in _BULK_TAG_OPERATIONS:
        raise _bulk_item_operation_error()
    if operation == "clear_tags":
        if tags is not None:
            raise ValidationError("tags must be omitted for clear_tags.")
        return []

    if tags is None:
        raise ValidationError(f"tags are required for {operation}.")
    normalized_tags = normalize_tags(tags)
    if not normalized_tags:
        raise ValidationError(f"tags must include at least one tag for {operation}.")
    return normalized_tags


def _normalize_bulk_mutation_request(
    *,
    operation: str,
    item_ids: list[int],
    tags: list[str] | None,
    quantity: int | None,
    notes: str | None,
    clear_notes: bool,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    clear_acquisition: bool,
    finish: str | None,
    location: str | None,
    clear_location: bool,
    condition_code: str | None,
    merge: bool,
    keep_acquisition: str | None,
) -> _BulkMutationRequest:
    normalized_item_ids = _normalize_bulk_item_ids(item_ids)
    if operation not in _SUPPORTED_BULK_ITEM_OPERATIONS:
        raise _bulk_item_operation_error()

    normalized_tags: list[str] | None = None
    if operation in _BULK_TAG_OPERATIONS:
        normalized_tags = _normalized_bulk_tags(operation=operation, tags=tags)
        _validate_bulk_fields_omitted(
            operation=operation,
            quantity=quantity,
            notes=notes,
            clear_notes=clear_notes,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            clear_acquisition=clear_acquisition,
            finish=finish,
            location=location,
            clear_location=clear_location,
            condition_code=condition_code,
            merge=merge,
            keep_acquisition=keep_acquisition,
        )
    elif operation in _BULK_QUANTITY_OPERATIONS:
        _validate_bulk_fields_omitted(
            operation=operation,
            tags=tags,
            notes=notes,
            clear_notes=clear_notes,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            clear_acquisition=clear_acquisition,
            finish=finish,
            location=location,
            clear_location=clear_location,
            condition_code=condition_code,
            merge=merge,
            keep_acquisition=keep_acquisition,
        )
        if quantity is None:
            raise ValidationError("quantity is required for set_quantity.")
        if quantity <= 0:
            raise ValidationError("quantity must be a positive integer for set_quantity.")
    elif operation in _BULK_NOTES_OPERATIONS:
        _validate_bulk_fields_omitted(
            operation=operation,
            tags=tags,
            quantity=quantity,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            clear_acquisition=clear_acquisition,
            finish=finish,
            location=location,
            clear_location=clear_location,
            condition_code=condition_code,
            merge=merge,
            keep_acquisition=keep_acquisition,
        )
        if clear_notes and notes is not None:
            raise ValidationError("notes must be omitted when clear_notes is true for set_notes.")
        if not clear_notes and notes is None:
            raise ValidationError("notes are required for set_notes unless clear_notes is true.")
    elif operation in _BULK_ACQUISITION_OPERATIONS:
        _validate_bulk_fields_omitted(
            operation=operation,
            tags=tags,
            quantity=quantity,
            notes=notes,
            clear_notes=clear_notes,
            finish=finish,
            location=location,
            clear_location=clear_location,
            condition_code=condition_code,
            merge=merge,
            keep_acquisition=keep_acquisition,
        )
        if clear_acquisition and (acquisition_price is not None or acquisition_currency is not None):
            raise ValidationError(
                "Use either clear_acquisition or acquisition_price / acquisition_currency for set_acquisition, not both."
            )
        if not clear_acquisition and acquisition_price is None and acquisition_currency is None:
            raise ValidationError(
                "Provide at least one of acquisition_price or acquisition_currency for set_acquisition, or use clear_acquisition."
            )
        if acquisition_price is not None and acquisition_price < 0:
            raise ValidationError("acquisition_price must be zero or greater for set_acquisition.")
        if acquisition_currency is not None:
            acquisition_currency = normalize_currency_code(acquisition_currency)
    elif operation in _BULK_FINISH_OPERATIONS:
        _validate_bulk_fields_omitted(
            operation=operation,
            tags=tags,
            quantity=quantity,
            notes=notes,
            clear_notes=clear_notes,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            clear_acquisition=clear_acquisition,
            location=location,
            clear_location=clear_location,
            condition_code=condition_code,
            merge=merge,
            keep_acquisition=keep_acquisition,
        )
        if finish is None:
            raise ValidationError("finish is required for set_finish.")
        finish = normalize_finish(finish)
    elif operation in _BULK_LOCATION_OPERATIONS:
        _validate_bulk_fields_omitted(
            operation=operation,
            tags=tags,
            quantity=quantity,
            notes=notes,
            clear_notes=clear_notes,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            clear_acquisition=clear_acquisition,
            finish=finish,
            condition_code=condition_code,
        )
        if clear_location and location is not None:
            raise ValidationError("Use either location or clear_location for set_location, not both.")
        if not clear_location and location is None:
            raise ValidationError("location is required for set_location unless clear_location is true.")
        if keep_acquisition not in (None, "source", "target"):
            raise ValidationError("keep_acquisition must be one of: source, target.")
        if not merge and keep_acquisition is not None:
            raise ValidationError("keep_acquisition only applies when merge is true for set_location.")
        location = "" if clear_location else (text_or_none(location) or "")
    elif operation in _BULK_CONDITION_OPERATIONS:
        _validate_bulk_fields_omitted(
            operation=operation,
            tags=tags,
            quantity=quantity,
            notes=notes,
            clear_notes=clear_notes,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            clear_acquisition=clear_acquisition,
            finish=finish,
            location=location,
            clear_location=clear_location,
        )
        if condition_code is None:
            raise ValidationError("condition_code is required for set_condition.")
        condition_code = normalize_condition_code(condition_code)
        if keep_acquisition not in (None, "source", "target"):
            raise ValidationError("keep_acquisition must be one of: source, target.")
        if not merge and keep_acquisition is not None:
            raise ValidationError("keep_acquisition only applies when merge is true for set_condition.")

    return _BulkMutationRequest(
        operation=operation,
        item_ids=normalized_item_ids,
        tags=normalized_tags,
        quantity=quantity,
        notes=None if clear_notes else text_or_none(notes),
        clear_notes=clear_notes,
        acquisition_price=acquisition_price,
        acquisition_currency=acquisition_currency,
        clear_acquisition=clear_acquisition,
        finish=finish,
        location=location,
        clear_location=clear_location,
        condition_code=condition_code,
        merge=merge,
        keep_acquisition=keep_acquisition,
    )


def _load_bulk_inventory_item_rows(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_ids: list[int],
) -> list[sqlite3.Row]:
    inventory = get_inventory_row(connection, inventory_slug)
    placeholders = ", ".join("?" for _ in item_ids)
    rows = connection.execute(
        f"""
        SELECT
            ii.id AS item_id,
            ii.inventory_id,
            i.slug AS inventory,
            ii.scryfall_id,
            c.name AS card_name,
            c.set_code,
            c.set_name,
            c.collector_number,
            c.finishes_json,
            ii.quantity,
            ii.condition_code,
            ii.finish,
            ii.language_code,
            ii.location,
            ii.acquisition_price,
            ii.acquisition_currency,
            ii.notes,
            COALESCE(ii.tags_json, '[]') AS tags_json
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        WHERE ii.inventory_id = ?
          AND ii.id IN ({placeholders})
        """,
        (inventory["id"], *item_ids),
    ).fetchall()
    if len(rows) != len(item_ids):
        raise NotFoundError(
            f"One or more item_ids were not found in inventory '{inventory_slug}'."
        )
    rows_by_id = {int(row["item_id"]): row for row in rows}
    return [rows_by_id[item_id] for item_id in item_ids]


def _bulk_tags_for_operation(*, operation: str, current_tags: list[str], requested_tags: list[str]) -> list[str]:
    if operation == "add_tags":
        return merge_tags(current_tags, requested_tags)
    if operation == "remove_tags":
        requested = set(requested_tags)
        return [tag for tag in current_tags if tag not in requested]
    if operation == "set_tags":
        return list(requested_tags)
    if operation == "clear_tags":
        return []
    raise _bulk_item_operation_error()


def _plan_bulk_tag_update(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    request: _BulkMutationRequest,
) -> _BulkPlannedItemUpdate | None:
    before_snapshot = inventory_item_result_from_row(row)
    current_tags = list(before_snapshot["tags"])
    next_tags = _bulk_tags_for_operation(
        operation=request.operation,
        current_tags=current_tags,
        requested_tags=list(request.tags or []),
    )
    if next_tags == current_tags:
        return None
    return _BulkPlannedItemUpdate(
        row=row,
        before_snapshot=before_snapshot,
        column_values={"tags_json": tags_to_json(next_tags)},
        metadata={},
    )


def _plan_bulk_quantity_update(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    request: _BulkMutationRequest,
) -> _BulkPlannedItemUpdate | None:
    before_snapshot = inventory_item_result_from_row(row)
    current_quantity = int(before_snapshot["quantity"])
    next_quantity = int(request.quantity or 0)
    if next_quantity == current_quantity:
        return None
    return _BulkPlannedItemUpdate(
        row=row,
        before_snapshot=before_snapshot,
        column_values={"quantity": next_quantity},
        metadata={"old_quantity": current_quantity, "new_quantity": next_quantity},
    )


def _plan_bulk_notes_update(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    request: _BulkMutationRequest,
) -> _BulkPlannedItemUpdate | None:
    before_snapshot = inventory_item_result_from_row(row)
    current_notes = text_or_none(before_snapshot["notes"])
    next_notes = None if request.clear_notes else text_or_none(request.notes)
    if next_notes == current_notes:
        return None
    return _BulkPlannedItemUpdate(
        row=row,
        before_snapshot=before_snapshot,
        column_values={"notes": next_notes},
        metadata={},
    )


def _plan_bulk_acquisition_update(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    request: _BulkMutationRequest,
) -> _BulkPlannedItemUpdate | None:
    before_snapshot = inventory_item_result_from_row(row)
    current_price = coerce_decimal(before_snapshot["acquisition_price"])
    current_currency = text_or_none(before_snapshot["acquisition_currency"])

    if request.clear_acquisition:
        next_price = None
        next_currency = None
    else:
        next_price = current_price if request.acquisition_price is None else request.acquisition_price
        next_currency = current_currency if request.acquisition_currency is None else request.acquisition_currency
        if next_price is None and next_currency is not None:
            raise ValidationError(
                "Cannot store an acquisition currency without an acquisition price. Use acquisition_price too, or clear_acquisition."
            )

    if next_price == current_price and next_currency == current_currency:
        return None
    return _BulkPlannedItemUpdate(
        row=row,
        before_snapshot=before_snapshot,
        column_values={"acquisition_price": next_price, "acquisition_currency": next_currency},
        metadata={"clear": request.clear_acquisition},
    )


def _plan_bulk_finish_update(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    request: _BulkMutationRequest,
) -> _BulkPlannedItemUpdate | None:
    before_snapshot = inventory_item_result_from_row(row)
    current_finish = str(before_snapshot["finish"])
    next_finish = str(request.finish)
    validate_supported_finish(row["finishes_json"], next_finish)
    if next_finish == current_finish:
        return None
    collision = find_inventory_item_collision(
        connection,
        inventory_id=int(row["inventory_id"]),
        scryfall_id=str(row["scryfall_id"]),
        condition_code=str(row["condition_code"]),
        finish=next_finish,
        language_code=str(row["language_code"]),
        location=str(row["location"]),
        exclude_item_id=int(row["item_id"]),
    )
    if collision is not None:
        raise _set_finish_collision_error()
    return _BulkPlannedItemUpdate(
        row=row,
        before_snapshot=before_snapshot,
        column_values={"finish": next_finish},
        metadata={"old_finish": current_finish, "new_finish": next_finish},
    )


def _planner_for_bulk_item_operation(
    operation: str,
) -> Callable[[sqlite3.Connection, sqlite3.Row, _BulkMutationRequest], _BulkPlannedItemUpdate | None]:
    if operation in _BULK_TAG_OPERATIONS:
        return _plan_bulk_tag_update
    if operation in _BULK_QUANTITY_OPERATIONS:
        return _plan_bulk_quantity_update
    if operation in _BULK_NOTES_OPERATIONS:
        return _plan_bulk_notes_update
    if operation in _BULK_ACQUISITION_OPERATIONS:
        return _plan_bulk_acquisition_update
    if operation in _BULK_FINISH_OPERATIONS:
        return _plan_bulk_finish_update
    raise _bulk_item_operation_error()


def _plan_bulk_item_updates(
    *,
    connection: sqlite3.Connection,
    item_rows: list[sqlite3.Row],
    request: _BulkMutationRequest,
) -> list[_BulkPlannedItemUpdate]:
    planner = _planner_for_bulk_item_operation(request.operation)
    planned_updates: list[_BulkPlannedItemUpdate] = []
    for row in item_rows:
        planned_update = planner(connection, row, request)
        if planned_update is not None:
            planned_updates.append(planned_update)
    return planned_updates


def _apply_bulk_item_update(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    request: _BulkMutationRequest,
    planned_update: _BulkPlannedItemUpdate,
    updated_count: int,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> int:
    assignments: list[str] = []
    parameters: list[Any] = []
    for column_name, column_value in planned_update.column_values.items():
        assignments.append(f"{column_name} = ?")
        parameters.append(column_value)
    assignments.append("updated_at = CURRENT_TIMESTAMP")
    parameters.append(int(planned_update.row["item_id"]))
    try:
        connection.execute(
            f"""
            UPDATE inventory_items
            SET {", ".join(assignments)}
            WHERE id = ?
            """,
            parameters,
        )
    except sqlite3.IntegrityError as exc:
        if request.operation in _BULK_FINISH_OPERATIONS:
            raise _set_finish_collision_error() from exc
        raise
    item_id = int(planned_update.row["item_id"])
    after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
    metadata = dict(planned_update.metadata)
    metadata.update(
        {
            "bulk_operation": True,
            "bulk_kind": request.operation,
            "bulk_count": len(request.item_ids),
            "updated_count": updated_count,
        }
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action=request.operation,
        item_id=item_id,
        before=planned_update.before_snapshot,
        after=after_snapshot,
        metadata=metadata,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return item_id


def _write_pending_bulk_audit_events(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    request: _BulkMutationRequest,
    pending_events: list[_PendingBulkAuditEvent],
    updated_count: int,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> None:
    for pending_event in pending_events:
        metadata = dict(pending_event.metadata)
        metadata.update(
            {
                "bulk_operation": True,
                "bulk_kind": request.operation,
                "bulk_count": len(request.item_ids),
                "updated_count": updated_count,
            }
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action=request.operation,
            item_id=pending_event.item_id,
            before=pending_event.before,
            after=pending_event.after,
            metadata=metadata,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )


def _apply_bulk_location_updates(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_rows: list[sqlite3.Row],
    request: _BulkMutationRequest,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> list[int]:
    normalized_location = str(request.location or "")
    updated_item_ids: list[int] = []
    pending_events: list[_PendingBulkAuditEvent] = []

    for row in item_rows:
        item_id = int(row["item_id"])
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if normalized_location == str(item["location"]):
            continue

        collision = find_inventory_item_collision(
            connection,
            inventory_id=int(item["inventory_id"]),
            scryfall_id=str(item["scryfall_id"]),
            condition_code=str(item["condition_code"]),
            finish=str(item["finish"]),
            language_code=str(item["language_code"]),
            location=normalized_location,
            exclude_item_id=item_id,
        )
        if collision is not None:
            if not request.merge:
                raise _set_location_collision_error()
            target_before_snapshot = inventory_item_result_from_row(collision)
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                acquisition_preference=request.keep_acquisition,
            )
            target_item_id = int(result["item_id"])
            target_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=target_item_id,
            )
            updated_item_ids.append(item_id)
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=item_id,
                    before=before_snapshot,
                    after=None,
                    metadata={
                        "merged": True,
                        "target_item_id": target_item_id,
                        "new_location": text_or_none(normalized_location),
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=target_item_id,
                    before=target_before_snapshot,
                    after=target_after_snapshot,
                    metadata={
                        "merged": True,
                        "source_item_id": item_id,
                        "new_location": text_or_none(normalized_location),
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            continue

        try:
            connection.execute(
                """
                UPDATE inventory_items
                SET location = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_location, item_id),
            )
        except sqlite3.IntegrityError as exc:
            if not request.merge:
                raise _set_location_collision_error() from exc
            collision = find_inventory_item_collision(
                connection,
                inventory_id=int(item["inventory_id"]),
                scryfall_id=str(item["scryfall_id"]),
                condition_code=str(item["condition_code"]),
                finish=str(item["finish"]),
                language_code=str(item["language_code"]),
                location=normalized_location,
                exclude_item_id=item_id,
            )
            if collision is None:
                raise _set_location_concurrent_merge_error() from exc
            target_before_snapshot = inventory_item_result_from_row(collision)
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                acquisition_preference=request.keep_acquisition,
            )
            target_item_id = int(result["item_id"])
            target_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=target_item_id,
            )
            updated_item_ids.append(item_id)
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=item_id,
                    before=before_snapshot,
                    after=None,
                    metadata={
                        "merged": True,
                        "target_item_id": target_item_id,
                        "new_location": text_or_none(normalized_location),
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=target_item_id,
                    before=target_before_snapshot,
                    after=target_after_snapshot,
                    metadata={
                        "merged": True,
                        "source_item_id": item_id,
                        "new_location": text_or_none(normalized_location),
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            continue

        after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
        )
        updated_item_ids.append(item_id)
        pending_events.append(
            _PendingBulkAuditEvent(
                item_id=item_id,
                before=before_snapshot,
                after=after_snapshot,
                metadata={
                    "merged": False,
                    "old_location": text_or_none(item["location"]),
                    "new_location": text_or_none(normalized_location),
                },
            )
        )

    _write_pending_bulk_audit_events(
        connection,
        inventory_slug=inventory_slug,
        request=request,
        pending_events=pending_events,
        updated_count=len(updated_item_ids),
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return updated_item_ids


def _apply_bulk_condition_updates(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_rows: list[sqlite3.Row],
    request: _BulkMutationRequest,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> list[int]:
    normalized_condition = str(request.condition_code)
    updated_item_ids: list[int] = []
    pending_events: list[_PendingBulkAuditEvent] = []

    for row in item_rows:
        item_id = int(row["item_id"])
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if normalized_condition == str(item["condition_code"]):
            continue

        collision = find_inventory_item_collision(
            connection,
            inventory_id=int(item["inventory_id"]),
            scryfall_id=str(item["scryfall_id"]),
            condition_code=normalized_condition,
            finish=str(item["finish"]),
            language_code=str(item["language_code"]),
            location=str(item["location"]),
            exclude_item_id=item_id,
        )
        if collision is not None:
            if not request.merge:
                raise _set_condition_collision_error()
            target_before_snapshot = inventory_item_result_from_row(collision)
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                acquisition_preference=request.keep_acquisition,
            )
            target_item_id = int(result["item_id"])
            target_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=target_item_id,
            )
            updated_item_ids.append(item_id)
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=item_id,
                    before=before_snapshot,
                    after=None,
                    metadata={
                        "merged": True,
                        "target_item_id": target_item_id,
                        "new_condition_code": normalized_condition,
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=target_item_id,
                    before=target_before_snapshot,
                    after=target_after_snapshot,
                    metadata={
                        "merged": True,
                        "source_item_id": item_id,
                        "new_condition_code": normalized_condition,
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            continue

        try:
            connection.execute(
                """
                UPDATE inventory_items
                SET condition_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_condition, item_id),
            )
        except sqlite3.IntegrityError as exc:
            if not request.merge:
                raise _set_condition_collision_error() from exc
            collision = find_inventory_item_collision(
                connection,
                inventory_id=int(item["inventory_id"]),
                scryfall_id=str(item["scryfall_id"]),
                condition_code=normalized_condition,
                finish=str(item["finish"]),
                language_code=str(item["language_code"]),
                location=str(item["location"]),
                exclude_item_id=item_id,
            )
            if collision is None:
                raise _set_condition_concurrent_merge_error() from exc
            target_before_snapshot = inventory_item_result_from_row(collision)
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                acquisition_preference=request.keep_acquisition,
            )
            target_item_id = int(result["item_id"])
            target_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=target_item_id,
            )
            updated_item_ids.append(item_id)
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=item_id,
                    before=before_snapshot,
                    after=None,
                    metadata={
                        "merged": True,
                        "target_item_id": target_item_id,
                        "new_condition_code": normalized_condition,
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            pending_events.append(
                _PendingBulkAuditEvent(
                    item_id=target_item_id,
                    before=target_before_snapshot,
                    after=target_after_snapshot,
                    metadata={
                        "merged": True,
                        "source_item_id": item_id,
                        "new_condition_code": normalized_condition,
                        "keep_acquisition": request.keep_acquisition,
                    },
                )
            )
            continue

        after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
        )
        updated_item_ids.append(item_id)
        pending_events.append(
            _PendingBulkAuditEvent(
                item_id=item_id,
                before=before_snapshot,
                after=after_snapshot,
                metadata={
                    "merged": False,
                    "old_condition_code": str(item["condition_code"]),
                    "new_condition_code": normalized_condition,
                },
            )
        )

    _write_pending_bulk_audit_events(
        connection,
        inventory_slug=inventory_slug,
        request=request,
        pending_events=pending_events,
        updated_count=len(updated_item_ids),
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return updated_item_ids


def _complete_location_merge(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    normalized_location: str,
    keep_acquisition: str | None,
    before_snapshot: dict[str, Any],
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> SetLocationResult:
    result = merge_inventory_item_rows(
        connection,
        inventory_slug=inventory_slug,
        source_item=source_item,
        target_item=target_item,
        acquisition_preference=keep_acquisition,
    )
    result["old_location"] = source_item["location"]
    result["location"] = normalized_location
    after_snapshot = load_inventory_item_snapshot(
        connection,
        inventory_slug=inventory_slug,
        item_id=int(result["item_id"]),
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_location",
        item_id=int(source_item["item_id"]),
        before=before_snapshot,
        after=None,
        metadata={
            "merged": True,
            "target_item_id": int(result["item_id"]),
            "new_location": text_or_none(normalized_location),
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_location",
        item_id=int(result["item_id"]),
        before=inventory_item_result_from_row(target_item),
        after=after_snapshot,
        metadata={
            "merged": True,
            "source_item_id": int(source_item["item_id"]),
            "new_location": text_or_none(normalized_location),
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    connection.commit()
    return SetLocationResult(
        **inventory_item_response_kwargs(result),
        operation="set_location",
        old_location=text_or_none(source_item["location"]),
        merged=True,
        merged_source_item_id=int(result["merged_source_item_id"]),
    )


def _complete_condition_merge(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    normalized_condition: str,
    keep_acquisition: str | None,
    before_snapshot: dict[str, Any],
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> SetConditionResult:
    result = merge_inventory_item_rows(
        connection,
        inventory_slug=inventory_slug,
        source_item=source_item,
        target_item=target_item,
        acquisition_preference=keep_acquisition,
    )
    result["old_condition_code"] = source_item["condition_code"]
    result["condition_code"] = normalized_condition
    after_snapshot = load_inventory_item_snapshot(
        connection,
        inventory_slug=inventory_slug,
        item_id=int(result["item_id"]),
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_condition",
        item_id=int(source_item["item_id"]),
        before=before_snapshot,
        after=None,
        metadata={
            "merged": True,
            "target_item_id": int(result["item_id"]),
            "new_condition_code": normalized_condition,
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_condition",
        item_id=int(result["item_id"]),
        before=inventory_item_result_from_row(target_item),
        after=after_snapshot,
        metadata={
            "merged": True,
            "source_item_id": int(source_item["item_id"]),
            "new_condition_code": normalized_condition,
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    connection.commit()
    return SetConditionResult(
        **inventory_item_response_kwargs(result),
        operation="set_condition",
        old_condition_code=str(source_item["condition_code"]),
        merged=True,
        merged_source_item_id=int(result["merged_source_item_id"]),
    )


def add_card_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    inventory_display_name: str | None = None,
    scryfall_id: str | None,
    oracle_id: str | None = None,
    tcgplayer_product_id: str | None = None,
    name: str | None,
    set_code: str | None,
    set_name: str | None = None,
    collector_number: str | None,
    lang: str | None,
    quantity: int,
    condition_code: str,
    finish: str,
    language_code: str | None,
    location: str,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None = None,
    resolved_card: sqlite3.Row | None = None,
    inventory_cache: dict[str, sqlite3.Row] | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> AddCardResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if quantity <= 0:
        raise ValidationError("--quantity must be a positive integer.")

    normalized_condition = normalize_condition_code(condition_code)
    normalized_finish = normalize_finish(finish)
    explicit_language = text_or_none(language_code)
    normalized_location = text_or_none(location) or ""
    normalized_acquisition_price = coerce_decimal(acquisition_price)
    normalized_acquisition_currency = normalize_currency_code(acquisition_currency)
    normalized_notes = text_or_none(notes)
    if normalized_acquisition_price is None and normalized_acquisition_currency is not None:
        raise ValidationError(
            "Cannot store an acquisition currency without an acquisition price. "
            "Use --acquisition-price too, or omit --acquisition-currency."
        )
    if normalized_acquisition_price is not None and normalized_acquisition_price < 0:
        raise ValidationError("--acquisition-price must be zero or greater.")
    if inventory_cache is None:
        inventory_cache = {}

    inventory = get_or_create_inventory_row(
        connection,
        inventory_slug,
        display_name=inventory_display_name,
        inventory_cache=inventory_cache,
        auto_create=inventory_display_name is not None,
    )

    card = resolved_card
    if card is None:
        card = resolve_card_row(
            connection,
            scryfall_id=scryfall_id,
            oracle_id=oracle_id,
            tcgplayer_product_id=normalize_external_id(tcgplayer_product_id),
            name=name,
            set_code=set_code,
            set_name=set_name,
            collector_number=collector_number,
            lang=lang,
            finish=normalized_finish,
        )
    validate_supported_finish(card["finishes_json"], normalized_finish)
    resolved_language = normalize_language_code(card["lang"])
    if explicit_language is None:
        normalized_language = resolved_language
    else:
        normalized_language = normalize_language_code(explicit_language)
        if normalized_language != resolved_language:
            raise ValidationError(
                "language_code must match the resolved printing language. "
                f"Printing language: {resolved_language}; requested language_code: {normalized_language}."
            )

    new_tags = parse_tags(tags)
    # Re-adding the same logical row should accumulate tags instead of replacing
    # previously attached metadata from earlier imports or manual edits.
    existing_row = connection.execute(
        """
        SELECT
            id,
            quantity,
            tags_json,
            acquisition_price,
            acquisition_currency,
            notes
        FROM inventory_items
        WHERE inventory_id = ?
          AND scryfall_id = ?
          AND condition_code = ?
          AND finish = ?
          AND language_code = ?
          AND location = ?
        """,
        (
            inventory["id"],
            card["scryfall_id"],
            normalized_condition,
            normalized_finish,
            normalized_language,
            normalized_location,
        ),
    ).fetchone()
    merged_tags = merge_tags(
        load_tags_json(existing_row["tags_json"]) if existing_row is not None else [],
        new_tags,
    )

    # The unique identity for an inventory row is printing plus
    # condition/finish/language/location. Matching rows roll quantity forward.
    if existing_row is not None:
        before_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=int(existing_row["id"]),
        )
        ensure_add_card_metadata_compatible(
            existing_row,
            incoming_notes=normalized_notes,
            incoming_acquisition_price=normalized_acquisition_price,
            incoming_acquisition_currency=normalized_acquisition_currency,
        )

        updated_quantity = int(existing_row["quantity"]) + quantity
        if before_write is not None:
            before_write()
        connection.execute(
            """
            UPDATE inventory_items
            SET quantity = ?, tags_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                updated_quantity,
                tags_to_json(merged_tags),
                existing_row["id"],
            ),
        )
        item_id = int(existing_row["id"])
        item_quantity = updated_quantity
        after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
        )
        result_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="add_card",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={"mode": "increment"},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
    else:
        if before_write is not None:
            before_write()
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
                    tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id, quantity
                """,
                (
                    inventory["id"],
                    card["scryfall_id"],
                    quantity,
                    normalized_condition,
                    normalized_finish,
                    normalized_language,
                    normalized_location,
                    normalized_acquisition_price,
                    normalized_acquisition_currency,
                    normalized_notes,
                    tags_to_json(merged_tags),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _add_card_concurrent_collision_error() from exc
        item_row = cursor.fetchone()
        item_id = int(item_row["id"])
        item_quantity = int(item_row["quantity"])
        after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
        )
        result_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="add_card",
            item_id=item_id,
            before=None,
            after=after_snapshot,
            metadata={"mode": "create"},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
    return _build_add_card_result(inventory_item_result_from_row(result_row))


def add_card(
    db_path: str | Path,
    *,
    inventory_slug: str,
    inventory_display_name: str | None = None,
    scryfall_id: str | None,
    oracle_id: str | None = None,
    tcgplayer_product_id: str | None = None,
    name: str | None,
    set_code: str | None,
    set_name: str | None = None,
    collector_number: str | None,
    lang: str | None,
    quantity: int,
    condition_code: str,
    finish: str,
    language_code: str | None,
    location: str,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> AddCardResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        result = add_card_with_connection(
            connection,
            inventory_slug=inventory_slug,
            inventory_display_name=inventory_display_name,
            scryfall_id=scryfall_id,
            oracle_id=oracle_id,
            tcgplayer_product_id=tcgplayer_product_id,
            name=name,
            set_code=set_code,
            set_name=set_name,
            collector_number=collector_number,
            lang=lang,
            quantity=quantity,
            condition_code=condition_code,
            finish=finish,
            language_code=language_code,
            location=location,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            notes=notes,
            tags=tags,
            before_write=before_write,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()
    return result


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
    before_write: Callable[[], Any] | None = None,
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


def set_location(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    location: str | None,
    merge: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetLocationResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_location = text_or_none(location) or ""
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if normalized_location == item["location"]:
            return SetLocationResult(
                **inventory_item_response_kwargs(before_snapshot),
                operation="set_location",
                old_location=text_or_none(item["location"]),
                merged=False,
            )

        collision = find_inventory_item_collision(
            connection,
            inventory_id=item["inventory_id"],
            scryfall_id=item["scryfall_id"],
            condition_code=item["condition_code"],
            finish=item["finish"],
            language_code=item["language_code"],
            location=normalized_location,
            exclude_item_id=item_id,
        )
        if collision is not None:
            # Changing an identity field can collapse two rows into one logical
            # bucket, so require an explicit merge opt-in before combining them.
            if not merge:
                raise _set_location_collision_error()
            if before_write is not None:
                before_write()
            return _complete_location_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_location=normalized_location,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )

        if before_write is not None:
            before_write()
        try:
            connection.execute(
                """
                UPDATE inventory_items
                SET location = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_location, item_id),
            )
        except sqlite3.IntegrityError as exc:
            if not merge:
                raise _set_location_collision_error() from exc
            collision = find_inventory_item_collision(
                connection,
                inventory_id=item["inventory_id"],
                scryfall_id=item["scryfall_id"],
                condition_code=item["condition_code"],
                finish=item["finish"],
                language_code=item["language_code"],
                location=normalized_location,
                exclude_item_id=item_id,
            )
            if collision is None:
                raise _set_location_concurrent_merge_error() from exc
            return _complete_location_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_location=normalized_location,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_location",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={
                "merged": False,
                "old_location": text_or_none(item["location"]),
                "new_location": text_or_none(normalized_location),
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetLocationResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_location",
        old_location=text_or_none(item["location"]),
        merged=False,
    )


def set_condition(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    condition_code: str,
    merge: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetConditionResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_condition = normalize_condition_code(condition_code)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if normalized_condition == item["condition_code"]:
            return SetConditionResult(
                **inventory_item_response_kwargs(before_snapshot),
                operation="set_condition",
                old_condition_code=str(item["condition_code"]),
                merged=False,
            )

        collision = find_inventory_item_collision(
            connection,
            inventory_id=item["inventory_id"],
            scryfall_id=item["scryfall_id"],
            condition_code=normalized_condition,
            finish=item["finish"],
            language_code=item["language_code"],
            location=item["location"],
            exclude_item_id=item_id,
        )
        if collision is not None:
            # Condition changes can trigger the same row-collision behavior as
            # location edits, so the merge path is shared here too.
            if not merge:
                raise _set_condition_collision_error()
            if before_write is not None:
                before_write()
            return _complete_condition_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_condition=normalized_condition,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )

        if before_write is not None:
            before_write()
        try:
            connection.execute(
                """
                UPDATE inventory_items
                SET condition_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_condition, item_id),
            )
        except sqlite3.IntegrityError as exc:
            if not merge:
                raise _set_condition_collision_error() from exc
            collision = find_inventory_item_collision(
                connection,
                inventory_id=item["inventory_id"],
                scryfall_id=item["scryfall_id"],
                condition_code=normalized_condition,
                finish=item["finish"],
                language_code=item["language_code"],
                location=item["location"],
                exclude_item_id=item_id,
            )
            if collision is None:
                raise _set_condition_concurrent_merge_error() from exc
            return _complete_condition_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_condition=normalized_condition,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_condition",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={
                "merged": False,
                "old_condition_code": item["condition_code"],
                "new_condition_code": normalized_condition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetConditionResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_condition",
        old_condition_code=str(item["condition_code"]),
        merged=False,
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
    before_write: Callable[[], Any] | None = None,
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

        target_condition = normalize_condition_code(condition_code) if condition_code is not None else source_item["condition_code"]
        target_finish = normalize_finish(finish) if finish is not None else source_item["finish"]
        target_language = normalize_language_code(language_code) if language_code is not None else source_item["language_code"]
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
            # Validate any acquisition conflict before touching quantities so a
            # failed merge request leaves both rows unchanged.
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
            # Splitting into an existing compatible row should merge into that
            # destination instead of manufacturing a third duplicate row.
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
                        tags_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def bulk_mutate_inventory_items(
    db_path: str | Path,
    *,
    inventory_slug: str,
    operation: str,
    item_ids: list[int],
    tags: list[str] | None,
    quantity: int | None = None,
    notes: str | None = None,
    clear_notes: bool = False,
    acquisition_price: Decimal | None = None,
    acquisition_currency: str | None = None,
    clear_acquisition: bool = False,
    finish: str | None = None,
    location: str | None = None,
    clear_location: bool = False,
    condition_code: str | None = None,
    merge: bool = False,
    keep_acquisition: str | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> BulkInventoryItemMutationResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_request = _normalize_bulk_mutation_request(
        operation=operation,
        item_ids=item_ids,
        tags=tags,
        quantity=quantity,
        notes=notes,
        clear_notes=clear_notes,
        acquisition_price=acquisition_price,
        acquisition_currency=acquisition_currency,
        clear_acquisition=clear_acquisition,
        finish=finish,
        location=location,
        clear_location=clear_location,
        condition_code=condition_code,
        merge=merge,
        keep_acquisition=keep_acquisition,
    )
    db_file = _prepared_db_path(db_path)

    with connect(db_file) as connection:
        item_rows = _load_bulk_inventory_item_rows(
            connection,
            inventory_slug=inventory_slug,
            item_ids=normalized_request.item_ids,
        )
        if normalized_request.operation in _BULK_LOCATION_OPERATIONS:
            updated_item_ids = _apply_bulk_location_updates(
                connection,
                inventory_slug=inventory_slug,
                item_rows=item_rows,
                request=normalized_request,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )
        elif normalized_request.operation in _BULK_CONDITION_OPERATIONS:
            updated_item_ids = _apply_bulk_condition_updates(
                connection,
                inventory_slug=inventory_slug,
                item_rows=item_rows,
                request=normalized_request,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )
        else:
            planned_updates = _plan_bulk_item_updates(
                connection=connection,
                item_rows=item_rows,
                request=normalized_request,
            )
            updated_item_ids = []
            updated_count = len(planned_updates)
            for planned_update in planned_updates:
                updated_item_ids.append(
                    _apply_bulk_item_update(
                        connection,
                        inventory_slug=inventory_slug,
                        request=normalized_request,
                        planned_update=planned_update,
                        updated_count=updated_count,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        request_id=request_id,
                    )
                )

        connection.commit()

    return BulkInventoryItemMutationResult(
        inventory=inventory_slug,
        operation=normalized_request.operation,
        requested_item_ids=normalized_request.item_ids,
        updated_item_ids=updated_item_ids,
        updated_count=len(updated_item_ids),
    )


def merge_rows(
    db_path: str | Path,
    *,
    inventory_slug: str,
    source_item_id: int,
    target_item_id: int,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
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
    before_write: Callable[[], Any] | None = None,
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
