"""Inventory container creation and listing helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..db.connection import connect
from ..db.schema import initialize_database, require_current_schema
from .normalize import text_or_none
from .response_models import InventoryListRow


def create_inventory(db_path: str | Path, slug: str, display_name: str, description: str | None) -> int:
    initialize_database(db_path)
    with connect(db_path) as connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO inventories (slug, display_name, description)
                VALUES (?, ?, ?)
                """,
                (slug, display_name, description),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"Inventory '{slug}' already exists.") from exc
        connection.commit()
        return int(cursor.lastrowid)


def list_inventories(db_path: str | Path) -> list[InventoryListRow]:
    require_current_schema(db_path)
    with connect(db_path) as connection:
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
