"""Cross-inventory transfer planning and execution."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ConflictError, ValidationError
from .audit import load_inventory_item_snapshot, write_inventory_audit_event
from .inventories import create_inventory_with_connection
from .normalize import normalize_inventory_slug
from .policies import build_merged_inventory_item_update
from .query_inventory import (
    find_inventory_item_collision,
    get_inventory_item_row,
    get_inventory_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)
from .response_models import (
    InventoryDuplicateResult,
    InventoryTransferItemResult,
    InventoryTransferResult,
)


_TRANSFER_MODES = frozenset({"copy", "move"})
_TRANSFER_CONFLICT_POLICIES = frozenset({"fail", "merge"})
_MAX_TRANSFER_RESULT_ROWS = 100


@dataclass(frozen=True, slots=True)
class _TransferRequest:
    target_inventory_slug: str
    mode: str
    selection_kind: str
    item_ids: list[int] | None
    on_conflict: str
    keep_acquisition: str | None
    dry_run: bool


@dataclass(frozen=True, slots=True)
class _PlannedTransferItem:
    source_item_id: int
    source_row: sqlite3.Row
    source_snapshot: dict[str, Any]
    target_item_id: int | None
    status: str
    source_removed: bool
    target_before_snapshot: dict[str, Any] | None = None
    error: Exception | None = None


def _prepared_db_path(db_path: str | Path) -> Path:
    return require_current_schema(db_path)


def _normalize_transfer_item_ids(item_ids: list[int]) -> list[int]:
    if not item_ids:
        raise ValidationError("item_ids must include at least one item id.")
    if len(set(item_ids)) != len(item_ids):
        raise ValidationError("item_ids must not contain duplicates.")
    if len(item_ids) > 100:
        raise ValidationError("item_ids must not contain more than 100 ids.")
    return list(item_ids)


def _normalize_transfer_request(
    *,
    source_inventory_slug: str,
    target_inventory_slug: str,
    mode: str,
    item_ids: list[int] | None,
    all_items: bool,
    on_conflict: str,
    keep_acquisition: str | None,
    dry_run: bool,
) -> _TransferRequest:
    normalized_source = normalize_inventory_slug(source_inventory_slug)
    normalized_target = normalize_inventory_slug(target_inventory_slug)
    if normalized_target == normalized_source:
        raise ValidationError("target_inventory_slug must be different from the source inventory.")
    if mode not in _TRANSFER_MODES:
        accepted = ", ".join(sorted(_TRANSFER_MODES))
        raise ValidationError(f"mode must be one of: {accepted}.")
    if on_conflict not in _TRANSFER_CONFLICT_POLICIES:
        accepted = ", ".join(sorted(_TRANSFER_CONFLICT_POLICIES))
        raise ValidationError(f"on_conflict must be one of: {accepted}.")
    if keep_acquisition not in (None, "source", "target"):
        raise ValidationError("keep_acquisition must be one of: source, target.")
    if on_conflict != "merge" and keep_acquisition is not None:
        raise ValidationError("keep_acquisition only applies when on_conflict is merge.")
    if all_items and item_ids is not None:
        raise ValidationError("Use either item_ids or all_items=true, not both.")
    if not all_items and item_ids is None:
        raise ValidationError("Provide item_ids or set all_items=true.")
    return _TransferRequest(
        target_inventory_slug=normalized_target,
        mode=mode,
        selection_kind="all_items" if all_items else "items",
        item_ids=None if all_items else _normalize_transfer_item_ids(item_ids or []),
        on_conflict=on_conflict,
        keep_acquisition=keep_acquisition,
        dry_run=bool(dry_run),
    )


def _transfer_identity_conflict_error(*, source_item_id: int, target_inventory_slug: str) -> ConflictError:
    return ConflictError(
        f"Transferring item {source_item_id} would collide with an existing row in inventory "
        f"'{target_inventory_slug}'. Re-run with on_conflict=merge or resolve the duplicate row first."
    )


def _transfer_acquisition_conflict_error(*, source_item_id: int, target_inventory_slug: str) -> ConflictError:
    return ConflictError(
        f"Transferring item {source_item_id} into inventory '{target_inventory_slug}' would merge rows with "
        "different acquisition values. Re-run with keep_acquisition='target' or keep_acquisition='source'."
    )


def _transfer_concurrent_collision_error(*, source_item_id: int, target_inventory_slug: str) -> ConflictError:
    return ConflictError(
        f"Transferring item {source_item_id} collided with a concurrent write in inventory "
        f"'{target_inventory_slug}'. Retry the request."
    )


def _load_transfer_source_rows(
    connection: sqlite3.Connection,
    *,
    source_inventory_slug: str,
    item_ids: list[int] | None,
) -> list[sqlite3.Row]:
    if item_ids is None:
        inventory = get_inventory_row(connection, source_inventory_slug)
        return connection.execute(
            """
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
            ORDER BY ii.id
            """,
            (inventory["id"],),
        ).fetchall()
    return [get_inventory_item_row(connection, source_inventory_slug, item_id) for item_id in item_ids]


def _plan_transfer_item(
    connection: sqlite3.Connection,
    *,
    target_inventory_id: int,
    target_inventory_slug: str,
    request: _TransferRequest,
    source_row: sqlite3.Row,
) -> _PlannedTransferItem:
    source_item_id = int(source_row["item_id"])
    source_snapshot = inventory_item_result_from_row(source_row)
    collision = find_inventory_item_collision(
        connection,
        inventory_id=target_inventory_id,
        scryfall_id=str(source_row["scryfall_id"]),
        condition_code=str(source_row["condition_code"]),
        finish=str(source_row["finish"]),
        language_code=str(source_row["language_code"]),
        location=str(source_row["location"]),
        exclude_item_id=-1,
    )
    if collision is None:
        return _PlannedTransferItem(
            source_item_id=source_item_id,
            source_row=source_row,
            source_snapshot=source_snapshot,
            target_item_id=None,
            status=request.mode,
            source_removed=request.mode == "move",
        )

    target_item_id = int(collision["item_id"])
    target_before_snapshot = inventory_item_result_from_row(collision)
    if request.on_conflict == "fail":
        return _PlannedTransferItem(
            source_item_id=source_item_id,
            source_row=source_row,
            source_snapshot=source_snapshot,
            target_item_id=target_item_id,
            status="fail",
            source_removed=False,
            target_before_snapshot=target_before_snapshot,
            error=_transfer_identity_conflict_error(
                source_item_id=source_item_id,
                target_inventory_slug=target_inventory_slug,
            ),
        )

    try:
        build_merged_inventory_item_update(
            source_row,
            collision,
            acquisition_preference=request.keep_acquisition,
        )
    except ConflictError:
        return _PlannedTransferItem(
            source_item_id=source_item_id,
            source_row=source_row,
            source_snapshot=source_snapshot,
            target_item_id=target_item_id,
            status="fail",
            source_removed=False,
            target_before_snapshot=target_before_snapshot,
            error=_transfer_acquisition_conflict_error(
                source_item_id=source_item_id,
                target_inventory_slug=target_inventory_slug,
            ),
        )

    return _PlannedTransferItem(
        source_item_id=source_item_id,
        source_row=source_row,
        source_snapshot=source_snapshot,
        target_item_id=target_item_id,
        status="merge",
        source_removed=request.mode == "move",
        target_before_snapshot=target_before_snapshot,
    )


def _plan_transfer_items(
    connection: sqlite3.Connection,
    *,
    target_inventory_id: int,
    target_inventory_slug: str,
    request: _TransferRequest,
    source_rows: list[sqlite3.Row],
) -> list[_PlannedTransferItem]:
    return [
        _plan_transfer_item(
            connection,
            target_inventory_id=target_inventory_id,
            target_inventory_slug=target_inventory_slug,
            request=request,
            source_row=source_row,
        )
        for source_row in source_rows
    ]


def _dry_run_status_for(plan: _PlannedTransferItem) -> str:
    if plan.status == "copy":
        return "would_copy"
    if plan.status == "move":
        return "would_move"
    if plan.status == "merge":
        return "would_merge"
    return "would_fail"


def _status_for_counts(result_status: str) -> str:
    if result_status in {"would_copy", "copied"}:
        return "copied"
    if result_status in {"would_move", "moved"}:
        return "moved"
    if result_status in {"would_merge", "merged"}:
        return "merged"
    return "failed"


def _result_from_plan(plan: _PlannedTransferItem, *, dry_run: bool) -> InventoryTransferItemResult:
    status = _dry_run_status_for(plan) if dry_run else plan.status
    return InventoryTransferItemResult(
        source_item_id=plan.source_item_id,
        target_item_id=plan.target_item_id,
        status=status,
        source_removed=plan.source_removed if status != "would_fail" else False,
        message=str(plan.error) if plan.error is not None else None,
    )


def _insert_transferred_row(
    connection: sqlite3.Connection,
    *,
    target_inventory_id: int,
    source_row: sqlite3.Row,
) -> int:
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
            target_inventory_id,
            source_row["scryfall_id"],
            source_row["quantity"],
            source_row["condition_code"],
            source_row["finish"],
            source_row["language_code"],
            source_row["location"],
            source_row["acquisition_price"],
            source_row["acquisition_currency"],
            source_row["notes"],
            source_row["tags_json"],
            source_row["printing_selection_mode"],
        ),
    )
    inserted = cursor.fetchone()
    return int(inserted["id"])


def _write_transfer_audit_pair(
    connection: sqlite3.Connection,
    *,
    source_inventory_slug: str,
    target_inventory_slug: str,
    source_item_id: int,
    target_item_id: int,
    source_before: dict[str, Any],
    source_after: dict[str, Any] | None,
    target_before: dict[str, Any] | None,
    target_after: dict[str, Any],
    mode: str,
    status: str,
    merged: bool,
    keep_acquisition: str | None,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> None:
    common_metadata = {
        "transfer_operation": True,
        "mode": mode,
        "status": status,
        "merged": merged,
        "source_removed": source_after is None,
        "keep_acquisition": keep_acquisition,
    }
    write_inventory_audit_event(
        connection,
        inventory_slug=source_inventory_slug,
        action="transfer_items",
        item_id=source_item_id,
        before=source_before,
        after=source_after,
        metadata={
            **common_metadata,
            "role": "source",
            "target_inventory": target_inventory_slug,
            "target_item_id": target_item_id,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=target_inventory_slug,
        action="transfer_items",
        item_id=target_item_id,
        before=target_before,
        after=target_after,
        metadata={
            **common_metadata,
            "role": "target",
            "source_inventory": source_inventory_slug,
            "source_item_id": source_item_id,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )


def _execute_copy_or_move(
    connection: sqlite3.Connection,
    *,
    source_inventory_slug: str,
    target_inventory_slug: str,
    target_inventory_id: int,
    request: _TransferRequest,
    plan: _PlannedTransferItem,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> InventoryTransferItemResult:
    current_source = get_inventory_item_row(connection, source_inventory_slug, plan.source_item_id)
    source_before = inventory_item_result_from_row(current_source)
    try:
        target_item_id = _insert_transferred_row(
            connection,
            target_inventory_id=target_inventory_id,
            source_row=current_source,
        )
    except sqlite3.IntegrityError as exc:
        if request.on_conflict == "merge":
            collision = find_inventory_item_collision(
                connection,
                inventory_id=target_inventory_id,
                scryfall_id=str(current_source["scryfall_id"]),
                condition_code=str(current_source["condition_code"]),
                finish=str(current_source["finish"]),
                language_code=str(current_source["language_code"]),
                location=str(current_source["location"]),
                exclude_item_id=-1,
            )
            if collision is None:
                raise _transfer_concurrent_collision_error(
                    source_item_id=plan.source_item_id,
                    target_inventory_slug=target_inventory_slug,
                ) from exc
            merge_result = _execute_merge(
                connection,
                source_inventory_slug=source_inventory_slug,
                target_inventory_slug=target_inventory_slug,
                request=request,
                plan=_PlannedTransferItem(
                    source_item_id=plan.source_item_id,
                    source_row=current_source,
                    source_snapshot=source_before,
                    target_item_id=int(collision["item_id"]),
                    status="merge",
                    source_removed=request.mode == "move",
                    target_before_snapshot=inventory_item_result_from_row(collision),
                ),
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )
            return merge_result
        raise _transfer_concurrent_collision_error(
            source_item_id=plan.source_item_id,
            target_inventory_slug=target_inventory_slug,
        ) from exc

    target_after = load_inventory_item_snapshot(
        connection,
        inventory_slug=target_inventory_slug,
        item_id=target_item_id,
    )
    if request.mode == "move":
        connection.execute(
            """
            DELETE FROM inventory_items
            WHERE id = ?
            """,
            (plan.source_item_id,),
        )
        source_after = None
        result_status = "moved"
    else:
        source_after = source_before
        result_status = "copied"

    _write_transfer_audit_pair(
        connection,
        source_inventory_slug=source_inventory_slug,
        target_inventory_slug=target_inventory_slug,
        source_item_id=plan.source_item_id,
        target_item_id=target_item_id,
        source_before=source_before,
        source_after=source_after,
        target_before=None,
        target_after=target_after,
        mode=request.mode,
        status=result_status,
        merged=False,
        keep_acquisition=request.keep_acquisition,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return InventoryTransferItemResult(
        source_item_id=plan.source_item_id,
        target_item_id=target_item_id,
        status=result_status,
        source_removed=request.mode == "move",
        message=None,
    )


def _execute_merge(
    connection: sqlite3.Connection,
    *,
    source_inventory_slug: str,
    target_inventory_slug: str,
    request: _TransferRequest,
    plan: _PlannedTransferItem,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> InventoryTransferItemResult:
    current_source = get_inventory_item_row(connection, source_inventory_slug, plan.source_item_id)
    if plan.target_item_id is None:
        raise ValueError("Merge execution requires a target item id.")
    current_target = get_inventory_item_row(connection, target_inventory_slug, plan.target_item_id)
    source_before = inventory_item_result_from_row(current_source)
    target_before = inventory_item_result_from_row(current_target)
    try:
        result = merge_inventory_item_rows(
            connection,
            inventory_slug=target_inventory_slug,
            source_item=current_source,
            target_item=current_target,
            delete_source=request.mode == "move",
            acquisition_preference=request.keep_acquisition,
        )
    except ConflictError as exc:
        raise _transfer_acquisition_conflict_error(
            source_item_id=plan.source_item_id,
            target_inventory_slug=target_inventory_slug,
        ) from exc

    target_item_id = int(result["item_id"])
    target_after = load_inventory_item_snapshot(
        connection,
        inventory_slug=target_inventory_slug,
        item_id=target_item_id,
    )
    _write_transfer_audit_pair(
        connection,
        source_inventory_slug=source_inventory_slug,
        target_inventory_slug=target_inventory_slug,
        source_item_id=plan.source_item_id,
        target_item_id=target_item_id,
        source_before=source_before,
        source_after=None if request.mode == "move" else source_before,
        target_before=target_before,
        target_after=target_after,
        mode=request.mode,
        status="merged",
        merged=True,
        keep_acquisition=request.keep_acquisition,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return InventoryTransferItemResult(
        source_item_id=plan.source_item_id,
        target_item_id=target_item_id,
        status="merged",
        source_removed=request.mode == "move",
        message=None,
    )


def _execute_transfer_plan(
    connection: sqlite3.Connection,
    *,
    source_inventory_slug: str,
    target_inventory_slug: str,
    target_inventory_id: int,
    request: _TransferRequest,
    plans: list[_PlannedTransferItem],
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> list[InventoryTransferItemResult]:
    failures = [plan for plan in plans if plan.error is not None]
    if failures:
        raise failures[0].error  # type: ignore[misc]

    results: list[InventoryTransferItemResult] = []
    for plan in plans:
        if plan.status in {"copy", "move"}:
            results.append(
                _execute_copy_or_move(
                    connection,
                    source_inventory_slug=source_inventory_slug,
                    target_inventory_slug=target_inventory_slug,
                    target_inventory_id=target_inventory_id,
                    request=request,
                    plan=plan,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    request_id=request_id,
                )
            )
        elif plan.status == "merge":
            results.append(
                _execute_merge(
                    connection,
                    source_inventory_slug=source_inventory_slug,
                    target_inventory_slug=target_inventory_slug,
                    request=request,
                    plan=plan,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    request_id=request_id,
                )
            )
        else:
            raise ValueError(f"Unexpected transfer plan status: {plan.status}")
    return results


def _bounded_transfer_results(
    results: list[InventoryTransferItemResult],
) -> tuple[list[InventoryTransferItemResult], bool]:
    if len(results) <= _MAX_TRANSFER_RESULT_ROWS:
        return results, False
    return results[:_MAX_TRANSFER_RESULT_ROWS], True


def _build_transfer_result(
    *,
    source_inventory_slug: str,
    request: _TransferRequest,
    results: list[InventoryTransferItemResult],
) -> InventoryTransferResult:
    copied_count = 0
    moved_count = 0
    merged_count = 0
    failed_count = 0
    for result in results:
        outcome = _status_for_counts(result.status)
        if outcome == "copied":
            copied_count += 1
        elif outcome == "moved":
            moved_count += 1
        elif outcome == "merged":
            merged_count += 1
        else:
            failed_count += 1
    bounded_results, results_truncated = _bounded_transfer_results(results)
    return InventoryTransferResult(
        source_inventory=source_inventory_slug,
        target_inventory=request.target_inventory_slug,
        mode=request.mode,
        dry_run=request.dry_run,
        selection_kind=request.selection_kind,
        requested_item_ids=None if request.item_ids is None else list(request.item_ids),
        requested_count=len(results),
        copied_count=copied_count,
        moved_count=moved_count,
        merged_count=merged_count,
        failed_count=failed_count,
        results_returned=len(bounded_results),
        results_truncated=results_truncated,
        results=bounded_results,
    )


def transfer_inventory_items(
    db_path: str | Path,
    *,
    source_inventory_slug: str,
    target_inventory_slug: str,
    mode: str,
    item_ids: list[int] | None,
    all_items: bool = False,
    on_conflict: str,
    keep_acquisition: str | None = None,
    dry_run: bool = False,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> InventoryTransferResult:
    source_inventory_slug = normalize_inventory_slug(source_inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        result = transfer_inventory_items_with_connection(
            connection,
            source_inventory_slug=source_inventory_slug,
            target_inventory_slug=target_inventory_slug,
            mode=mode,
            item_ids=item_ids,
            all_items=all_items,
            on_conflict=on_conflict,
            keep_acquisition=keep_acquisition,
            dry_run=dry_run,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        if not dry_run:
            connection.commit()
        return result


def transfer_inventory_items_with_connection(
    connection: sqlite3.Connection,
    *,
    source_inventory_slug: str,
    target_inventory_slug: str,
    mode: str,
    item_ids: list[int] | None,
    all_items: bool = False,
    on_conflict: str,
    keep_acquisition: str | None = None,
    dry_run: bool = False,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> InventoryTransferResult:
    source_inventory_slug = normalize_inventory_slug(source_inventory_slug)
    request = _normalize_transfer_request(
        source_inventory_slug=source_inventory_slug,
        target_inventory_slug=target_inventory_slug,
        mode=mode,
        item_ids=item_ids,
        all_items=all_items,
        on_conflict=on_conflict,
        keep_acquisition=keep_acquisition,
        dry_run=dry_run,
    )
    get_inventory_row(connection, source_inventory_slug)
    target_inventory = get_inventory_row(connection, request.target_inventory_slug)
    source_rows = _load_transfer_source_rows(
        connection,
        source_inventory_slug=source_inventory_slug,
        item_ids=request.item_ids,
    )
    plans = _plan_transfer_items(
        connection,
        target_inventory_id=int(target_inventory["id"]),
        target_inventory_slug=request.target_inventory_slug,
        request=request,
        source_rows=source_rows,
    )
    if request.dry_run:
        dry_run_results = [_result_from_plan(plan, dry_run=True) for plan in plans]
        return _build_transfer_result(
            source_inventory_slug=source_inventory_slug,
            request=request,
            results=dry_run_results,
        )

    live_results = _execute_transfer_plan(
        connection,
        source_inventory_slug=source_inventory_slug,
        target_inventory_slug=request.target_inventory_slug,
        target_inventory_id=int(target_inventory["id"]),
        request=request,
        plans=plans,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return _build_transfer_result(
        source_inventory_slug=source_inventory_slug,
        request=request,
        results=live_results,
    )


def duplicate_inventory(
    db_path: str | Path,
    *,
    source_inventory_slug: str,
    target_slug: str,
    target_display_name: str,
    target_description: str | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> InventoryDuplicateResult:
    source_inventory_slug = normalize_inventory_slug(source_inventory_slug)
    target_slug = normalize_inventory_slug(target_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        source_inventory = connection.execute(
            """
            SELECT description
            FROM inventories
            WHERE slug = ?
            """,
            (source_inventory_slug,),
        ).fetchone()
        if source_inventory is None:
            get_inventory_row(connection, source_inventory_slug)
            raise AssertionError("Expected source inventory row to exist.")
        created_inventory = create_inventory_with_connection(
            connection,
            slug=target_slug,
            display_name=target_display_name,
            description=source_inventory["description"] if target_description is None else target_description,
            actor_id=actor_id,
        )
        transfer_result = transfer_inventory_items_with_connection(
            connection,
            source_inventory_slug=source_inventory_slug,
            target_inventory_slug=created_inventory.slug,
            mode="copy",
            item_ids=None,
            all_items=True,
            on_conflict="fail",
            keep_acquisition=None,
            dry_run=False,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()
        return InventoryDuplicateResult(
            source_inventory=source_inventory_slug,
            inventory=created_inventory,
            transfer=transfer_result,
        )
