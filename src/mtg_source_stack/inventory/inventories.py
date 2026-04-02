"""Inventory container creation and listing helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ConflictError, ValidationError
from .access import grant_inventory_membership_with_connection, is_global_admin
from .normalize import text_or_none
from .response_models import InventoryCreateResult, InventoryListRow


def _inventory_list_rows(rows: list[sqlite3.Row]) -> list[InventoryListRow]:
    return [
        InventoryListRow(
            slug=row["slug"],
            display_name=row["display_name"],
            description=text_or_none(row["description"]),
            item_rows=int(row["item_rows"]),
            total_cards=int(row["total_cards"]),
        )
        for row in rows
    ]


def _normalized_visible_actor_id(actor_id: str | None) -> str | None:
    if actor_id is None:
        return None
    normalized = actor_id.strip()
    if not normalized:
        raise ValidationError("actor_id is required.")
    return normalized


def create_inventory(
    db_path: str | Path,
    slug: str,
    display_name: str,
    description: str | None,
    actor_id: str | None = None,
) -> InventoryCreateResult:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO inventories (slug, display_name, description)
                VALUES (?, ?, ?)
                """,
                (slug, display_name, description),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"Inventory '{slug}' already exists.") from exc
        if actor_id is not None:
            grant_inventory_membership_with_connection(
                connection,
                inventory_id=int(cursor.lastrowid),
                actor_id=actor_id,
                role="owner",
            )
        connection.commit()
        return InventoryCreateResult(
            inventory_id=int(cursor.lastrowid),
            slug=slug,
            display_name=display_name,
            description=text_or_none(description),
        )


def list_inventories(db_path: str | Path) -> list[InventoryListRow]:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        rows = connection.execute(
            """
            SELECT
                i.slug,
                i.display_name,
                COALESCE(i.description, '') AS description,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards
            FROM inventories i
            LEFT JOIN inventory_items ii ON ii.inventory_id = i.id
            GROUP BY i.id, i.slug, i.display_name, i.description
            ORDER BY i.slug
            """
        ).fetchall()
    return _inventory_list_rows(rows)


def list_visible_inventories(
    db_path: str | Path,
    *,
    actor_id: str | None,
    actor_roles: Iterable[str],
) -> list[InventoryListRow]:
    if is_global_admin(actor_roles):
        return list_inventories(db_path)
    normalized_actor_id = _normalized_visible_actor_id(actor_id)
    if normalized_actor_id is None:
        return []
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        rows = connection.execute(
            """
            SELECT
                i.slug,
                i.display_name,
                COALESCE(i.description, '') AS description,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards
            FROM inventories i
            JOIN inventory_memberships im
                ON im.inventory_id = i.id
            LEFT JOIN inventory_items ii ON ii.inventory_id = i.id
            WHERE im.actor_id = ?
            GROUP BY i.id, i.slug, i.display_name, i.description
            ORDER BY i.slug
            """,
            (normalized_actor_id,),
        ).fetchall()
    return _inventory_list_rows(rows)
