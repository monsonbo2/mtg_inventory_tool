from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import initialize_database
from .normalize import (
    coerce_float,
    format_finishes,
    load_tags_json,
    merge_tags,
    normalize_condition_code,
    normalize_currency_code,
    normalize_external_id,
    normalize_finish,
    normalize_language_code,
    normalize_catalog_finishes,
    normalized_catalog_finish_list,
    parse_tags,
    tags_to_json,
    text_or_none,
    truncate,
)
from .queries import (
    add_catalog_filters,
    add_owned_filters,
    find_inventory_item_collision,
    get_inventory_item_row,
    get_inventory_row,
    get_or_create_inventory_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
    query_duplicate_like_groups,
    query_inventory_summary,
    query_merge_note_rows,
    query_missing_location_rows,
    query_missing_tag_rows,
    query_price_gaps,
    query_stale_price_rows,
)
from .reports import (
    build_currency_totals,
    build_top_value_rows,
    flatten_owned_export_rows,
    summarize_filters,
    write_inventory_export_csv,
)


def create_inventory(db_path: str | Path, slug: str, display_name: str, description: str | None) -> int:
    initialize_database(db_path)
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO inventories (slug, display_name, description)
            VALUES (?, ?, ?)
            """,
            (slug, display_name, description),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_inventories(db_path: str | Path) -> list[dict[str, Any]]:
    initialize_database(db_path)
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
    return [dict(row) for row in rows]


def search_cards(
    db_path: str | Path,
    query: str,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: str | None = None,
    lang: str | None = None,
    exact: bool = False,
    limit: int = 10,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        where_parts: list[str] = []
        params: list[Any] = []
        if exact:
            where_parts.append("LOWER(name) = LOWER(?)")
            params.append(query)
        else:
            where_parts.append("LOWER(name) LIKE LOWER(?)")
            params.append(f"%{query}%")

        add_catalog_filters(
            where_parts,
            params,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            lang=lang,
        )

        params.extend([query, limit])
        rows = connection.execute(
            f"""
            SELECT
                scryfall_id,
                name,
                set_code,
                set_name,
                collector_number,
                lang,
                rarity,
                finishes_json,
                tcgplayer_product_id
            FROM mtg_cards
            WHERE {' AND '.join(where_parts)}
            ORDER BY
                CASE WHEN LOWER(name) = LOWER(?) THEN 0 ELSE 1 END,
                name,
                released_at DESC,
                set_code,
                collector_number
            LIMIT ?
            """,
            params,
        ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["finishes"] = normalize_catalog_finishes(item.pop("finishes_json", None))
        results.append(item)
    return results


def resolve_card_row(
    connection: sqlite3.Connection,
    *,
    scryfall_id: str | None,
    tcgplayer_product_id: str | None,
    name: str | None,
    set_code: str | None,
    collector_number: str | None,
    lang: str | None,
) -> sqlite3.Row:
    if scryfall_id:
        row = connection.execute(
            """
            SELECT scryfall_id, name, set_code, set_name, collector_number, lang, finishes_json
            FROM mtg_cards
            WHERE scryfall_id = ?
            """,
            (scryfall_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No card found for scryfall_id '{scryfall_id}'.")
        return row

    if tcgplayer_product_id:
        row = connection.execute(
            """
            SELECT scryfall_id, name, set_code, set_name, collector_number, lang, finishes_json
            FROM mtg_cards
            WHERE tcgplayer_product_id = ?
            ORDER BY released_at DESC, set_code, collector_number
            LIMIT 2
            """,
            (tcgplayer_product_id,),
        ).fetchall()
        if not row:
            raise ValueError(f"No card found for tcgplayer_product_id '{tcgplayer_product_id}'.")
        if len(row) > 1:
            raise ValueError(
                "Multiple printings matched that TCGplayer product id. "
                "Narrow it with --scryfall-id or provide name/set details."
            )
        return row[0]

    if not name:
        raise ValueError("Provide either --scryfall-id, --tcgplayer-product-id, or --name.")

    params: list[Any] = [name]
    filters = ["LOWER(name) = LOWER(?)"]

    if set_code:
        filters.append("LOWER(set_code) = LOWER(?)")
        params.append(set_code)
    if collector_number:
        filters.append("collector_number = ?")
        params.append(collector_number)
    if lang:
        filters.append("LOWER(lang) = LOWER(?)")
        params.append(lang)

    rows = connection.execute(
        f"""
        SELECT scryfall_id, name, set_code, set_name, collector_number, lang, finishes_json
        FROM mtg_cards
        WHERE {' AND '.join(filters)}
        ORDER BY released_at DESC, set_code, collector_number
        LIMIT 10
        """,
        params,
    ).fetchall()

    if not rows:
        raise ValueError("No matching printing found. Try search-cards first to find the exact printing.")
    if len(rows) > 1:
        candidates = "; ".join(
            f"{row['set_code']} #{row['collector_number']} ({row['lang']}) [{row['scryfall_id']}]"
            for row in rows
        )
        raise ValueError(
            "Multiple printings matched that name. Narrow it with --set-code, --collector-number, or --scryfall-id. "
            f"Candidates: {candidates}"
        )
    return rows[0]


def add_card_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    inventory_display_name: str | None = None,
    scryfall_id: str | None,
    tcgplayer_product_id: str | None = None,
    name: str | None,
    set_code: str | None,
    collector_number: str | None,
    lang: str | None,
    quantity: int,
    condition_code: str,
    finish: str,
    language_code: str,
    location: str,
    acquisition_price: float | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None = None,
    inventory_cache: dict[str, sqlite3.Row] | None = None,
) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("--quantity must be a positive integer.")

    normalized_finish = normalize_finish(finish)
    if inventory_cache is None:
        inventory_cache = {}

    inventory = get_or_create_inventory_row(
        connection,
        inventory_slug,
        display_name=inventory_display_name,
        inventory_cache=inventory_cache,
        auto_create=inventory_display_name is not None,
    )

    card = resolve_card_row(
        connection,
        scryfall_id=scryfall_id,
        tcgplayer_product_id=normalize_external_id(tcgplayer_product_id),
        name=name,
        set_code=set_code,
        collector_number=collector_number,
        lang=lang,
    )

    new_tags = parse_tags(tags)
    existing_row = connection.execute(
        """
        SELECT tags_json
        FROM inventory_items
        WHERE inventory_id = ?
          AND scryfall_id = ?
          AND condition_code = ?
          AND finish = ?
          AND language_code = ?
          AND location = ?
        """,
        (
            inventory["id"],
            card["scryfall_id"],
            condition_code,
            normalized_finish,
            language_code,
            location,
        ),
    ).fetchone()
    merged_tags = merge_tags(
        load_tags_json(existing_row["tags_json"]) if existing_row is not None else [],
        new_tags,
    )

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
            tags_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (
            inventory_id,
            scryfall_id,
            condition_code,
            finish,
            language_code,
            location
        ) DO UPDATE SET
            quantity = inventory_items.quantity + excluded.quantity,
            acquisition_price = COALESCE(excluded.acquisition_price, inventory_items.acquisition_price),
            acquisition_currency = COALESCE(excluded.acquisition_currency, inventory_items.acquisition_currency),
            notes = COALESCE(excluded.notes, inventory_items.notes),
            tags_json = excluded.tags_json,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id, quantity
        """,
        (
            inventory["id"],
            card["scryfall_id"],
            quantity,
            condition_code,
            normalized_finish,
            language_code,
            location,
            acquisition_price,
            acquisition_currency,
            notes,
            tags_to_json(merged_tags),
        ),
    )
    item_row = cursor.fetchone()

    return {
        "inventory": inventory["slug"],
        "card_name": card["name"],
        "set_code": card["set_code"],
        "set_name": card["set_name"],
        "collector_number": card["collector_number"],
        "scryfall_id": card["scryfall_id"],
        "item_id": item_row["id"],
        "quantity": item_row["quantity"],
        "finish": normalized_finish,
        "condition_code": condition_code,
        "language_code": language_code,
        "location": location,
        "tags": merged_tags,
    }


