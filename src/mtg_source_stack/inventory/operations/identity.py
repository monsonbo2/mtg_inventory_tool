"""Identity-changing inventory row mutations."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from ...db.connection import connect
from ...db.schema import require_current_schema
from ...errors import ConflictError, ValidationError
from ..audit import load_inventory_item_snapshot, write_inventory_audit_event
from ..catalog import resolve_card_row
from ..normalize import (
    CANONICAL_FINISHES,
    normalize_condition_code,
    normalize_finish,
    normalize_inventory_slug,
    normalize_language_code,
    normalized_catalog_finish_list,
    text_or_none,
    validate_supported_finish,
)
from ..query_inventory import (
    find_inventory_item_collision,
    get_inventory_item_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)
from ..response_models import (
    SetConditionResult,
    SetLocationResult,
    SetPrintingResult,
    inventory_item_response_kwargs,
)

__all__ = ["set_condition", "set_location", "set_printing", "set_printing_with_connection"]


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


def _set_printing_collision_error() -> ConflictError:
    return ConflictError(
        "Changing printing would collide with an existing inventory row. "
        "Re-run with --merge to combine the rows, or resolve the duplicate row first."
    )


def _set_printing_concurrent_merge_error() -> ConflictError:
    return ConflictError(
        "Changing printing collided with another concurrent write while merging. Retry the request."
    )


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


def _mutable_row_copy(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _resolve_printing_change_finish(
    *,
    target_card: sqlite3.Row,
    current_finish: str,
    requested_finish: str | None,
) -> tuple[str, bool]:
    if requested_finish is not None:
        normalized_finish = normalize_finish(requested_finish)
        validate_supported_finish(target_card["finishes_json"], normalized_finish)
        return normalized_finish, False

    available_finishes = normalized_catalog_finish_list(target_card["finishes_json"])
    if current_finish in available_finishes:
        return current_finish, False
    for candidate_finish in CANONICAL_FINISHES:
        if candidate_finish in available_finishes:
            return candidate_finish, True
    raise ValidationError(
        f"Target printing '{target_card['scryfall_id']}' does not expose any supported finishes."
    )


def _complete_printing_merge(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    before_snapshot: dict[str, Any],
    target_scryfall_id: str,
    target_finish: str,
    target_language_code: str,
    keep_acquisition: str | None,
    auto_selected_finish: bool,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> SetPrintingResult:
    merge_source_item = _mutable_row_copy(source_item)
    merge_source_item["printing_selection_mode"] = "explicit"
    result = merge_inventory_item_rows(
        connection,
        inventory_slug=inventory_slug,
        source_item=merge_source_item,
        target_item=target_item,
        acquisition_preference=keep_acquisition,
    )
    after_snapshot = load_inventory_item_snapshot(
        connection,
        inventory_slug=inventory_slug,
        item_id=int(result["item_id"]),
    )
    metadata = {
        "merged": True,
        "new_scryfall_id": target_scryfall_id,
        "new_finish": target_finish,
        "new_language_code": target_language_code,
        "keep_acquisition": keep_acquisition,
        "auto_selected_finish": auto_selected_finish,
    }
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_printing",
        item_id=int(source_item["item_id"]),
        before=before_snapshot,
        after=None,
        metadata={
            **metadata,
            "target_item_id": int(result["item_id"]),
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_printing",
        item_id=int(result["item_id"]),
        before=inventory_item_result_from_row(target_item),
        after=after_snapshot,
        metadata={
            **metadata,
            "source_item_id": int(source_item["item_id"]),
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    connection.commit()
    return SetPrintingResult(
        **inventory_item_response_kwargs(result),
        operation="set_printing",
        old_scryfall_id=str(source_item["scryfall_id"]),
        old_finish=str(source_item["finish"]),
        old_language_code=str(source_item["language_code"]),
        merged=True,
        merged_source_item_id=int(result["merged_source_item_id"]),
    )


def set_printing_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_id: int,
    scryfall_id: str,
    finish: str | None = None,
    merge: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetPrintingResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    target_scryfall_id = text_or_none(scryfall_id)
    if target_scryfall_id is None:
        raise ValidationError("scryfall_id is required for set_printing.")
    if keep_acquisition not in (None, "source", "target"):
        raise ValidationError("keep_acquisition must be one of: source, target.")
    if not merge and keep_acquisition is not None:
        raise ValidationError("keep_acquisition only applies when merge is true for set_printing.")

    item = get_inventory_item_row(connection, inventory_slug, item_id)
    before_snapshot = inventory_item_result_from_row(item)
    target_card = resolve_card_row(
        connection,
        scryfall_id=target_scryfall_id,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        set_name=None,
        collector_number=None,
        lang=None,
        finish=None,
    )
    if str(target_card["oracle_id"]) != str(item["oracle_id"]):
        raise ValidationError("Target printing must belong to the same oracle card as the current inventory row.")

    target_finish, auto_selected_finish = _resolve_printing_change_finish(
        target_card=target_card,
        current_finish=str(item["finish"]),
        requested_finish=finish,
    )
    target_language_code = normalize_language_code(target_card["lang"])
    if target_scryfall_id == str(item["scryfall_id"]) and (
        target_finish != str(item["finish"])
        or target_language_code != str(item["language_code"])
    ):
        raise ValidationError(
            "set_printing only supports confirming the current printing when finish and language stay unchanged. "
            "Use the generic item PATCH route for finish changes."
        )
    mode_only_update = (
        target_scryfall_id == str(item["scryfall_id"])
        and target_finish == str(item["finish"])
        and target_language_code == str(item["language_code"])
    )
    if mode_only_update and str(item["printing_selection_mode"]) == "explicit":
        return SetPrintingResult(
            **inventory_item_response_kwargs(before_snapshot),
            operation="set_printing",
            old_scryfall_id=str(item["scryfall_id"]),
            old_finish=str(item["finish"]),
            old_language_code=str(item["language_code"]),
            merged=False,
        )

    collision = find_inventory_item_collision(
        connection,
        inventory_id=int(item["inventory_id"]),
        scryfall_id=target_scryfall_id,
        condition_code=str(item["condition_code"]),
        finish=target_finish,
        language_code=target_language_code,
        location=str(item["location"]),
        exclude_item_id=item_id,
    )
    if collision is not None:
        if not merge:
            raise _set_printing_collision_error()
        if before_write is not None:
            before_write()
        return _complete_printing_merge(
            connection,
            inventory_slug=inventory_slug,
            source_item=item,
            target_item=collision,
            before_snapshot=before_snapshot,
            target_scryfall_id=target_scryfall_id,
            target_finish=target_finish,
            target_language_code=target_language_code,
            keep_acquisition=keep_acquisition,
            auto_selected_finish=auto_selected_finish,
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
            SET
                scryfall_id = ?,
                finish = ?,
                language_code = ?,
                printing_selection_mode = 'explicit',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_scryfall_id, target_finish, target_language_code, item_id),
        )
    except sqlite3.IntegrityError as exc:
        if not merge:
            raise _set_printing_collision_error() from exc
        collision = find_inventory_item_collision(
            connection,
            inventory_id=int(item["inventory_id"]),
            scryfall_id=target_scryfall_id,
            condition_code=str(item["condition_code"]),
            finish=target_finish,
            language_code=target_language_code,
            location=str(item["location"]),
            exclude_item_id=item_id,
        )
        if collision is None:
            raise _set_printing_concurrent_merge_error() from exc
        return _complete_printing_merge(
            connection,
            inventory_slug=inventory_slug,
            source_item=item,
            target_item=collision,
            before_snapshot=before_snapshot,
            target_scryfall_id=target_scryfall_id,
            target_finish=target_finish,
            target_language_code=target_language_code,
            keep_acquisition=keep_acquisition,
            auto_selected_finish=auto_selected_finish,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )

    after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
    after_row = get_inventory_item_row(connection, inventory_slug, item_id)
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_printing",
        item_id=item_id,
        before=before_snapshot,
        after=after_snapshot,
        metadata={
            "merged": False,
            "old_scryfall_id": str(item["scryfall_id"]),
            "new_scryfall_id": target_scryfall_id,
            "old_finish": str(item["finish"]),
            "new_finish": target_finish,
            "old_language_code": str(item["language_code"]),
            "new_language_code": target_language_code,
            "auto_selected_finish": auto_selected_finish,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return SetPrintingResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_printing",
        old_scryfall_id=str(item["scryfall_id"]),
        old_finish=str(item["finish"]),
        old_language_code=str(item["language_code"]),
        merged=False,
    )


def set_printing(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    scryfall_id: str,
    finish: str | None = None,
    merge: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetPrintingResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        result = set_printing_with_connection(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
            scryfall_id=scryfall_id,
            finish=finish,
            merge=merge,
            keep_acquisition=keep_acquisition,
            before_write=before_write,
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
