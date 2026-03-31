"""Inventory row lookup and merge SQL helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from .money import coerce_decimal
from .normalize import load_tags_json, normalize_finish, parse_tag_filters, text_or_none
from .policies import build_merged_inventory_item_update


def add_owned_filters(
    where_parts: list[str],
    params: list[Any],
    *,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
) -> None:
    if query:
        where_parts.append("LOWER(c.name) LIKE LOWER(?)")
        params.append(f"%{query}%")

    if set_code:
        where_parts.append("LOWER(c.set_code) = LOWER(?)")
        params.append(set_code)

    if rarity:
        where_parts.append("LOWER(COALESCE(c.rarity, '')) = LOWER(?)")
        params.append(rarity)

    if finish:
        where_parts.append("LOWER(ii.finish) = LOWER(?)")
        params.append(normalize_finish(finish))

    if condition_code:
        where_parts.append("LOWER(ii.condition_code) = LOWER(?)")
        params.append(condition_code)

    if language_code:
        where_parts.append("LOWER(ii.language_code) = LOWER(?)")
        params.append(language_code)

    if location:
        where_parts.append("LOWER(ii.location) LIKE LOWER(?)")
        params.append(f"%{location}%")

    for tag in parse_tag_filters(tags):
        where_parts.append("LOWER(COALESCE(ii.tags_json, '[]')) LIKE ?")
        params.append(f'%"{tag}"%')


def get_inventory_row(connection: sqlite3.Connection, slug: str) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT id, slug, display_name
        FROM inventories
        WHERE slug = ?
        """,
        (slug,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown inventory '{slug}'. Create it first with create-inventory.")
    return row


def get_or_create_inventory_row(
    connection: sqlite3.Connection,
    slug: str,
    *,
    display_name: str | None,
    inventory_cache: dict[str, sqlite3.Row] | None = None,
    auto_create: bool = False,
) -> sqlite3.Row:
    if inventory_cache is not None and slug in inventory_cache:
        return inventory_cache[slug]

    row = connection.execute(
        """
        SELECT id, slug, display_name
        FROM inventories
        WHERE slug = ?
        """,
        (slug,),
    ).fetchone()

    if row is None and auto_create:
        cursor = connection.execute(
            """
            INSERT INTO inventories (slug, display_name)
            VALUES (?, ?)
            RETURNING id, slug, display_name
            """,
            (slug, display_name or slug),
        )
        row = cursor.fetchone()

    if row is None:
        raise ValueError(f"Unknown inventory '{slug}'. Create it first with create-inventory.")

    if inventory_cache is not None:
        inventory_cache[slug] = row
    return row


def get_inventory_item_row(connection: sqlite3.Connection, inventory_slug: str, item_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            ii.id AS item_id,
            ii.inventory_id,
            i.slug AS inventory,
            ii.scryfall_id,
            c.name AS card_name,
            c.set_code,
            c.set_name,
            c.collector_number,
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
        WHERE i.slug = ?
          AND ii.id = ?
        """,
        (inventory_slug, item_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"No inventory row found for item_id '{item_id}' in inventory '{inventory_slug}'.")
    return row


def inventory_item_result_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "inventory": row["inventory"],
        "card_name": row["card_name"],
        "set_code": row["set_code"],
        "set_name": row["set_name"],
        "collector_number": row["collector_number"],
        "scryfall_id": row["scryfall_id"],
        "item_id": row["item_id"],
        "quantity": row["quantity"],
        "finish": row["finish"],
        "condition_code": row["condition_code"],
        "language_code": row["language_code"],
        "location": row["location"],
        "acquisition_price": coerce_decimal(row["acquisition_price"]),
        "acquisition_currency": text_or_none(row["acquisition_currency"]),
        "notes": text_or_none(row["notes"]),
        "tags": load_tags_json(row["tags_json"]),
    }


def find_inventory_item_collision(
    connection: sqlite3.Connection,
    *,
    inventory_id: int,
    scryfall_id: str,
    condition_code: str,
    finish: str,
    language_code: str,
    location: str,
    exclude_item_id: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            ii.id AS item_id,
            ii.inventory_id,
            i.slug AS inventory,
            ii.scryfall_id,
            c.name AS card_name,
            c.set_code,
            c.set_name,
            c.collector_number,
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
          AND ii.scryfall_id = ?
          AND ii.condition_code = ?
          AND ii.finish = ?
          AND ii.language_code = ?
          AND ii.location = ?
          AND ii.id != ?
        """,
        (
            inventory_id,
            scryfall_id,
            condition_code,
            finish,
            language_code,
            location,
            exclude_item_id,
        ),
    ).fetchone()


def merge_inventory_item_rows(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    source_quantity: int | None = None,
    delete_source: bool = True,
    acquisition_preference: str | None = None,
) -> dict[str, Any]:
    source_quantity = int(source_item["quantity"]) if source_quantity is None else int(source_quantity)
    merged_update = build_merged_inventory_item_update(
        source_item,
        target_item,
        source_quantity=source_quantity,
        acquisition_preference=acquisition_preference,
    )

    connection.execute(
        """
        UPDATE inventory_items
        SET
            quantity = ?,
            acquisition_price = ?,
            acquisition_currency = ?,
            notes = ?,
            tags_json = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            merged_update["quantity"],
            merged_update["acquisition_price"],
            merged_update["acquisition_currency"],
            merged_update["notes"],
            merged_update["tags_json"],
            target_item["item_id"],
        ),
    )
    if delete_source:
        connection.execute("DELETE FROM inventory_items WHERE id = ?", (source_item["item_id"],))

    merged_row = get_inventory_item_row(connection, inventory_slug, target_item["item_id"])
    result = inventory_item_result_from_row(merged_row)
    result["merged"] = True
    result["merged_source_item_id"] = source_item["item_id"]
    result["source_quantity"] = source_quantity
    return result