def add_card(
    db_path: str | Path,
    *,
    inventory_slug: str,
    inventory_display_name: str | None = None,
    scryfall_id: str | None,
    tcgplayer_product_id: str | None = None,
    name: str | None,
    set_code: str | None,
    collector_number: str | None,
    lang: str | None,
    quantity: int,
    condition_code: str,
    finish: str,
    language_code: str,
    location: str,
    acquisition_price: float | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None = None,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        result = add_card_with_connection(
            connection,
            inventory_slug=inventory_slug,
            inventory_display_name=inventory_display_name,
            scryfall_id=scryfall_id,
            tcgplayer_product_id=tcgplayer_product_id,
            name=name,
            set_code=set_code,
            collector_number=collector_number,
            lang=lang,
            quantity=quantity,
            condition_code=condition_code,
            finish=finish,
            language_code=language_code,
            location=location,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            notes=notes,
            tags=tags,
        )
        connection.commit()
    return result


def set_quantity(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    quantity: int,
) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("--quantity must be a positive integer. Use remove-card to delete a row.")

    initialize_database(db_path)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        connection.execute(
            """
            UPDATE inventory_items
            SET quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (quantity, item_id),
        )
        connection.commit()

    result = inventory_item_result_from_row(item)
    result["old_quantity"] = item["quantity"]
    result["quantity"] = quantity
    return result


def set_acquisition(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    acquisition_price: float | None,
    acquisition_currency: str | None,
    clear: bool = False,
) -> dict[str, Any]:
    if clear and (acquisition_price is not None or acquisition_currency is not None):
        raise ValueError("Use either --clear or --price / --currency, not both.")
    if not clear and acquisition_price is None and acquisition_currency is None:
        raise ValueError("Provide at least one of --price or --currency, or use --clear.")
    if acquisition_price is not None and acquisition_price < 0:
        raise ValueError("--price must be zero or greater.")

    initialize_database(db_path)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        current_currency = text_or_none(item["acquisition_currency"])
        new_price = None if clear else item["acquisition_price"]
        new_currency = None if clear else current_currency

        if acquisition_price is not None:
            new_price = float(acquisition_price)
        if acquisition_currency is not None:
            new_currency = normalize_currency_code(acquisition_currency)

        if new_price is None and new_currency is not None:
            raise ValueError("Cannot store an acquisition currency without an acquisition price. Use --price too, or --clear.")

        connection.execute(
            """
            UPDATE inventory_items
            SET acquisition_price = ?, acquisition_currency = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (new_price, new_currency, item_id),
        )
        connection.commit()

    result = inventory_item_result_from_row(item)
    result["old_acquisition_price"] = item["acquisition_price"]
    result["old_acquisition_currency"] = current_currency
    result["acquisition_price"] = new_price
    result["acquisition_currency"] = new_currency
    return result


def set_finish_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_id: int,
    finish: str,
) -> dict[str, Any]:
    item = get_inventory_item_row(connection, inventory_slug, item_id)
    normalized_finish = normalize_finish(finish)
    if normalized_finish == item["finish"]:
        result = inventory_item_result_from_row(item)
        result["old_finish"] = item["finish"]
        return result

    try:
        connection.execute(
            """
            UPDATE inventory_items
            SET finish = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_finish, item_id),
        )
    except sqlite3.IntegrityError as exc:
        raise ValueError(
            "Changing finish would collide with an existing inventory row. "
            "Resolve the duplicate row first."
        ) from exc

    result = inventory_item_result_from_row(item)
    result["old_finish"] = item["finish"]
    result["finish"] = normalized_finish
    return result


def set_finish(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    finish: str,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        result = set_finish_with_connection(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
            finish=finish,
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
) -> dict[str, Any]:
    initialize_database(db_path)
    normalized_location = text_or_none(location) or ""
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        if normalized_location == item["location"]:
            result = inventory_item_result_from_row(item)
            result["old_location"] = item["location"]
            result["merged"] = False
            return result

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
                raise ValueError(
                    "Changing location would collide with an existing inventory row. "
                    "Re-run with --merge to combine the rows, or resolve the duplicate row first."
                )
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
            )
            result["old_location"] = item["location"]
            result["location"] = normalized_location
            connection.commit()
            return result

        connection.execute(
            """
            UPDATE inventory_items
            SET location = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_location, item_id),
        )
        connection.commit()

    result = inventory_item_result_from_row(item)
    result["old_location"] = item["location"]
    result["location"] = normalized_location
    result["merged"] = False
    return result


