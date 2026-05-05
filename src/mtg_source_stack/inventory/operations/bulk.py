"""Bulk inventory mutation engine."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping

from ...db.connection import connect
from ...db.schema import require_current_schema
from ...errors import ConflictError, NotFoundError, ValidationError
from ..audit import load_inventory_item_snapshot, write_inventory_audit_event
from ..money import coerce_decimal
from ..normalize import (
    merge_tags,
    normalize_condition_code,
    normalize_currency_code,
    normalize_finish,
    normalize_inventory_slug,
    normalize_language_code,
    normalize_tags,
    parse_tag_filters,
    tags_to_json,
    text_or_none,
    validate_supported_finish,
)
from ..query_inventory import (
    add_owned_filters,
    find_inventory_item_collision,
    get_inventory_item_row,
    get_inventory_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)
from ..response_models import BulkInventoryItemMutationResult

__all__ = ["bulk_mutate_inventory_items"]


def _prepared_db_path(db_path: str | Path) -> Path:
    return require_current_schema(db_path)


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


def _set_finish_collision_error() -> ConflictError:
    return ConflictError(
        "Changing finish would collide with an existing inventory row. Resolve the duplicate row first."
    )


_BULK_TAG_OPERATIONS = frozenset({"add_tags", "clear_tags", "remove_tags", "set_tags"})
_BULK_QUANTITY_OPERATIONS = frozenset({"set_quantity"})
_BULK_NOTES_OPERATIONS = frozenset({"set_notes"})
_BULK_ACQUISITION_OPERATIONS = frozenset({"set_acquisition"})
_BULK_FINISH_OPERATIONS = frozenset({"set_finish"})
_BULK_LOCATION_OPERATIONS = frozenset({"set_location"})
_BULK_CONDITION_OPERATIONS = frozenset({"set_condition"})
_BULK_SELECTION_KINDS = frozenset({"items", "filtered", "all_items"})
_MAX_BULK_ITEM_IDS = 1000
_MAX_BULK_UPDATED_ITEM_IDS = 1000
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
class _BulkSelectionRequest:
    kind: str
    item_ids: list[int] | None = None
    query: str | None = None
    set_code: str | None = None
    rarity: str | None = None
    finish: str | None = None
    condition_code: str | None = None
    language_code: str | None = None
    location: str | None = None
    tags: list[str] | None = None


@dataclass(frozen=True, slots=True)
class _BulkMutationRequest:
    operation: str
    selection: _BulkSelectionRequest
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


def _bulk_selection_error() -> ValidationError:
    supported_kinds = ", ".join(sorted(_BULK_SELECTION_KINDS))
    return ValidationError(f"selection.kind must be one of: {supported_kinds}.")


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


def _normalize_bulk_item_ids(item_ids: list[int] | None) -> list[int]:
    if not item_ids:
        raise ValidationError("selection.item_ids must include at least one item id.")
    if len(set(item_ids)) != len(item_ids):
        raise ValidationError("selection.item_ids must not contain duplicates.")
    if len(item_ids) > _MAX_BULK_ITEM_IDS:
        raise ValidationError(f"selection.item_ids must not contain more than {_MAX_BULK_ITEM_IDS} ids.")
    return list(item_ids)


def _normalize_bulk_selection_request(
    *,
    selection: Mapping[str, Any] | None,
) -> _BulkSelectionRequest:
    if selection is None:
        raise ValidationError("selection is required for bulk item mutations.")
    selection_kind = text_or_none(selection.get("kind"))
    if selection_kind not in _BULK_SELECTION_KINDS:
        raise _bulk_selection_error()

    if selection_kind == "items":
        unexpected_fields = sorted(key for key in selection if key not in {"kind", "item_ids"})
        if unexpected_fields:
            fields_text = ", ".join(unexpected_fields)
            raise ValidationError(f"{fields_text} are not valid for selection.kind='items'.")
        return _BulkSelectionRequest(
            kind="items",
            item_ids=_normalize_bulk_item_ids(selection.get("item_ids")),
        )

    if selection_kind == "all_items":
        unexpected_fields = sorted(key for key, value in selection.items() if key != "kind" and value is not None)
        if unexpected_fields:
            fields_text = ", ".join(unexpected_fields)
            raise ValidationError(f"{fields_text} are not valid for selection.kind='all_items'.")
        return _BulkSelectionRequest(kind="all_items")

    normalized_selection = _BulkSelectionRequest(
        kind="filtered",
        query=text_or_none(selection.get("query")),
        set_code=text_or_none(selection.get("set_code")),
        rarity=text_or_none(selection.get("rarity")),
        finish=normalize_finish(selection["finish"]) if selection.get("finish") is not None else None,
        condition_code=(
            normalize_condition_code(selection["condition_code"])
            if selection.get("condition_code") is not None
            else None
        ),
        language_code=(
            normalize_language_code(selection["language_code"])
            if selection.get("language_code") is not None
            else None
        ),
        location=text_or_none(selection.get("location")),
        tags=parse_tag_filters(selection.get("tags")),
    )
    if (
        normalized_selection.query is None
        and normalized_selection.set_code is None
        and normalized_selection.rarity is None
        and normalized_selection.finish is None
        and normalized_selection.condition_code is None
        and normalized_selection.language_code is None
        and normalized_selection.location is None
        and not normalized_selection.tags
    ):
        raise ValidationError("selection.kind='filtered' requires at least one effective filter.")
    unexpected_fields = sorted(
        key
        for key in selection
        if key
        not in {
            "kind",
            "query",
            "set_code",
            "rarity",
            "finish",
            "condition_code",
            "language_code",
            "location",
            "tags",
        }
    )
    if unexpected_fields:
        fields_text = ", ".join(unexpected_fields)
        raise ValidationError(f"{fields_text} are not valid for selection.kind='filtered'.")
    return normalized_selection


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
    selection: Mapping[str, Any] | None,
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
    normalized_selection = _normalize_bulk_selection_request(selection=selection)
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
        selection=normalized_selection,
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


def _load_bulk_inventory_item_rows_by_ids(
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
            c.oracle_id,
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
            COALESCE(ii.tags_json, '[]') AS tags_json,
            ii.printing_selection_mode
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


def _load_bulk_inventory_item_rows_for_selection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    selection: _BulkSelectionRequest,
) -> list[sqlite3.Row]:
    inventory = get_inventory_row(connection, inventory_slug)
    where_parts = ["ii.inventory_id = ?"]
    where_params: list[Any] = [inventory["id"]]
    if selection.kind == "filtered":
        add_owned_filters(
            where_parts,
            where_params,
            query=selection.query,
            set_code=selection.set_code,
            rarity=selection.rarity,
            finish=selection.finish,
            condition_code=selection.condition_code,
            language_code=selection.language_code,
            location=selection.location,
            tags=selection.tags,
        )
    return connection.execute(
        f"""
        SELECT
            ii.id AS item_id,
            ii.inventory_id,
            i.slug AS inventory,
            ii.scryfall_id,
            c.oracle_id,
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
            COALESCE(ii.tags_json, '[]') AS tags_json,
            ii.printing_selection_mode
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        WHERE {' AND '.join(where_parts)}
        ORDER BY ii.id ASC
        """,
        where_params,
    ).fetchall()


def _load_bulk_inventory_item_rows(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    selection: _BulkSelectionRequest,
) -> list[sqlite3.Row]:
    if selection.kind == "items":
        return _load_bulk_inventory_item_rows_by_ids(
            connection,
            inventory_slug=inventory_slug,
            item_ids=list(selection.item_ids or []),
        )
    return _load_bulk_inventory_item_rows_for_selection(
        connection,
        inventory_slug=inventory_slug,
        selection=selection,
    )


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
    del connection
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
    del connection
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
    del connection
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
    del connection
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


def _bounded_bulk_updated_item_ids(item_ids: list[int]) -> tuple[list[int], bool]:
    if len(item_ids) <= _MAX_BULK_UPDATED_ITEM_IDS:
        return list(item_ids), False
    return list(item_ids[:_MAX_BULK_UPDATED_ITEM_IDS]), True


def _bulk_audit_metadata(
    *,
    request: _BulkMutationRequest,
    matched_count: int,
    updated_count: int,
) -> dict[str, Any]:
    return {
        "bulk_operation": True,
        "bulk_kind": request.operation,
        "bulk_count": matched_count,
        "selection_kind": request.selection.kind,
        "updated_count": updated_count,
    }


def _apply_bulk_item_update(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    request: _BulkMutationRequest,
    planned_update: _BulkPlannedItemUpdate,
    matched_count: int,
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
    metadata.update(_bulk_audit_metadata(request=request, matched_count=matched_count, updated_count=updated_count))
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
    matched_count: int,
    updated_count: int,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> None:
    for pending_event in pending_events:
        metadata = dict(pending_event.metadata)
        metadata.update(_bulk_audit_metadata(request=request, matched_count=matched_count, updated_count=updated_count))
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
        matched_count=len(item_rows),
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
        matched_count=len(item_rows),
        updated_count=len(updated_item_ids),
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return updated_item_ids


def bulk_mutate_inventory_items(
    db_path: str | Path,
    *,
    inventory_slug: str,
    operation: str,
    selection: Mapping[str, Any] | None,
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
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> BulkInventoryItemMutationResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_request = _normalize_bulk_mutation_request(
        operation=operation,
        selection=selection,
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
            selection=normalized_request.selection,
        )
        matched_count = len(item_rows)
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
                        matched_count=matched_count,
                        updated_count=updated_count,
                        actor_type=actor_type,
                        actor_id=actor_id,
                        request_id=request_id,
                    )
                )

        connection.commit()

    bounded_updated_item_ids, updated_item_ids_truncated = _bounded_bulk_updated_item_ids(updated_item_ids)
    return BulkInventoryItemMutationResult(
        inventory=inventory_slug,
        operation=normalized_request.operation,
        selection_kind=normalized_request.selection.kind,
        matched_count=matched_count,
        unchanged_count=matched_count - len(updated_item_ids),
        updated_item_ids=bounded_updated_item_ids,
        updated_count=len(updated_item_ids),
        updated_item_ids_truncated=updated_item_ids_truncated,
    )
