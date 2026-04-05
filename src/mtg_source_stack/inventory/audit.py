"""Transactional audit helpers for inventory mutations."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import sqlite3
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import require_current_schema
from .normalize import DEFAULT_AUDIT_EVENT_LIMIT, MAX_AUDIT_EVENT_LIMIT, normalize_inventory_slug, validate_limit_value
from .query_inventory import get_inventory_item_row, inventory_item_result_from_row
from .query_inventory import get_inventory_row
from .response_models import InventoryAuditEvent, serialize_response


def format_audit_timestamp(value: str) -> str:
    text = value.strip()
    if not text:
        return value

    normalized = text.replace("Z", "+00:00")
    occurred_at = datetime.fromisoformat(normalized)
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def inventory_item_snapshot(payload: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    if isinstance(payload, sqlite3.Row):
        return serialize_response(inventory_item_result_from_row(payload))
    return serialize_response(dict(payload))


def load_inventory_item_snapshot(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_id: int,
) -> dict[str, Any]:
    row = get_inventory_item_row(connection, inventory_slug, item_id)
    snapshot = inventory_item_snapshot(row)
    if snapshot is None:
        raise ValueError("Expected an inventory row snapshot.")
    return snapshot


def write_inventory_audit_event(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    action: str,
    item_id: int | None = None,
    before: sqlite3.Row | dict[str, Any] | None = None,
    after: sqlite3.Row | dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> None:
    before_snapshot = inventory_item_snapshot(before)
    after_snapshot = inventory_item_snapshot(after)
    effective_item_id = item_id
    if effective_item_id is None:
        if after_snapshot is not None:
            effective_item_id = int(after_snapshot["item_id"])
        elif before_snapshot is not None:
            effective_item_id = int(before_snapshot["item_id"])

    connection.execute(
        """
        INSERT INTO inventory_audit_log (
            inventory_slug,
            item_id,
            action,
            actor_type,
            actor_id,
            request_id,
            before_json,
            after_json,
            metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            inventory_slug,
            effective_item_id,
            action,
            actor_type,
            actor_id,
            request_id,
            json.dumps(before_snapshot, ensure_ascii=True, separators=(",", ":")) if before_snapshot else None,
            json.dumps(after_snapshot, ensure_ascii=True, separators=(",", ":")) if after_snapshot else None,
            json.dumps(serialize_response(metadata or {}), ensure_ascii=True, separators=(",", ":")),
        ),
    )


def list_inventory_audit_events(
    db_path: str | Path,
    *,
    inventory_slug: str,
    limit: int = DEFAULT_AUDIT_EVENT_LIMIT,
    item_id: int | None = None,
) -> list[InventoryAuditEvent]:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    validate_limit_value(limit, maximum=MAX_AUDIT_EVENT_LIMIT)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        get_inventory_row(connection, inventory_slug)
        where_parts = ["inventory_slug = ?"]
        params: list[Any] = [inventory_slug]
        if item_id is not None:
            where_parts.append("item_id = ?")
            params.append(item_id)

        rows = connection.execute(
            f"""
            SELECT
                id,
                inventory_slug,
                item_id,
                action,
                actor_type,
                actor_id,
                request_id,
                occurred_at,
                before_json,
                after_json,
                metadata_json
            FROM inventory_audit_log
            WHERE {' AND '.join(where_parts)}
            ORDER BY occurred_at DESC, id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()

    return [
        InventoryAuditEvent(
            id=int(row["id"]),
            inventory=row["inventory_slug"],
            item_id=int(row["item_id"]) if row["item_id"] is not None else None,
            action=row["action"],
            actor_type=row["actor_type"],
            actor_id=row["actor_id"],
            request_id=row["request_id"],
            occurred_at=format_audit_timestamp(row["occurred_at"]),
            before=json.loads(row["before_json"]) if row["before_json"] else None,
            after=json.loads(row["after_json"]) if row["after_json"] else None,
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )
        for row in rows
    ]