def set_condition(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    condition_code: str,
    merge: bool = False,
) -> dict[str, Any]:
    initialize_database(db_path)
    normalized_condition = normalize_condition_code(condition_code)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        if normalized_condition == item["condition_code"]:
            result = inventory_item_result_from_row(item)
            result["old_condition_code"] = item["condition_code"]
            result["merged"] = False
            return result

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
                raise ValueError(
                    "Changing condition would collide with an existing inventory row. "
                    "Re-run with --merge to combine the rows, or resolve the duplicate row first."
                )
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
            )
            result["old_condition_code"] = item["condition_code"]
            result["condition_code"] = normalized_condition
            connection.commit()
            return result

        connection.execute(
            """
            UPDATE inventory_items
            SET condition_code = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_condition, item_id),
        )
        connection.commit()

    result = inventory_item_result_from_row(item)
    result["old_condition_code"] = item["condition_code"]
    result["condition_code"] = normalized_condition
    result["merged"] = False
    return result


def split_row(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    quantity: int,
    condition_code: str | None,
    finish: str | None,
    language_code: str | None,
    location: str | None,
    clear_location: bool = False,
) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("--quantity must be a positive integer.")
    if clear_location and location is not None:
        raise ValueError("Use either --location or --clear-location, not both.")

    initialize_database(db_path)
    with connect(db_path) as connection:
        source_item = get_inventory_item_row(connection, inventory_slug, item_id)
        source_quantity = int(source_item["quantity"])
        if quantity > source_quantity:
            raise ValueError("--quantity cannot exceed the current row quantity.")

        target_condition = normalize_condition_code(condition_code) if condition_code is not None else source_item["condition_code"]
        target_finish = normalize_finish(finish) if finish is not None else source_item["finish"]
        target_language = normalize_language_code(language_code) if language_code is not None else source_item["language_code"]
        if clear_location:
            target_location = ""
        elif location is not None:
            target_location = text_or_none(location) or ""
        else:
            target_location = source_item["location"]

        if (
            target_condition == source_item["condition_code"]
            and target_finish == source_item["finish"]
            and target_language == source_item["language_code"]
            and target_location == source_item["location"]
        ):
            raise ValueError(
                "split-row needs a different condition, finish, language, or location for the target row."
            )

        target_item = find_inventory_item_collision(
            connection,
            inventory_id=source_item["inventory_id"],
            scryfall_id=source_item["scryfall_id"],
            condition_code=target_condition,
            finish=target_finish,
            language_code=target_language,
            location=target_location,
            exclude_item_id=item_id,
        )

        remaining_quantity = source_quantity - quantity
        if remaining_quantity == 0:
            connection.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
            source_deleted = True
        else:
            connection.execute(
                """
                UPDATE inventory_items
                SET quantity = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (remaining_quantity, item_id),
            )
            source_deleted = False

        if target_item is not None:
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=source_item,
                target_item=target_item,
                source_quantity=quantity,
                delete_source=False,
            )
            result["merged_into_existing"] = True
        else:
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
                    tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    source_item["inventory_id"],
                    source_item["scryfall_id"],
                    quantity,
                    target_condition,
                    target_finish,
                    target_language,
                    target_location,
                    source_item["acquisition_price"],
                    text_or_none(source_item["acquisition_currency"]),
                    text_or_none(source_item["notes"]),
                    source_item["tags_json"],
                ),
            )
            new_item_id = cursor.fetchone()["id"]
            new_item_row = get_inventory_item_row(connection, inventory_slug, new_item_id)
            result = inventory_item_result_from_row(new_item_row)
            result["merged_into_existing"] = False

        connection.commit()

    result["source_item_id"] = item_id
    result["source_old_quantity"] = source_quantity
    result["source_quantity"] = remaining_quantity
    result["source_deleted"] = source_deleted
    result["moved_quantity"] = quantity
    return result


