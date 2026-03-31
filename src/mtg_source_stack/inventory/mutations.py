"""Inventory write operations and row-shaping mutations."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..db.connection import connect, require_database_file
from ..db.schema import initialize_database
from .catalog import resolve_card_row
from .money import coerce_decimal
from .normalize import (
    load_tags_json,
    merge_tags,
    normalize_condition_code,
    normalize_currency_code,
    normalize_external_id,
    normalize_finish,
    normalize_language_code,
    parse_tags,
    tags_to_json,
    text_or_none,
)
from .policies import ensure_add_card_metadata_compatible, resolve_merge_acquisition, row_matches_identity
from .query_inventory import (
    find_inventory_item_collision,
    get_inventory_item_row,
    get_or_create_inventory_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)


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
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None = None,
    inventory_cache: dict[str, sqlite3.Row] | None = None,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    if quantity <= 0:
        raise ValueError("--quantity must be a positive integer.")

    normalized_condition = normalize_condition_code(condition_code)
    normalized_finish = normalize_finish(finish)
    normalized_language = normalize_language_code(language_code)
    normalized_location = text_or_none(location) or ""
    normalized_acquisition_price = coerce_decimal(acquisition_price)
    normalized_acquisition_currency = normalize_currency_code(acquisition_currency)
    normalized_notes = text_or_none(notes)
    if normalized_acquisition_price is None and normalized_acquisition_currency is not None:
        raise ValueError(
            "Cannot store an acquisition currency without an acquisition price. "
            "Use --acquisition-price too, or omit --acquisition-currency."
        )
    if normalized_acquisition_price is not None and normalized_acquisition_price < 0:
        raise ValueError("--acquisition-price must be zero or greater.")
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
    # Re-adding the same logical row should accumulate tags instead of replacing
    # previously attached metadata from earlier imports or manual edits.
    existing_row = connection.execute(
        """
        SELECT
            id,
            quantity,
            tags_json,
            acquisition_price,
            acquisition_currency,
            notes
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
            normalized_condition,
            normalized_finish,
            normalized_language,
            normalized_location,
        ),
    ).fetchone()
    merged_tags = merge_tags(
        load_tags_json(existing_row["tags_json"]) if existing_row is not None else [],
        new_tags,
    )

    # The unique identity for an inventory row is printing plus
    # condition/finish/language/location. Matching rows roll quantity forward.
    if existing_row is not None:
        ensure_add_card_metadata_compatible(
            existing_row,
            incoming_notes=normalized_notes,
            incoming_acquisition_price=normalized_acquisition_price,
            incoming_acquisition_currency=normalized_acquisition_currency,
        )

        updated_quantity = int(existing_row["quantity"]) + quantity
        if before_write is not None:
            before_write()
        connection.execute(
            """
            UPDATE inventory_items
            SET quantity = ?, tags_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                updated_quantity,
                tags_to_json(merged_tags),
                existing_row["id"],
            ),
        )
        item_id = int(existing_row["id"])
        item_quantity = updated_quantity
    else:
        if before_write is not None:
            before_write()
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
            RETURNING id, quantity
            """,
            (
                inventory["id"],
                card["scryfall_id"],
                quantity,
                normalized_condition,
                normalized_finish,
                normalized_language,
                normalized_location,
                normalized_acquisition_price,
                normalized_acquisition_currency,
                normalized_notes,
                tags_to_json(merged_tags),
            ),
        )
        item_row = cursor.fetchone()
        item_id = int(item_row["id"])
        item_quantity = int(item_row["quantity"])

    return {
        "inventory": inventory["slug"],
        "card_name": card["name"],
        "set_code": card["set_code"],
        "set_name": card["set_name"],
        "collector_number": card["collector_number"],
        "scryfall_id": card["scryfall_id"],
        "item_id": item_id,
        "quantity": item_quantity,
        "finish": normalized_finish,
        "condition_code": normalized_condition,
        "language_code": normalized_language,
        "location": normalized_location,
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
    acquisition_price: Decimal | None,
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
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    clear: bool = False,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    require_database_file(db_path)
    if clear and (acquisition_price is not None or acquisition_currency is not None):
        raise ValueError("Use either --clear or --price / --currency, not both.")
    if not clear and acquisition_price is None and acquisition_currency is None:
        raise ValueError("Provide at least one of --price or --currency, or use --clear.")
    normalized_acquisition_price = coerce_decimal(acquisition_price)
    if normalized_acquisition_price is not None and normalized_acquisition_price < 0:
        raise ValueError("--price must be zero or greater.")

    initialize_database(db_path)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        current_currency = text_or_none(item["acquisition_currency"])
        new_price = None if clear else coerce_decimal(item["acquisition_price"])
        new_currency = None if clear else current_currency

        if normalized_acquisition_price is not None:
            new_price = normalized_acquisition_price
        if acquisition_currency is not None:
            new_currency = normalize_currency_code(acquisition_currency)

        if new_price is None and new_currency is not None:
            raise ValueError("Cannot store an acquisition currency without an acquisition price. Use --price too, or --clear.")

        if before_write is not None:
            before_write()
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
    result["old_acquisition_price"] = coerce_decimal(item["acquisition_price"])
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
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    require_database_file(db_path)
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
            # Changing an identity field can collapse two rows into one logical
            # bucket, so require an explicit merge opt-in before combining them.
            if not merge:
                raise ValueError(
                    "Changing location would collide with an existing inventory row. "
                    "Re-run with --merge to combine the rows, or resolve the duplicate row first."
                )
            if before_write is not None:
                before_write()
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                acquisition_preference=keep_acquisition,
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
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    require_database_file(db_path)
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
            # Condition changes can trigger the same row-collision behavior as
            # location edits, so the merge path is shared here too.
            if not merge:
                raise ValueError(
                    "Changing condition would collide with an existing inventory row. "
                    "Re-run with --merge to combine the rows, or resolve the duplicate row first."
                )
            if before_write is not None:
                before_write()
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                acquisition_preference=keep_acquisition,
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
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    require_database_file(db_path)
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

        if row_matches_identity(
            source_item,
            condition_code=target_condition,
            finish=target_finish,
            language_code=target_language,
            location=target_location,
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

        if target_item is not None:
            # Validate any acquisition conflict before touching quantities so a
            # failed merge request leaves both rows unchanged.
            resolve_merge_acquisition(
                source_item,
                target_item,
                acquisition_preference=keep_acquisition,
            )

        if before_write is not None:
            before_write()
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
            # Splitting into an existing compatible row should merge into that
            # destination instead of manufacturing a third duplicate row.
            result = merge_inventory_item_rows(
                connection,
                inventory_slug=inventory_slug,
                source_item=source_item,
                target_item=target_item,
                source_quantity=quantity,
                delete_source=False,
                acquisition_preference=keep_acquisition,
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
                    coerce_decimal(source_item["acquisition_price"]),
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
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    require_database_file(db_path)
    if source_item_id == target_item_id:
        raise ValueError("Choose two different item ids when using merge-rows.")

    initialize_database(db_path)
    with connect(db_path) as connection:
        source_item = get_inventory_item_row(connection, inventory_slug, source_item_id)
        target_item = get_inventory_item_row(connection, inventory_slug, target_item_id)

        if source_item["scryfall_id"] != target_item["scryfall_id"]:
            raise ValueError("merge-rows currently requires both rows to reference the same printing.")

        if before_write is not None:
            before_write()
        result = merge_inventory_item_rows(
            connection,
            inventory_slug=inventory_slug,
            source_item=source_item,
            target_item=target_item,
            acquisition_preference=keep_acquisition,
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
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    require_database_file(db_path)
    initialize_database(db_path)
    with connect(db_path) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        if before_write is not None:
            before_write()
        connection.execute(
            """
            DELETE FROM inventory_items
            WHERE id = ?
            """,
            (item_id,),
        )
        connection.commit()

    return inventory_item_result_from_row(item)
