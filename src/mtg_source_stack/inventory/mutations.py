"""Inventory write operations and row-shaping mutations."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ConflictError, ValidationError
from .audit import load_inventory_item_snapshot, write_inventory_audit_event
from .catalog import determine_printing_selection_mode, resolve_card_row
from .money import coerce_decimal
from .normalize import (
    CANONICAL_FINISHES,
    load_tags_json,
    merge_tags,
    normalize_condition_code,
    normalize_currency_code,
    normalize_external_id,
    normalize_finish,
    normalize_inventory_slug,
    normalize_language_code,
    normalized_catalog_finish_list,
    parse_tags,
    tags_to_json,
    text_or_none,
    validate_supported_finish,
)
from .operations.bulk import bulk_mutate_inventory_items
from .policies import (
    ensure_add_card_metadata_compatible,
    merge_printing_selection_mode,
    resolve_merge_acquisition,
    row_matches_identity,
)
from .query_inventory import (
    find_inventory_item_collision,
    get_inventory_item_row,
    get_or_create_inventory_row,
    inventory_item_result_from_row,
    merge_inventory_item_rows,
)
from .response_models import (
    AddCardResult,
    MergeRowsResult,
    RemoveCardResult,
    SetAcquisitionResult,
    SetConditionResult,
    SetFinishResult,
    SetLocationResult,
    SetNotesResult,
    SetPrintingResult,
    SetQuantityResult,
    SetTagsResult,
    SplitRowResult,
    inventory_item_response_kwargs,
)


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


def _set_location_collision_error() -> ConflictError:
    return ConflictError(
        "Changing location would collide with an existing inventory row. "
        "Re-run with --merge to combine the rows, or resolve the duplicate row first."
    )


def _set_location_concurrent_merge_error() -> ConflictError:
    return ConflictError(
        "Changing location collided with another concurrent write while merging. Retry the request."
    )


def _set_condition_collision_error() -> ConflictError:
    return ConflictError(
        "Changing condition would collide with an existing inventory row. "
        "Re-run with --merge to combine the rows, or resolve the duplicate row first."
    )


def _set_condition_concurrent_merge_error() -> ConflictError:
    return ConflictError(
        "Changing condition collided with another concurrent write while merging. Retry the request."
    )


def _split_row_concurrent_collision_error() -> ConflictError:
    return ConflictError(
        "Splitting row would collide with an existing inventory row due to a concurrent write. Retry the request."
    )


def _set_finish_collision_error() -> ConflictError:
    return ConflictError(
        "Changing finish would collide with an existing inventory row. Resolve the duplicate row first."
    )


def _set_printing_collision_error() -> ConflictError:
    return ConflictError(
        "Changing printing would collide with an existing inventory row. "
        "Re-run with --merge to combine the rows, or resolve the duplicate row first."
    )


def _set_printing_concurrent_merge_error() -> ConflictError:
    return ConflictError(
        "Changing printing collided with another concurrent write while merging. Retry the request."
    )


def _complete_location_merge(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    normalized_location: str,
    keep_acquisition: str | None,
    before_snapshot: dict[str, Any],
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> SetLocationResult:
    result = merge_inventory_item_rows(
        connection,
        inventory_slug=inventory_slug,
        source_item=source_item,
        target_item=target_item,
        acquisition_preference=keep_acquisition,
    )
    result["old_location"] = source_item["location"]
    result["location"] = normalized_location
    after_snapshot = load_inventory_item_snapshot(
        connection,
        inventory_slug=inventory_slug,
        item_id=int(result["item_id"]),
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_location",
        item_id=int(source_item["item_id"]),
        before=before_snapshot,
        after=None,
        metadata={
            "merged": True,
            "target_item_id": int(result["item_id"]),
            "new_location": text_or_none(normalized_location),
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_location",
        item_id=int(result["item_id"]),
        before=inventory_item_result_from_row(target_item),
        after=after_snapshot,
        metadata={
            "merged": True,
            "source_item_id": int(source_item["item_id"]),
            "new_location": text_or_none(normalized_location),
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    connection.commit()
    return SetLocationResult(
        **inventory_item_response_kwargs(result),
        operation="set_location",
        old_location=text_or_none(source_item["location"]),
        merged=True,
        merged_source_item_id=int(result["merged_source_item_id"]),
    )


def _complete_condition_merge(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    normalized_condition: str,
    keep_acquisition: str | None,
    before_snapshot: dict[str, Any],
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> SetConditionResult:
    result = merge_inventory_item_rows(
        connection,
        inventory_slug=inventory_slug,
        source_item=source_item,
        target_item=target_item,
        acquisition_preference=keep_acquisition,
    )
    result["old_condition_code"] = source_item["condition_code"]
    result["condition_code"] = normalized_condition
    after_snapshot = load_inventory_item_snapshot(
        connection,
        inventory_slug=inventory_slug,
        item_id=int(result["item_id"]),
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_condition",
        item_id=int(source_item["item_id"]),
        before=before_snapshot,
        after=None,
        metadata={
            "merged": True,
            "target_item_id": int(result["item_id"]),
            "new_condition_code": normalized_condition,
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_condition",
        item_id=int(result["item_id"]),
        before=inventory_item_result_from_row(target_item),
        after=after_snapshot,
        metadata={
            "merged": True,
            "source_item_id": int(source_item["item_id"]),
            "new_condition_code": normalized_condition,
            "keep_acquisition": keep_acquisition,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    connection.commit()
    return SetConditionResult(
        **inventory_item_response_kwargs(result),
        operation="set_condition",
        old_condition_code=str(source_item["condition_code"]),
        merged=True,
        merged_source_item_id=int(result["merged_source_item_id"]),
    )


def _mutable_row_copy(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _resolve_printing_change_finish(
    *,
    target_card: sqlite3.Row,
    current_finish: str,
    requested_finish: str | None,
) -> tuple[str, bool]:
    if requested_finish is not None:
        normalized_finish = normalize_finish(requested_finish)
        validate_supported_finish(target_card["finishes_json"], normalized_finish)
        return normalized_finish, False

    available_finishes = normalized_catalog_finish_list(target_card["finishes_json"])
    if current_finish in available_finishes:
        return current_finish, False
    for candidate_finish in CANONICAL_FINISHES:
        if candidate_finish in available_finishes:
            return candidate_finish, True
    raise ValidationError(
        f"Target printing '{target_card['scryfall_id']}' does not expose any supported finishes."
    )


def _complete_printing_merge(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    before_snapshot: dict[str, Any],
    target_scryfall_id: str,
    target_finish: str,
    target_language_code: str,
    keep_acquisition: str | None,
    auto_selected_finish: bool,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
) -> SetPrintingResult:
    merge_source_item = _mutable_row_copy(source_item)
    merge_source_item["printing_selection_mode"] = "explicit"
    result = merge_inventory_item_rows(
        connection,
        inventory_slug=inventory_slug,
        source_item=merge_source_item,
        target_item=target_item,
        acquisition_preference=keep_acquisition,
    )
    after_snapshot = load_inventory_item_snapshot(
        connection,
        inventory_slug=inventory_slug,
        item_id=int(result["item_id"]),
    )
    metadata = {
        "merged": True,
        "new_scryfall_id": target_scryfall_id,
        "new_finish": target_finish,
        "new_language_code": target_language_code,
        "keep_acquisition": keep_acquisition,
        "auto_selected_finish": auto_selected_finish,
    }
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_printing",
        item_id=int(source_item["item_id"]),
        before=before_snapshot,
        after=None,
        metadata={
            **metadata,
            "target_item_id": int(result["item_id"]),
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_printing",
        item_id=int(result["item_id"]),
        before=inventory_item_result_from_row(target_item),
        after=after_snapshot,
        metadata={
            **metadata,
            "source_item_id": int(source_item["item_id"]),
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    connection.commit()
    return SetPrintingResult(
        **inventory_item_response_kwargs(result),
        operation="set_printing",
        old_scryfall_id=str(source_item["scryfall_id"]),
        old_finish=str(source_item["finish"]),
        old_language_code=str(source_item["language_code"]),
        merged=True,
        merged_source_item_id=int(result["merged_source_item_id"]),
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

    # The unique identity for an inventory row is printing plus
    # condition/finish/language/location. Matching rows roll quantity forward.
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
        item_quantity = updated_quantity
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
        item_quantity = int(item_row["quantity"])
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


def set_quantity(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    quantity: int,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetQuantityResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if quantity <= 0:
        raise ValidationError("--quantity must be a positive integer. Use remove-card to delete a row.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        connection.execute(
            """
            UPDATE inventory_items
            SET quantity = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (quantity, item_id),
        )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_quantity",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={"old_quantity": int(item["quantity"]), "new_quantity": quantity},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetQuantityResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_quantity",
        old_quantity=int(item["quantity"]),
    )