def set_notes(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    notes: str | None,
) -> dict[str, Any]:
    initialize_database(db_path)
    normalized_notes = text_or_none(notes)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        connection.execute(
            """
            UPDATE inventory_items
            SET notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_notes, item_id),
        )
        connection.commit()

    result = inventory_item_result_from_row(item)
    result["old_notes"] = result["notes"]
    result["notes"] = normalized_notes
    return result


def set_tags(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    tags: str | None,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        normalized_tags = parse_tags(tags)
        connection.execute(
            """
            UPDATE inventory_items
            SET tags_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (tags_to_json(normalized_tags), item_id),
        )
        connection.commit()

    result = inventory_item_result_from_row(item)
    result["old_tags"] = result["tags"]
    result["tags"] = normalized_tags
    return result


def merge_rows(
    db_path: str | Path,
    *,
    inventory_slug: str,
    source_item_id: int,
    target_item_id: int,
) -> dict[str, Any]:
    if source_item_id == target_item_id:
        raise ValueError("Choose two different item ids when using merge-rows.")

    initialize_database(db_path)
    with connect(db_path) as connection:
        source_item = get_inventory_item_row(connection, inventory_slug, source_item_id)
        target_item = get_inventory_item_row(connection, inventory_slug, target_item_id)

        if source_item["scryfall_id"] != target_item["scryfall_id"]:
            raise ValueError("merge-rows currently requires both rows to reference the same printing.")

        result = merge_inventory_item_rows(
            connection,
            inventory_slug=inventory_slug,
            source_item=source_item,
            target_item=target_item,
        )
        connection.commit()

    result["target_old_quantity"] = target_item["quantity"]
    result["source_quantity"] = source_item["quantity"]
    return result


