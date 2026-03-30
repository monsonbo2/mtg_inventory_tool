from __future__ import annotations

import sqlite3
from typing import Any

from .normalize import (
    MERGED_ACQUISITION_NOTE_MARKER,
    format_acquisition_summary,
    format_finishes,
    format_tags,
    load_tags_json,
    merge_note_text,
    merge_tags,
    normalize_finish,
    normalized_catalog_finish_list,
    normalize_tag,
    parse_finish_list,
    parse_tag_filters,
    tags_to_json,
    text_or_none,
    truncate,
)


def build_catalog_finish_filter(normalized_finish: str) -> tuple[str, ...]:
    if normalized_finish == "normal":
        return ("normal", "nonfoil")
    return (normalized_finish,)


def add_catalog_filters(
    where_parts: list[str],
    params: list[Any],
    *,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    lang: str | None,
) -> None:
    if set_code:
        where_parts.append("LOWER(set_code) = LOWER(?)")
        params.append(set_code)

    if rarity:
        where_parts.append("LOWER(COALESCE(rarity, '')) = LOWER(?)")
        params.append(rarity)

    if lang:
        where_parts.append("LOWER(lang) = LOWER(?)")
        params.append(lang)

    if finish:
        tokens = build_catalog_finish_filter(normalize_finish(finish))
        finish_parts = []
        for token in tokens:
            finish_parts.append("LOWER(finishes_json) LIKE ?")
            params.append(f'%"{token.lower()}"%')
        where_parts.append("(" + " OR ".join(finish_parts) + ")")


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
        "acquisition_price": row["acquisition_price"],
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
) -> dict[str, Any]:
    source_quantity = int(source_item["quantity"]) if source_quantity is None else int(source_quantity)
    merged_quantity = int(target_item["quantity"]) + source_quantity
    merged_tags = merge_tags(load_tags_json(target_item["tags_json"]), load_tags_json(source_item["tags_json"]))

    target_acquisition_price = target_item["acquisition_price"]
    source_acquisition_price = source_item["acquisition_price"]
    target_acquisition_currency = text_or_none(target_item["acquisition_currency"])
    source_acquisition_currency = text_or_none(source_item["acquisition_currency"])

    if target_acquisition_price is not None:
        merged_acquisition_price = target_acquisition_price
        merged_acquisition_currency = target_acquisition_currency or source_acquisition_currency
    else:
        merged_acquisition_price = source_acquisition_price
        merged_acquisition_currency = source_acquisition_currency or target_acquisition_currency

    merged_notes = merge_note_text(
        target_notes=text_or_none(target_item["notes"]),
        source_notes=text_or_none(source_item["notes"]),
        source_item_id=source_item["item_id"],
        target_acquisition_summary=format_acquisition_summary(
            target_acquisition_price,
            target_acquisition_currency,
        ),
        source_acquisition_summary=format_acquisition_summary(
            source_acquisition_price,
            source_acquisition_currency,
        ),
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
            merged_quantity,
            merged_acquisition_price,
            merged_acquisition_currency,
            merged_notes,
            tags_to_json(merged_tags),
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


def build_price_gap_result(row: sqlite3.Row) -> dict[str, Any]:
    result = inventory_item_result_from_row(row)
    available_finishes = parse_finish_list(row["available_finishes"])
    result["available_finishes"] = available_finishes
    if not available_finishes:
        result["suggested_finish"] = None
        result["reconcile_status"] = "no priced finishes"
    elif len(available_finishes) == 1:
        result["suggested_finish"] = available_finishes[0]
        result["reconcile_status"] = "single priced finish"
    else:
        result["suggested_finish"] = None
        result["reconcile_status"] = "multiple priced finishes"
    return result


def query_price_gaps(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    get_inventory_row(connection, inventory_slug)
    sql = """
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
        COALESCE(ii.tags_json, '[]') AS tags_json,
        GROUP_CONCAT(DISTINCT ps.finish) AS available_finishes
    FROM inventory_items ii
    JOIN inventories i ON i.id = ii.inventory_id
    JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
    LEFT JOIN price_snapshots ps
      ON ps.scryfall_id = ii.scryfall_id
     AND LOWER(ps.provider) = LOWER(?)
     AND ps.price_kind = 'retail'
    WHERE i.slug = ?
    GROUP BY
        ii.id,
        ii.inventory_id,
        i.slug,
        ii.scryfall_id,
        c.name,
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
        ii.tags_json
    HAVING SUM(CASE WHEN LOWER(COALESCE(ps.finish, '')) = LOWER(ii.finish) THEN 1 ELSE 0 END) = 0
    ORDER BY c.name, c.set_code, c.collector_number
    """
    params: list[Any] = [provider, inventory_slug]
    if limit is not None:
        sql += "\nLIMIT ?"
        params.append(limit)

    rows = connection.execute(sql, params).fetchall()
    return [build_price_gap_result(row) for row in rows]


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


def query_stale_price_rows(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    provider: str,
    current_date: str,
    cutoff_date: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        WITH latest_prices AS (
            SELECT
                scryfall_id,
                finish,
                snapshot_date,
                ROW_NUMBER() OVER (
                    PARTITION BY scryfall_id, finish
                    ORDER BY snapshot_date DESC, id DESC
                ) AS rn
            FROM price_snapshots
            WHERE price_kind = 'retail'
              AND provider = ?
        )
        SELECT
            ii.id AS item_id,
            c.name AS card_name,
            c.set_code,
            c.collector_number,
            ii.finish,
            lp.snapshot_date AS price_date,
            CAST(julianday(?) - julianday(lp.snapshot_date) AS INTEGER) AS age_days
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        JOIN latest_prices lp
            ON lp.scryfall_id = ii.scryfall_id
           AND lp.finish = ii.finish
           AND lp.rn = 1
        WHERE i.slug = ?
          AND lp.snapshot_date < ?
        ORDER BY age_days DESC, c.name, c.set_code, c.collector_number, ii.id
        """,
        (provider, current_date, inventory_slug, cutoff_date),
    ).fetchall()
    return [
        {
            "item_id": row["item_id"],
            "name": truncate(row["card_name"], 28),
            "set": row["set_code"],
            "number": row["collector_number"],
            "finish": row["finish"],
            "price_date": row["price_date"],
            "age_days": row["age_days"],
        }
        for row in rows
    ]


def query_duplicate_like_groups(connection: sqlite3.Connection, *, inventory_slug: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
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