def set_acquisition(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    clear: bool = False,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetAcquisitionResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if clear and (acquisition_price is not None or acquisition_currency is not None):
        raise ValidationError("Use either --clear or --price / --currency, not both.")
    if not clear and acquisition_price is None and acquisition_currency is None:
        raise ValidationError("Provide at least one of --price or --currency, or use --clear.")
    normalized_acquisition_price = coerce_decimal(acquisition_price)
    if normalized_acquisition_price is not None and normalized_acquisition_price < 0:
        raise ValidationError("--price must be zero or greater.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        current_currency = text_or_none(item["acquisition_currency"])
        new_price = None if clear else coerce_decimal(item["acquisition_price"])
        new_currency = None if clear else current_currency

        if normalized_acquisition_price is not None:
            new_price = normalized_acquisition_price
        if acquisition_currency is not None:
            new_currency = normalize_currency_code(acquisition_currency)

        if new_price is None and new_currency is not None:
            raise ValidationError(
                "Cannot store an acquisition currency without an acquisition price. Use --price too, or --clear."
            )

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
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_acquisition",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={"clear": clear},
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetAcquisitionResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_acquisition",
        old_acquisition_price=coerce_decimal(item["acquisition_price"]),
        old_acquisition_currency=current_currency,
    )


def set_finish_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_id: int,
    finish: str,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetFinishResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    item = get_inventory_item_row(connection, inventory_slug, item_id)
    before_snapshot = inventory_item_result_from_row(item)
    normalized_finish = normalize_finish(finish)
    validate_supported_finish(item["finishes_json"], normalized_finish)
    if normalized_finish == item["finish"]:
        return SetFinishResult(
            **inventory_item_response_kwargs(before_snapshot),
            operation="set_finish",
            old_finish=str(item["finish"]),
        )

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
        raise _set_finish_collision_error() from exc

    after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
    after_row = get_inventory_item_row(connection, inventory_slug, item_id)
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_finish",
        item_id=item_id,
        before=before_snapshot,
        after=after_snapshot,
        metadata={"old_finish": item["finish"], "new_finish": normalized_finish},
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )

    return SetFinishResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_finish",
        old_finish=str(item["finish"]),
    )