def remove_card(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        connection.execute(
            """
            DELETE FROM inventory_items
            WHERE id = ?
            """,
            (item_id,),
        )
        connection.commit()

    return inventory_item_result_from_row(item)


def list_price_gaps(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        return query_price_gaps(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=limit,
        )


def reconcile_prices(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    apply_changes: bool,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = query_price_gaps(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=None,
        )

        updated_rows: list[dict[str, Any]] = []
        remaining_rows: list[dict[str, Any]] = []
        rows_fixable = 0

        for row in rows:
            suggested_finish = row["suggested_finish"]
            if suggested_finish is None:
                remaining_rows.append(row)
                continue

            rows_fixable += 1
            if not apply_changes:
                updated_rows.append(row)
                continue

            try:
                updated = set_finish_with_connection(
                    connection,
                    inventory_slug=inventory_slug,
                    item_id=row["item_id"],
                    finish=suggested_finish,
                )
            except ValueError as exc:
                row["reconcile_status"] = str(exc)
                remaining_rows.append(row)
                continue

            updated["available_finishes"] = row["available_finishes"]
            updated["suggested_finish"] = suggested_finish
            updated["reconcile_status"] = "updated"
            updated_rows.append(updated)

        if apply_changes:
            connection.commit()

    return {
        "inventory": inventory_slug,
        "provider": provider,
        "applied": apply_changes,
        "rows_seen": len(rows),
        "rows_fixable": rows_fixable,
        "rows_updated": len(updated_rows) if apply_changes else 0,
        "updated_rows": updated_rows,
        "remaining_rows": remaining_rows,
    }


def inventory_health(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    stale_days: int,
    preview_limit: int,
) -> dict[str, Any]:
    if stale_days < 0:
        raise ValueError("--stale-days must be zero or greater.")
    if preview_limit <= 0:
        raise ValueError("--limit must be a positive integer.")

    initialize_database(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)
        current_date = dt.date.today()
        cutoff_date = current_date - dt.timedelta(days=stale_days)

        summary = query_inventory_summary(connection, inventory_slug=inventory_slug)
        missing_price_rows = query_price_gaps(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=None,
        )
        missing_location_rows = query_missing_location_rows(connection, inventory_slug=inventory_slug)
        missing_tag_rows = query_missing_tag_rows(connection, inventory_slug=inventory_slug)
        merge_note_rows = query_merge_note_rows(connection, inventory_slug=inventory_slug)
        stale_price_rows = query_stale_price_rows(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            current_date=current_date.isoformat(),
            cutoff_date=cutoff_date.isoformat(),
        )
        duplicate_groups = query_duplicate_like_groups(connection, inventory_slug=inventory_slug)

    formatted_missing_prices = [
        {
            "item_id": row["item_id"],
            "name": truncate(row["card_name"], 28),
            "set": row["set_code"],
            "number": row["collector_number"],
            "finish": row["finish"],
            "priced_finishes": truncate(format_finishes(row["available_finishes"]), 18),
            "status": truncate(row["reconcile_status"], 24),
        }
        for row in missing_price_rows
    ]

    summary.update(
        {
            "missing_price_rows": len(missing_price_rows),
            "missing_location_rows": len(missing_location_rows),
            "missing_tag_rows": len(missing_tag_rows),
            "merge_note_rows": len(merge_note_rows),
            "stale_price_rows": len(stale_price_rows),
            "duplicate_groups": len(duplicate_groups),
        }
    )

    return {
        "inventory": inventory_slug,
        "provider": provider,
        "stale_days": stale_days,
        "current_date": current_date.isoformat(),
        "preview_limit": preview_limit,
        "summary": summary,
        "missing_price_rows": formatted_missing_prices,
        "missing_location_rows": missing_location_rows,
        "missing_tag_rows": missing_tag_rows,
        "merge_note_rows": merge_note_rows,
        "stale_price_rows": stale_price_rows,
        "duplicate_groups": duplicate_groups,
    }


def list_owned(db_path: str | Path, inventory_slug: str, provider: str, limit: int | None) -> list[dict[str, Any]]:
    return list_owned_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        limit=limit,
        query=None,
        set_code=None,
        rarity=None,
        finish=None,
        condition_code=None,
        language_code=None,
        location=None,
        tags=None,
    )


def list_owned_filtered(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)
        params: list[Any] = [provider, inventory_slug]
        where_parts = ["i.slug = ?"]
        add_owned_filters(
            where_parts,
            params,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        )
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        rows = connection.execute(
            f"""
            WITH latest_prices AS (
                SELECT
                    scryfall_id,
                    provider,
                    finish,
                    currency,
                    price_value,
                    snapshot_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY scryfall_id, provider, finish, currency
                        ORDER BY snapshot_date DESC, id DESC
                    ) AS rn
                FROM price_snapshots
                WHERE price_kind = 'retail'
                  AND provider = ?
            )
            SELECT
                ii.id AS item_id,
                ii.scryfall_id,
                c.name,
                c.set_code,
                c.set_name,
                COALESCE(c.rarity, '') AS rarity,
                c.collector_number,
                ii.quantity,
                ii.condition_code,
                ii.finish,
                ii.language_code,
                ii.location,
                COALESCE(ii.tags_json, '[]') AS tags_json,
                ii.acquisition_price,
                COALESCE(ii.acquisition_currency, '') AS acquisition_currency,
                COALESCE(lp.currency, '') AS currency,
                COALESCE(lp.price_value, '') AS unit_price,
                COALESCE(ROUND(ii.quantity * lp.price_value, 2), '') AS est_value,
                COALESCE(lp.snapshot_date, '') AS price_date,
                COALESCE(ii.notes, '') AS notes
            FROM inventory_items ii
            JOIN inventories i ON i.id = ii.inventory_id
            JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
            LEFT JOIN latest_prices lp
                ON lp.scryfall_id = ii.scryfall_id
               AND lp.finish = ii.finish
               AND lp.rn = 1
            WHERE {' AND '.join(where_parts)}
            ORDER BY c.name, c.set_code, c.collector_number, ii.condition_code, ii.finish
            {limit_sql}
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def export_inventory_csv(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    output_path: str | Path,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
    limit: int | None,
) -> dict[str, Any]:
    rows = list_owned_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        limit=limit,
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )
    output = write_inventory_export_csv(
        output_path,
        rows,
        inventory_slug=inventory_slug,
        provider=provider,
    )
    return {
        "inventory": inventory_slug,
        "provider": provider,
        "output_path": str(output),
        "rows_exported": len(rows),
        "filters_text": summarize_filters(
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        ),
        "rows": rows,
    }


def valuation(db_path: str | Path, inventory_slug: str, provider: str | None) -> list[dict[str, Any]]:
    return valuation_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        query=None,
        set_code=None,
        rarity=None,
        finish=None,
        condition_code=None,
        language_code=None,
        location=None,
        tags=None,
    )


def valuation_filtered(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str | None,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)

        if provider:
            params: list[Any] = [provider, provider, inventory_slug]
            where_parts = ["i.slug = ?"]
            add_owned_filters(
                where_parts,
                params,
                query=query,
                set_code=set_code,
                rarity=rarity,
                finish=finish,
                condition_code=condition_code,
                language_code=language_code,
                location=location,
                tags=tags,
            )
            rows = connection.execute(
                f"""
                WITH latest_prices AS (
                    SELECT
                        scryfall_id,
                        provider,
                        finish,
                        currency,
                        price_value,
                        ROW_NUMBER() OVER (
                            PARTITION BY scryfall_id, provider, finish, currency
                            ORDER BY snapshot_date DESC, id DESC
                        ) AS rn
                    FROM price_snapshots
                    WHERE price_kind = 'retail'
                      AND provider = ?
                )
                SELECT
                    ? AS provider,
                    COALESCE(lp.currency, '') AS currency,
                    COUNT(ii.id) AS item_rows,
                    COALESCE(SUM(ii.quantity), 0) AS total_cards,
                    ROUND(COALESCE(SUM(ii.quantity * lp.price_value), 0), 2) AS total_value
                FROM inventory_items ii
                JOIN inventories i ON i.id = ii.inventory_id
                JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
                LEFT JOIN latest_prices lp
                    ON lp.scryfall_id = ii.scryfall_id
                   AND lp.finish = ii.finish
                   AND lp.rn = 1
                WHERE {' AND '.join(where_parts)}
                GROUP BY lp.currency
                ORDER BY lp.currency
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

        params = [inventory_slug]
        where_parts = ["i.slug = ?"]
        add_owned_filters(
            where_parts,
            params,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        )
        rows = connection.execute(
            f"""
            WITH latest_prices AS (
                SELECT
                    scryfall_id,
                    provider,
                    finish,
                    currency,
                    price_value,
                    ROW_NUMBER() OVER (
                        PARTITION BY scryfall_id, provider, finish, currency
                        ORDER BY snapshot_date DESC, id DESC
                    ) AS rn
                FROM price_snapshots
                WHERE price_kind = 'retail'
            )
            SELECT
                lp.provider,
                lp.currency,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards,
                ROUND(COALESCE(SUM(ii.quantity * lp.price_value), 0), 2) AS total_value
            FROM inventory_items ii
            JOIN inventories i ON i.id = ii.inventory_id
            JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
            LEFT JOIN latest_prices lp
                ON lp.scryfall_id = ii.scryfall_id
               AND lp.finish = ii.finish
               AND lp.rn = 1
            WHERE {' AND '.join(where_parts)}
            GROUP BY lp.provider, lp.currency
            ORDER BY lp.provider, lp.currency
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def inventory_report(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
    limit: int,
    stale_days: int,
) -> dict[str, Any]:
    rows = list_owned_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        limit=None,
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )
    valuation_rows = valuation_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )
    health = inventory_health(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        stale_days=stale_days,
        preview_limit=limit,
    )
    filtered_health_summary = {
        "item_rows": len(rows),
        "total_cards": sum(int(row["quantity"]) for row in rows),
        "missing_price_rows": 0,
        "missing_location_rows": 0,
        "missing_tag_rows": 0,
        "merge_note_rows": 0,
        "stale_price_rows": 0,
        "duplicate_groups": 0,
    }

    filters_text = summarize_filters(
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )

    summary = {
        "item_rows": len(rows),
        "total_cards": sum(int(row["quantity"]) for row in rows),
        "unique_printings": len({row["scryfall_id"] for row in rows}),
        "unique_card_names": len({row["name"] for row in rows}),
        "valued_rows": sum(1 for row in rows if coerce_float(row.get("unit_price")) is not None),
        "unpriced_rows": sum(1 for row in rows if coerce_float(row.get("unit_price")) is None),
    }

    acquisition_totals = build_currency_totals(
        rows,
        value_key="acquisition_price",
        currency_key="acquisition_currency",
        quantity_key="quantity",
    )
    top_rows = build_top_value_rows(rows, limit=limit)

    if filters_text == "(none)":
        filtered_health_summary = health["summary"]
    else:
        missing_price_ids = {row["item_id"] for row in health["missing_price_rows"]}
        missing_location_ids = {row["item_id"] for row in health["missing_location_rows"]}
        missing_tag_ids = {row["item_id"] for row in health["missing_tag_rows"]}
        merge_note_ids = {row["item_id"] for row in health["merge_note_rows"]}
        stale_price_ids = {row["item_id"] for row in health["stale_price_rows"]}
        filtered_ids = {row["item_id"] for row in rows}
        filtered_health_summary.update(
            {
                "missing_price_rows": len(filtered_ids & missing_price_ids),
                "missing_location_rows": len(filtered_ids & missing_location_ids),
                "missing_tag_rows": len(filtered_ids & missing_tag_ids),
                "merge_note_rows": len(filtered_ids & merge_note_ids),
                "stale_price_rows": len(filtered_ids & stale_price_ids),
                "duplicate_groups": health["summary"]["duplicate_groups"],
            }
        )
        health = {**health, "summary": filtered_health_summary}

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "inventory": inventory_slug,
        "provider": provider,
        "filters_text": filters_text,
        "summary": summary,
        "valuation_rows": valuation_rows,
        "acquisition_totals": acquisition_totals,
        "top_rows": top_rows,
        "health": health,
        "rows": flatten_owned_export_rows(rows, inventory_slug=inventory_slug, provider=provider),
    }
