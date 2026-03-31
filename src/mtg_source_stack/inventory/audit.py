"""Transactional audit helpers for inventory mutations."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .query_inventory import get_inventory_item_row, inventory_item_result_from_row
from .response_models import serialize_response


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