def set_finish(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    finish: str,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetFinishResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        result = set_finish_with_connection(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
            finish=finish,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()
    return result


def set_printing_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    item_id: int,
    scryfall_id: str,
    finish: str | None = None,
    merge: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetPrintingResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    target_scryfall_id = text_or_none(scryfall_id)
    if target_scryfall_id is None:
        raise ValidationError("scryfall_id is required for set_printing.")
    if keep_acquisition not in (None, "source", "target"):
        raise ValidationError("keep_acquisition must be one of: source, target.")
    if not merge and keep_acquisition is not None:
        raise ValidationError("keep_acquisition only applies when merge is true for set_printing.")

    item = get_inventory_item_row(connection, inventory_slug, item_id)
    before_snapshot = inventory_item_result_from_row(item)
    target_card = resolve_card_row(
        connection,
        scryfall_id=target_scryfall_id,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        set_name=None,
        collector_number=None,
        lang=None,
        finish=None,
    )
    if str(target_card["oracle_id"]) != str(item["oracle_id"]):
        raise ValidationError("Target printing must belong to the same oracle card as the current inventory row.")

    target_finish, auto_selected_finish = _resolve_printing_change_finish(
        target_card=target_card,
        current_finish=str(item["finish"]),
        requested_finish=finish,
    )
    target_language_code = normalize_language_code(target_card["lang"])
    if target_scryfall_id == str(item["scryfall_id"]) and (
        target_finish != str(item["finish"])
        or target_language_code != str(item["language_code"])
    ):
        raise ValidationError(
            "set_printing only supports confirming the current printing when finish and language stay unchanged. "
            "Use the generic item PATCH route for finish changes."
        )
    mode_only_update = (
        target_scryfall_id == str(item["scryfall_id"])
        and target_finish == str(item["finish"])
        and target_language_code == str(item["language_code"])
    )
    if mode_only_update and str(item["printing_selection_mode"]) == "explicit":
        return SetPrintingResult(
            **inventory_item_response_kwargs(before_snapshot),
            operation="set_printing",
            old_scryfall_id=str(item["scryfall_id"]),
            old_finish=str(item["finish"]),
            old_language_code=str(item["language_code"]),
            merged=False,
        )

    collision = find_inventory_item_collision(
        connection,
        inventory_id=int(item["inventory_id"]),
        scryfall_id=target_scryfall_id,
        condition_code=str(item["condition_code"]),
        finish=target_finish,
        language_code=target_language_code,
        location=str(item["location"]),
        exclude_item_id=item_id,
    )
    if collision is not None:
        if not merge:
            raise _set_printing_collision_error()
        if before_write is not None:
            before_write()
        return _complete_printing_merge(
            connection,
            inventory_slug=inventory_slug,
            source_item=item,
            target_item=collision,
            before_snapshot=before_snapshot,
            target_scryfall_id=target_scryfall_id,
            target_finish=target_finish,
            target_language_code=target_language_code,
            keep_acquisition=keep_acquisition,
            auto_selected_finish=auto_selected_finish,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )

    if before_write is not None:
        before_write()
    try:
        connection.execute(
            """
            UPDATE inventory_items
            SET
                scryfall_id = ?,
                finish = ?,
                language_code = ?,
                printing_selection_mode = 'explicit',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (target_scryfall_id, target_finish, target_language_code, item_id),
        )
    except sqlite3.IntegrityError as exc:
        if not merge:
            raise _set_printing_collision_error() from exc
        collision = find_inventory_item_collision(
            connection,
            inventory_id=int(item["inventory_id"]),
            scryfall_id=target_scryfall_id,
            condition_code=str(item["condition_code"]),
            finish=target_finish,
            language_code=target_language_code,
            location=str(item["location"]),
            exclude_item_id=item_id,
        )
        if collision is None:
            raise _set_printing_concurrent_merge_error() from exc
        return _complete_printing_merge(
            connection,
            inventory_slug=inventory_slug,
            source_item=item,
            target_item=collision,
            before_snapshot=before_snapshot,
            target_scryfall_id=target_scryfall_id,
            target_finish=target_finish,
            target_language_code=target_language_code,
            keep_acquisition=keep_acquisition,
            auto_selected_finish=auto_selected_finish,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )

    after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
    after_row = get_inventory_item_row(connection, inventory_slug, item_id)
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action="set_printing",
        item_id=item_id,
        before=before_snapshot,
        after=after_snapshot,
        metadata={
            "merged": False,
            "old_scryfall_id": str(item["scryfall_id"]),
            "new_scryfall_id": target_scryfall_id,
            "old_finish": str(item["finish"]),
            "new_finish": target_finish,
            "old_language_code": str(item["language_code"]),
            "new_language_code": target_language_code,
            "auto_selected_finish": auto_selected_finish,
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return SetPrintingResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_printing",
        old_scryfall_id=str(item["scryfall_id"]),
        old_finish=str(item["finish"]),
        old_language_code=str(item["language_code"]),
        merged=False,
    )


def set_printing(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    scryfall_id: str,
    finish: str | None = None,
    merge: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetPrintingResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        result = set_printing_with_connection(
            connection,
            inventory_slug=inventory_slug,
            item_id=item_id,
            scryfall_id=scryfall_id,
            finish=finish,
            merge=merge,
            keep_acquisition=keep_acquisition,
            before_write=before_write,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
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
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetLocationResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_location = text_or_none(location) or ""
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if normalized_location == item["location"]:
            return SetLocationResult(
                **inventory_item_response_kwargs(before_snapshot),
                operation="set_location",
                old_location=text_or_none(item["location"]),
                merged=False,
            )

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
                raise _set_location_collision_error()
            if before_write is not None:
                before_write()
            return _complete_location_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_location=normalized_location,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )

        if before_write is not None:
            before_write()
        try:
            connection.execute(
                """
                UPDATE inventory_items
                SET location = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_location, item_id),
            )
        except sqlite3.IntegrityError as exc:
            if not merge:
                raise _set_location_collision_error() from exc
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
            if collision is None:
                raise _set_location_concurrent_merge_error() from exc
            return _complete_location_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_location=normalized_location,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_location",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={
                "merged": False,
                "old_location": text_or_none(item["location"]),
                "new_location": text_or_none(normalized_location),
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetLocationResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_location",
        old_location=text_or_none(item["location"]),
        merged=False,
    )


