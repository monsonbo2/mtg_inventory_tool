"""Inventory add-card operations."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ...db.connection import connect
from ...db.schema import require_current_schema
from ...errors import ConflictError, ValidationError
from ..audit import load_inventory_item_snapshot, write_inventory_audit_event
from ..catalog import determine_printing_selection_mode, resolve_card_row
from ..money import coerce_decimal
from ..normalize import (
    load_tags_json,
    merge_tags,
    normalize_condition_code,
    normalize_currency_code,
    normalize_external_id,
    normalize_finish,
    normalize_inventory_slug,
    normalize_language_code,
    parse_tags,
    tags_to_json,
    text_or_none,
    validate_supported_finish,
)
from ..policies import ensure_add_card_metadata_compatible, merge_printing_selection_mode
from ..query_inventory import get_inventory_item_row, get_or_create_inventory_row, inventory_item_result_from_row
from ..response_models import AddCardResult, inventory_item_response_kwargs

__all__ = ["add_card", "add_card_with_connection"]


def _build_add_card_result(payload: dict[str, Any]) -> AddCardResult:
    return AddCardResult(**inventory_item_response_kwargs(payload))


def _normalize_printing_selection_mode(mode: str | None) -> str | None:
    normalized = text_or_none(mode)
    if normalized is None:
        return None
    if normalized not in {"explicit", "defaulted"}:
        raise ValidationError("printing_selection_mode must be 'explicit' or 'defaulted'.")
    return normalized


def _prepared_db_path(db_path: str | Path) -> Path:
    return require_current_schema(db_path)


def _add_card_concurrent_collision_error() -> ConflictError:
    return ConflictError(
        "Adding card would collide with an existing inventory row due to a concurrent write. Retry the request."
    )


def add_card_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    inventory_display_name: str | None = None,
    scryfall_id: str | None,
    oracle_id: str | None = None,
    tcgplayer_product_id: str | None = None,
    name: str | None,
    set_code: str | None,
    set_name: str | None = None,
    collector_number: str | None,
    lang: str | None,
    quantity: int,
    condition_code: str,
    finish: str,
    language_code: str | None,
    location: str | None,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None = None,
    printing_selection_mode: str | None = None,
    resolved_card: sqlite3.Row | None = None,
    inventory_cache: dict[str, sqlite3.Row] | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> AddCardResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if quantity <= 0:
        raise ValidationError("--quantity must be a positive integer.")

    normalized_condition = normalize_condition_code(condition_code)
    normalized_finish = normalize_finish(finish)
    explicit_language = text_or_none(language_code)
    explicit_location = location is not None
    normalized_location = text_or_none(location) or ""
    normalized_acquisition_price = coerce_decimal(acquisition_price)
    normalized_acquisition_currency = normalize_currency_code(acquisition_currency)
    normalized_notes = text_or_none(notes)
    if normalized_acquisition_price is None and normalized_acquisition_currency is not None:
        raise ValidationError(
            "Cannot store an acquisition currency without an acquisition price. "
            "Use --acquisition-price too, or omit --acquisition-currency."
        )
    if normalized_acquisition_price is not None and normalized_acquisition_price < 0:
        raise ValidationError("--acquisition-price must be zero or greater.")
    if inventory_cache is None:
        inventory_cache = {}

    inventory = get_or_create_inventory_row(
        connection,
        inventory_slug,
        display_name=inventory_display_name,
        inventory_cache=inventory_cache,
        auto_create=inventory_display_name is not None,
    )
    if not explicit_location:
        normalized_location = text_or_none(inventory["default_location"]) or ""

    card = resolved_card
    if card is None:
        card = resolve_card_row(
            connection,
            scryfall_id=scryfall_id,
            oracle_id=oracle_id,
            tcgplayer_product_id=normalize_external_id(tcgplayer_product_id),
            name=name,
            set_code=set_code,
            set_name=set_name,
            collector_number=collector_number,
            lang=lang,
            finish=normalized_finish,
        )
    normalized_printing_selection_mode = _normalize_printing_selection_mode(printing_selection_mode)
    if normalized_printing_selection_mode is None:
        normalized_printing_selection_mode = determine_printing_selection_mode(
            connection,
            scryfall_id=scryfall_id,
            oracle_id=oracle_id,
            tcgplayer_product_id=normalize_external_id(tcgplayer_product_id),
            name=name,
            set_code=set_code,
            set_name=set_name,
            collector_number=collector_number,
            lang=lang,
            finish=normalized_finish,
        )
    validate_supported_finish(card["finishes_json"], normalized_finish)
    resolved_language = normalize_language_code(card["lang"])
    if explicit_language is None:
        normalized_language = resolved_language
    else:
        normalized_language = normalize_language_code(explicit_language)
        if normalized_language != resolved_language:
            raise ValidationError(
                "language_code must match the resolved printing language. "
                f"Printing language: {resolved_language}; requested language_code: {normalized_language}."
            )

    explicit_tags = tags is not None
    default_tags = parse_tags(inventory["default_tags"])
    if explicit_tags:
        requested_tags = parse_tags(tags)
        new_tags = requested_tags if text_or_none(tags) is None else merge_tags(default_tags, requested_tags)
    else:
        new_tags = default_tags
    existing_row = connection.execute(
        """
        SELECT
            id,
            quantity,
            tags_json,
            acquisition_price,
            acquisition_currency,
            notes,
            printing_selection_mode
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

    if existing_row is not None:
        before_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=int(existing_row["id"]),
        )
        ensure_add_card_metadata_compatible(
            existing_row,
            incoming_notes=normalized_notes,
            incoming_acquisition_price=normalized_acquisition_price,
            incoming_acquisition_currency=normalized_acquisition_currency,
        )

        updated_quantity = int(existing_row["quantity"]) + quantity
        updated_printing_selection_mode = merge_printing_selection_mode(
            str(existing_row["printing_selection_mode"]),
            normalized_printing_selection_mode,
        )
        if before_write is not None:
            before_write()
        connection.execute(
            """
            UPDATE inventory_items
            SET quantity = ?, tags_json = ?, printing_selection_mode = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                updated_quantity,
                tags_to_json(merged_tags),
                updated_printing_selection_mode,
                existing_row["id"],
            ),
        )
        item_id = int(existing_row["id"])
        after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
        )
        result_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="add_card",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={"mode": "increment"},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
    else:
        if before_write is not None:
            before_write()
        try:
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
                    normalized_printing_selection_mode,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise _add_card_concurrent_collision_error() from exc
        item_row = cursor.fetchone()
        item_id = int(item_row["id"])
        after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
        )
        result_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="add_card",
            item_id=item_id,
            before=None,
            after=after_snapshot,
            metadata={"mode": "create"},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
    return _build_add_card_result(inventory_item_result_from_row(result_row))


def add_card(
    db_path: str | Path,
    *,
    inventory_slug: str,
    inventory_display_name: str | None = None,
    scryfall_id: str | None,
    oracle_id: str | None = None,
    tcgplayer_product_id: str | None = None,
    name: str | None,
    set_code: str | None,
    set_name: str | None = None,
    collector_number: str | None,
    lang: str | None,
    quantity: int,
    condition_code: str,
    finish: str,
    language_code: str | None,
    location: str,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None = None,
    printing_selection_mode: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> AddCardResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        result = add_card_with_connection(
            connection,
            inventory_slug=inventory_slug,
            inventory_display_name=inventory_display_name,
            scryfall_id=scryfall_id,
            oracle_id=oracle_id,
            tcgplayer_product_id=tcgplayer_product_id,
            name=name,
            set_code=set_code,
            set_name=set_name,
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
            printing_selection_mode=printing_selection_mode,
            before_write=before_write,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()
    return result
