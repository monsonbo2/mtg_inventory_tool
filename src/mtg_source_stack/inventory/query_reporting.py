"""Reporting and health-check query helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from .normalize import (
    MERGED_ACQUISITION_NOTE_MARKER,
    format_tags,
    load_tags_json,
    text_or_none,
    truncate,
)


def build_health_item_preview(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    tags_value = row["tags_json"] if "tags_json" in row.keys() else row.get("tags_json", "[]")
    return {
        "item_id": row["item_id"],
        "name": truncate(row["card_name"], 28),
        "set": row["set_code"],
        "number": row["collector_number"],
        "qty": row["quantity"],
        "cond": row["condition_code"],
        "finish": row["finish"],
        "location": truncate(text_or_none(row["location"]) or "(none)", 18),
        "tags": truncate(format_tags(load_tags_json(tags_value)), 24),
        "note": truncate(text_or_none(row["notes"]) or "", 32),
    }


def query_inventory_summary(connection: sqlite3.Connection, *, inventory_slug: str) -> dict[str, int]:
    row = connection.execute(
        """
        SELECT
            COUNT(ii.id) AS item_rows,
            COALESCE(SUM(ii.quantity), 0) AS total_cards
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        WHERE i.slug = ?
        """,
        (inventory_slug,),
    ).fetchone()
    return {
        "item_rows": int(row["item_rows"]),
        "total_cards": int(row["total_cards"]),
    }


def query_missing_location_rows(connection: sqlite3.Connection, *, inventory_slug: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            ii.id AS item_id,
            c.name AS card_name,
            c.set_code,
            c.collector_number,
            ii.quantity,
            ii.condition_code,
            ii.finish,
            ii.location,
            COALESCE(ii.tags_json, '[]') AS tags_json,
            COALESCE(ii.notes, '') AS notes
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        WHERE i.slug = ?
          AND TRIM(COALESCE(ii.location, '')) = ''
        ORDER BY c.name, c.set_code, c.collector_number, ii.id
        """,
        (inventory_slug,),
    ).fetchall()
    return [build_health_item_preview(row) for row in rows]


def query_missing_tag_rows(connection: sqlite3.Connection, *, inventory_slug: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            ii.id AS item_id,
            c.name AS card_name,
            c.set_code,
            c.collector_number,
            ii.quantity,
            ii.condition_code,
            ii.finish,
            ii.location,
            COALESCE(ii.tags_json, '[]') AS tags_json,
            COALESCE(ii.notes, '') AS notes
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        WHERE i.slug = ?
          AND TRIM(COALESCE(ii.tags_json, '[]')) IN ('', '[]')
        ORDER BY c.name, c.set_code, c.collector_number, ii.id
        """,
        (inventory_slug,),
    ).fetchall()
    return [build_health_item_preview(row) for row in rows]


def query_merge_note_rows(connection: sqlite3.Connection, *, inventory_slug: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            ii.id AS item_id,
            c.name AS card_name,
            c.set_code,
            c.collector_number,
            ii.quantity,
            ii.condition_code,
            ii.finish,
            ii.location,
            COALESCE(ii.tags_json, '[]') AS tags_json,
            COALESCE(ii.notes, '') AS notes
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        WHERE i.slug = ?
          AND ii.notes LIKE ?
        ORDER BY c.name, c.set_code, c.collector_number, ii.id
        """,
        (inventory_slug, f"%{MERGED_ACQUISITION_NOTE_MARKER}%"),
    ).fetchall()
    return [build_health_item_preview(row) for row in rows]


def query_duplicate_like_groups(connection: sqlite3.Connection, *, inventory_slug: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            ii.scryfall_id,
            c.name AS card_name,
            c.set_code,
            c.collector_number,
            ii.condition_code,
            ii.finish,
            ii.language_code,
            COUNT(ii.id) AS item_rows,
            COALESCE(SUM(ii.quantity), 0) AS total_cards,
            GROUP_CONCAT(DISTINCT CASE WHEN TRIM(ii.location) = '' THEN '(none)' ELSE ii.location END) AS locations
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        WHERE i.slug = ?
        GROUP BY ii.scryfall_id, ii.condition_code, ii.finish, ii.language_code
        HAVING COUNT(ii.id) > 1
        ORDER BY item_rows DESC, total_cards DESC, c.name, c.set_code, c.collector_number
        """,
        (inventory_slug,),
    ).fetchall()
    return [
        {
            "scryfall_id": row["scryfall_id"],
            "condition_code": row["condition_code"],
            "language_code": row["language_code"],
            "name": truncate(row["card_name"], 28),
            "set": row["set_code"],
            "number": row["collector_number"],
            "cond": row["condition_code"],
            "finish": row["finish"],
            "rows": row["item_rows"],
            "qty": row["total_cards"],
            "locations": truncate(text_or_none(row["locations"]) or "(none)", 32),
        }
        for row in rows
    ]