def set_condition(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    condition_code: str,
    merge: bool = False,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetConditionResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_condition = normalize_condition_code(condition_code)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if normalized_condition == item["condition_code"]:
            return SetConditionResult(
                **inventory_item_response_kwargs(before_snapshot),
                operation="set_condition",
                old_condition_code=str(item["condition_code"]),
                merged=False,
            )

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
                raise _set_condition_collision_error()
            if before_write is not None:
                before_write()
            return _complete_condition_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_condition=normalized_condition,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )

        if before_write is not None:
            before_write()
        try:
            connection.execute(
                """
                UPDATE inventory_items
                SET condition_code = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (normalized_condition, item_id),
            )
        except sqlite3.IntegrityError as exc:
            if not merge:
                raise _set_condition_collision_error() from exc
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
            if collision is None:
                raise _set_condition_concurrent_merge_error() from exc
            return _complete_condition_merge(
                connection,
                inventory_slug=inventory_slug,
                source_item=item,
                target_item=collision,
                normalized_condition=normalized_condition,
                keep_acquisition=keep_acquisition,
                before_snapshot=before_snapshot,
                actor_type=actor_type,
                actor_id=actor_id,
                request_id=request_id,
            )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_condition",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            metadata={
                "merged": False,
                "old_condition_code": item["condition_code"],
                "new_condition_code": normalized_condition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetConditionResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_condition",
        old_condition_code=str(item["condition_code"]),
        merged=False,
    )


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
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SplitRowResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if quantity <= 0:
        raise ValidationError("--quantity must be a positive integer.")
    if clear_location and location is not None:
        raise ValidationError("Use either --location or --clear-location, not both.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        source_item = get_inventory_item_row(connection, inventory_slug, item_id)
        source_before_snapshot = inventory_item_result_from_row(source_item)
        source_quantity = int(source_item["quantity"])
        if quantity > source_quantity:
            raise ValidationError("--quantity cannot exceed the current row quantity.")

        target_condition = normalize_condition_code(condition_code) if condition_code is not None else source_item["condition_code"]
        target_finish = normalize_finish(finish) if finish is not None else source_item["finish"]
        target_language = normalize_language_code(language_code) if language_code is not None else source_item["language_code"]
        validate_supported_finish(source_item["finishes_json"], target_finish)
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
            raise ValidationError(
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
            target_before_snapshot = inventory_item_result_from_row(target_item)
        else:
            target_before_snapshot = None

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
            target_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=int(result["item_id"]),
            )
        else:
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
                        source_item["printing_selection_mode"],
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise _split_row_concurrent_collision_error() from exc
            new_item_id = cursor.fetchone()["id"]
            new_item_row = get_inventory_item_row(connection, inventory_slug, new_item_id)
            result = inventory_item_result_from_row(new_item_row)
            result["merged_into_existing"] = False
            target_after_snapshot = inventory_item_result_from_row(new_item_row)

        if source_deleted:
            source_after_snapshot = None
        else:
            source_after_snapshot = load_inventory_item_snapshot(
                connection,
                inventory_slug=inventory_slug,
                item_id=item_id,
            )

        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="split_row",
            item_id=item_id,
            before=source_before_snapshot,
            after=source_after_snapshot,
            metadata={
                "role": "source",
                "moved_quantity": quantity,
                "source_deleted": source_deleted,
                "target_item_id": int(result["item_id"]),
                "merged_into_existing": bool(result["merged_into_existing"]),
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="split_row",
            item_id=int(result["item_id"]),
            before=target_before_snapshot,
            after=target_after_snapshot,
            metadata={
                "role": "target",
                "source_item_id": item_id,
                "moved_quantity": quantity,
                "merged_into_existing": bool(result["merged_into_existing"]),
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )

        connection.commit()

    return SplitRowResult(
        **inventory_item_response_kwargs(result),
        merged_into_existing=bool(result["merged_into_existing"]),
        source_item_id=item_id,
        source_old_quantity=source_quantity,
        source_quantity=remaining_quantity,
        source_deleted=source_deleted,
        moved_quantity=quantity,
    )


def set_notes(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    notes: str | None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetNotesResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    normalized_notes = text_or_none(notes)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        connection.execute(
            """
            UPDATE inventory_items
            SET notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (normalized_notes, item_id),
        )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_notes",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetNotesResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_notes",
        old_notes=text_or_none(item["notes"]),
    )


def set_tags(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    tags: str | None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> SetTagsResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        normalized_tags = parse_tags(tags)
        connection.execute(
            """
            UPDATE inventory_items
            SET tags_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (tags_to_json(normalized_tags), item_id),
        )
        after_snapshot = load_inventory_item_snapshot(connection, inventory_slug=inventory_slug, item_id=item_id)
        after_row = get_inventory_item_row(connection, inventory_slug, item_id)
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="set_tags",
            item_id=item_id,
            before=before_snapshot,
            after=after_snapshot,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return SetTagsResult(
        **inventory_item_response_kwargs(inventory_item_result_from_row(after_row)),
        operation="set_tags",
        old_tags=list(before_snapshot["tags"]),
    )


def merge_rows(
    db_path: str | Path,
    *,
    inventory_slug: str,
    source_item_id: int,
    target_item_id: int,
    keep_acquisition: str | None = None,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> MergeRowsResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if source_item_id == target_item_id:
        raise ValidationError("Choose two different item ids when using merge-rows.")

    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        source_item = get_inventory_item_row(connection, inventory_slug, source_item_id)
        target_item = get_inventory_item_row(connection, inventory_slug, target_item_id)
        source_before_snapshot = inventory_item_result_from_row(source_item)
        target_before_snapshot = inventory_item_result_from_row(target_item)

        if source_item["scryfall_id"] != target_item["scryfall_id"]:
            raise ValidationError("merge-rows currently requires both rows to reference the same printing.")

        if before_write is not None:
            before_write()
        result = merge_inventory_item_rows(
            connection,
            inventory_slug=inventory_slug,
            source_item=source_item,
            target_item=target_item,
            acquisition_preference=keep_acquisition,
        )
        target_after_snapshot = load_inventory_item_snapshot(
            connection,
            inventory_slug=inventory_slug,
            item_id=target_item_id,
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="merge_rows",
            item_id=source_item_id,
            before=source_before_snapshot,
            after=None,
            metadata={
                "role": "source",
                "target_item_id": target_item_id,
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="merge_rows",
            item_id=target_item_id,
            before=target_before_snapshot,
            after=target_after_snapshot,
            metadata={
                "role": "target",
                "source_item_id": source_item_id,
                "keep_acquisition": keep_acquisition,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return MergeRowsResult(
        **inventory_item_response_kwargs(result),
        merged_source_item_id=int(result["merged_source_item_id"]),
        source_quantity=int(source_item["quantity"]),
        target_old_quantity=int(target_item["quantity"]),
    )


def remove_card(
    db_path: str | Path,
    *,
    inventory_slug: str,
    item_id: int,
    before_write: Callable[[], Any] | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> RemoveCardResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    db_file = _prepared_db_path(db_path)
    with connect(db_file) as connection:
        item = get_inventory_item_row(connection, inventory_slug, item_id)
        before_snapshot = inventory_item_result_from_row(item)
        if before_write is not None:
            before_write()
        connection.execute(
            """
            DELETE FROM inventory_items
            WHERE id = ?
            """,
            (item_id,),
        )
        write_inventory_audit_event(
            connection,
            inventory_slug=inventory_slug,
            action="remove_card",
            item_id=item_id,
            before=before_snapshot,
            after=None,
            actor_type=actor_type,
            actor_id=actor_id,
            request_id=request_id,
        )
        connection.commit()

    return RemoveCardResult(**inventory_item_response_kwargs(before_snapshot))
