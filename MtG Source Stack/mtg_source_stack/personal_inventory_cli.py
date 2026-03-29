from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .mvp_importer import DEFAULT_DB_PATH, connect, create_database_snapshot, initialize_database


DEFAULT_PROVIDER = "tcgplayer"
CSV_PREVIEW_LIMIT = 25
DEFAULT_HEALTH_STALE_DAYS = 30
HEALTH_PREVIEW_LIMIT = 10
MERGED_ACQUISITION_NOTE_MARKER = "Merged source acquisition from item "
CSV_HEADER_ALIASES = {
    "inventory_slug": "inventory",
    "inventoryname": "inventory",
    "inventoryslug": "inventory",
    "collection_name": "inventory_name",
    "collection": "inventory_name",
    "created_at": "source_created_at",
    "product_id": "tcgplayer_product_id",
    "tcgplayer_id": "tcgplayer_product_id",
    "tcgplayer_product_id": "tcgplayer_product_id",
    "scryfallid": "scryfall_id",
    "card_name": "name",
    "cardname": "name",
    "product_name": "name",
    "set": "set_code",
    "setcode": "set_code",
    "set_name": "set_name",
    "collector_no": "collector_number",
    "collectornumber": "collector_number",
    "number": "collector_number",
    "printing_lang": "lang",
    "qty": "quantity",
    "condition_code": "condition",
    "cond": "condition",
    "language": "language_code",
    "languagecode": "language_code",
    "owned_language": "language_code",
    "variant": "variant",
    "total_quantity": "total_quantity",
    "add_to_quantity": "add_to_quantity",
    "tcg_marketplace_price": "marketplace_price",
    "tcg_market_price": "market_price",
    "acquisitionprice": "acquisition_price",
    "purchase_price": "acquisition_price",
    "acquisitioncurrency": "acquisition_currency",
    "currency": "acquisition_currency",
    "tag": "tags",
}


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = text_or_none(value)
        if text is not None:
            return text
    return None


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def slugify_inventory_name(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "inventory"


def normalize_condition_code(value: str | None) -> str:
    text = text_or_none(value)
    if text is None:
        return "NM"

    normalized = text.strip().lower()
    for suffix in (" etched foil", " foil", " etched"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()

    mapping = {
        "m": "M",
        "mint": "M",
        "nm": "NM",
        "near mint": "NM",
        "near-mint": "NM",
        "lp": "LP",
        "lightly played": "LP",
        "light-played": "LP",
        "slightly played": "LP",
        "sp": "LP",
        "mp": "MP",
        "moderately played": "MP",
        "moderately-played": "MP",
        "hp": "HP",
        "heavily played": "HP",
        "heavily-played": "HP",
        "dmg": "DMG",
        "damaged": "DMG",
    }
    return mapping.get(normalized, text.upper())


def normalize_language_code(value: str | None) -> str:
    text = text_or_none(value)
    if text is None:
        return "en"

    normalized = text.strip().lower()
    mapping = {
        "english": "en",
        "en": "en",
        "japanese": "ja",
        "ja": "ja",
        "german": "de",
        "de": "de",
        "french": "fr",
        "fr": "fr",
        "italian": "it",
        "it": "it",
        "spanish": "es",
        "es": "es",
        "portuguese": "pt",
        "pt": "pt",
        "russian": "ru",
        "ru": "ru",
        "korean": "ko",
        "ko": "ko",
        "simplified chinese": "zhs",
        "zhs": "zhs",
        "traditional chinese": "zht",
        "zht": "zht",
        "phyrexian": "ph",
        "ph": "ph",
    }
    return mapping.get(normalized, normalized)


def normalize_currency_code(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None
    return text.upper()


def normalize_external_id(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def parse_int_value(value: str | None, *, row_number: int, field_name: str) -> int | None:
    text = text_or_none(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"CSV row {row_number}: {field_name} must be an integer.") from exc


def resolve_csv_quantity(row: dict[str, str | None], *, row_number: int) -> int | None:
    direct_quantity = parse_int_value(row.get("quantity"), row_number=row_number, field_name="quantity")
    if direct_quantity is not None:
        if direct_quantity <= 0:
            raise ValueError(f"CSV row {row_number}: quantity must be a positive integer.")
        return direct_quantity

    total_quantity = parse_int_value(row.get("total_quantity"), row_number=row_number, field_name="total_quantity")
    add_to_quantity = parse_int_value(
        row.get("add_to_quantity"),
        row_number=row_number,
        field_name="add_to_quantity",
    )
    if total_quantity is not None or add_to_quantity is not None:
        computed = max(0, (total_quantity or 0) + (add_to_quantity or 0))
        if computed == 0:
            return None
        return computed

    return 1


def finish_from_variant(variant: str | None, finish: str | None) -> str:
    explicit_finish = text_or_none(finish)
    if explicit_finish is not None:
        return explicit_finish

    variant_text = text_or_none(variant)
    if variant_text is None:
        return "normal"

    lowered = variant_text.lower()
    if "etched" in lowered:
        return "etched"
    if "foil" in lowered:
        return "foil"
    return "normal"


def finish_and_source_from_row(row: dict[str, str | None]) -> tuple[str, str]:
    explicit = text_or_none(row.get("finish"))
    if explicit is not None:
        return explicit, "finish"

    from_variant = finish_from_variant(row.get("variant"), None)
    if from_variant != "normal":
        return from_variant, "variant"

    condition_text = text_or_none(row.get("condition"))
    if condition_text is not None:
        lowered = condition_text.lower()
        if "etched" in lowered:
            return "etched", "condition"
        if "foil" in lowered:
            return "foil", "condition"

    return "normal", "default"


def finish_from_row(row: dict[str, str | None]) -> str:
    finish, _ = finish_and_source_from_row(row)
    return finish


def normalize_finish(value: str | None) -> str:
    normalized = (value or "normal").strip().lower()
    mapping = {
        "normal": "normal",
        "nonfoil": "normal",
        "foil": "foil",
        "etched": "etched",
    }
    if normalized not in mapping:
        raise ValueError("Finish must be one of: normal, nonfoil, foil, etched.")
    return mapping[normalized]


def parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def normalize_tag(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None
    normalized = " ".join(text.split()).lower()
    return normalized or None


def normalize_tags(values: list[str]) -> list[str]:
    normalized_tags: list[str] = []
    for value in values:
        normalized = normalize_tag(value)
        if normalized is not None and normalized not in normalized_tags:
            normalized_tags.append(normalized)
    return normalized_tags


def parse_tags(value: str | None) -> list[str]:
    text = text_or_none(value)
    if text is None:
        return []
    return normalize_tags(text.split(","))


def load_tags_json(value: str | None) -> list[str]:
    return normalize_tags(parse_json_list(value))


def merge_tags(existing_tags: list[str], new_tags: list[str]) -> list[str]:
    return normalize_tags([*existing_tags, *new_tags])


def tags_to_json(tags: list[str]) -> str:
    return compact_json(normalize_tags(tags))


def format_tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else "(none)"


def format_finishes(finishes: list[str]) -> str:
    return ", ".join(finishes) if finishes else "(none)"


def format_optional_text(value: str | None) -> str:
    text = text_or_none(value)
    return text if text is not None else "(none)"


def format_acquisition_text(price: Any, currency: Any) -> str:
    return format_optional_text(format_acquisition_summary(price, currency))


def format_decimal(value: Any) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def format_acquisition_summary(price: Any, currency: Any) -> str | None:
    if price is None:
        return None
    price_text = format_decimal(price)
    currency_text = text_or_none(currency)
    return f"{price_text} {currency_text}".strip() if currency_text else price_text


def merge_note_text(
    *,
    target_notes: str | None,
    source_notes: str | None,
    source_item_id: int,
    target_acquisition_summary: str | None,
    source_acquisition_summary: str | None,
) -> str | None:
    merged_parts: list[str] = []
    for note in (text_or_none(target_notes), text_or_none(source_notes)):
        if note is not None and note not in merged_parts:
            merged_parts.append(note)

    if (
        source_acquisition_summary is not None
        and target_acquisition_summary is not None
        and source_acquisition_summary != target_acquisition_summary
    ):
        merged_parts.append(
            f"Merged source acquisition from item {source_item_id}: {source_acquisition_summary}"
        )

    if not merged_parts:
        return None
    return "\n\n".join(merged_parts)


def parse_tag_filters(values: list[str] | None) -> list[str]:
    if not values:
        return []
    parsed: list[str] = []
    for value in values:
        parsed.extend(parse_tags(value))
    return normalize_tags(parsed)


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


def normalize_catalog_finishes(raw_finishes: str | None) -> str:
    return ",".join(normalized_catalog_finish_list(raw_finishes))


def normalized_catalog_finish_list(raw_finishes: str | None) -> list[str]:
    finishes: list[str] = []
    for finish in parse_json_list(raw_finishes):
        normalized = normalize_finish(finish)
        if normalized not in finishes:
            finishes.append(normalized)
    return finishes


def truncate(value: Any, max_len: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_add_card_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Added to inventory",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Quantity now: {result['quantity']}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {result['location'] or '(none)'}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
        f"Item ID: {result['item_id']}",
    ]
    return "\n".join(lines)


def format_set_quantity_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Updated inventory quantity",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Previous quantity: {result['old_quantity']}",
        f"Quantity now: {result['quantity']}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Notes: {format_optional_text(result['notes'])}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
        f"Item ID: {result['item_id']}",
    ]
    return "\n".join(lines)


def format_remove_card_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Removed from inventory",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Removed quantity: {result['quantity']}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Notes: {format_optional_text(result['notes'])}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
        f"Item ID: {result['item_id']}",
    ]
    return "\n".join(lines)


def format_set_tags_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Updated card tags",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Previous tags: {format_tags(result['old_tags'])}",
        f"Tags now: {format_tags(result['tags'])}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Notes: {format_optional_text(result['notes'])}",
        f"Inventory: {result['inventory']}",
        f"Item ID: {result['item_id']}",
    ]
    return "\n".join(lines)


def format_set_finish_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Updated card finish",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Previous finish: {result['old_finish']}",
        f"Finish now: {result['finish']}",
        f"Condition: {result['condition_code']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Notes: {format_optional_text(result['notes'])}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
        f"Item ID: {result['item_id']}",
    ]
    return "\n".join(lines)


def format_set_location_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Updated card location",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Previous location: {format_optional_text(result['old_location'])}",
        f"Location now: {format_optional_text(result['location'])}",
    ]
    if result.get("merged"):
        lines.extend(
            [
                "Merge applied: yes",
                f"Merged source item ID: {result['merged_source_item_id']}",
                f"Active item ID: {result['item_id']}",
                f"Quantity now: {result['quantity']}",
            ]
        )
    lines.extend(
        [
            f"Condition: {result['condition_code']}",
            f"Finish: {result['finish']}",
            f"Language: {result['language_code']}",
            f"Notes: {format_optional_text(result['notes'])}",
            f"Tags: {format_tags(result['tags'])}",
            f"Inventory: {result['inventory']}",
            f"Item ID: {result['item_id']}",
        ]
    )
    return "\n".join(lines)


def format_set_condition_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Updated card condition",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Previous condition: {result['old_condition_code']}",
        f"Condition now: {result['condition_code']}",
    ]
    if result.get("merged"):
        lines.extend(
            [
                "Merge applied: yes",
                f"Merged source item ID: {result['merged_source_item_id']}",
                f"Active item ID: {result['item_id']}",
                f"Quantity now: {result['quantity']}",
            ]
        )
    lines.extend(
        [
            f"Finish: {result['finish']}",
            f"Language: {result['language_code']}",
            f"Location: {format_optional_text(result['location'])}",
            f"Notes: {format_optional_text(result['notes'])}",
            f"Tags: {format_tags(result['tags'])}",
            f"Inventory: {result['inventory']}",
            f"Item ID: {result['item_id']}",
        ]
    )
    return "\n".join(lines)


def format_set_notes_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Updated card notes",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Previous notes: {format_optional_text(result['old_notes'])}",
        f"Notes now: {format_optional_text(result['notes'])}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
        f"Item ID: {result['item_id']}",
    ]
    return "\n".join(lines)


def format_set_acquisition_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Updated card acquisition",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Previous acquisition: {format_acquisition_text(result['old_acquisition_price'], result['old_acquisition_currency'])}",
        f"Acquisition now: {format_acquisition_text(result['acquisition_price'], result['acquisition_currency'])}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Notes: {format_optional_text(result['notes'])}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
        f"Item ID: {result['item_id']}",
    ]
    return "\n".join(lines)


def format_split_row_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Split inventory row",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Moved quantity: {result['moved_quantity']}",
        f"Source item ID: {result['source_item_id']}",
        f"Source previous quantity: {result['source_old_quantity']}",
        f"Source quantity now: {result['source_quantity']}",
        f"Source row removed: {'yes' if result['source_deleted'] else 'no'}",
        f"Target item ID: {result['item_id']}",
        f"Target quantity now: {result['quantity']}",
        f"Merged into existing row: {'yes' if result['merged_into_existing'] else 'no'}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Acquisition: {format_acquisition_text(result['acquisition_price'], result['acquisition_currency'])}",
        f"Notes: {format_optional_text(result['notes'])}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
    ]
    return "\n".join(lines)


def format_merge_rows_result(result: dict[str, Any]) -> str:
    printing = f"{result['set_name']} ({str(result['set_code']).upper()} #{result['collector_number']})"
    lines = [
        "Merged inventory rows",
        "",
        f"Card: {result['card_name']}",
        f"Printing: {printing}",
        f"Source item ID: {result['merged_source_item_id']}",
        f"Source quantity removed: {result['source_quantity']}",
        f"Target item ID: {result['item_id']}",
        f"Target previous quantity: {result['target_old_quantity']}",
        f"Quantity now: {result['quantity']}",
        f"Condition: {result['condition_code']}",
        f"Finish: {result['finish']}",
        f"Language: {result['language_code']}",
        f"Location: {format_optional_text(result['location'])}",
        f"Acquisition: {format_acquisition_text(result['acquisition_price'], result['acquisition_currency'])}",
        f"Notes: {format_optional_text(result['notes'])}",
        f"Tags: {format_tags(result['tags'])}",
        f"Inventory: {result['inventory']}",
    ]
    return "\n".join(lines)


def format_import_csv_result(result: dict[str, Any]) -> str:
    lines = [
        "Imported inventory rows from CSV",
        "",
        f"File: {result['csv_path']}",
        f"Rows seen: {result['rows_seen']}",
        f"Rows imported: {result['rows_written']}",
    ]

    if result.get("dry_run"):
        lines.append("Mode: dry run (no changes saved)")

    default_inventory = result.get("default_inventory")
    if default_inventory:
        lines.append(f"Default inventory: {default_inventory}")

    lines.append(f"Finish adjustments: {result.get('finish_adjustment_count', 0)}")

    preview_rows = []
    for row in result["imported_rows"][:CSV_PREVIEW_LIMIT]:
        preview_rows.append(
            {
                "csv_row": row["csv_row"],
                "inventory": row["inventory"],
                "name": truncate(row["card_name"], 28),
                "set": row["set_code"],
                "number": row["collector_number"],
                "qty": row["quantity"],
                "finish": row["finish"],
                "tags": truncate(format_tags(row["tags"]), 24),
                "item_id": row["item_id"],
            }
        )

    if preview_rows:
        lines.extend(
            [
                "",
                "Imported rows",
                "",
                render_table(
                    preview_rows,
                    [
                        ("csv_row", "csv_row"),
                        ("inventory", "inventory"),
                        ("name", "name"),
                        ("set", "set"),
                        ("number", "number"),
                        ("qty", "qty"),
                        ("finish", "finish"),
                        ("tags", "tags"),
                        ("item_id", "item_id"),
                    ],
                ),
            ]
        )

        remaining_rows = result["rows_written"] - len(preview_rows)
        if remaining_rows > 0:
            lines.append(f"... {remaining_rows} more imported row(s) not shown.")

    adjustment_rows = []
    for row in result.get("finish_adjustments", [])[:CSV_PREVIEW_LIMIT]:
        adjustment_rows.append(
            {
                "csv_row": row["csv_row"],
                "inventory": row["inventory"],
                "name": truncate(row["card_name"], 28),
                "set": row["set_code"],
                "number": row["collector_number"],
                "from": row["old_finish"],
                "to": row["new_finish"],
                "reason": truncate(row["reason"], 24),
            }
        )

    if adjustment_rows:
        lines.extend(
            [
                "",
                "Automatic finish adjustments",
                "",
                render_table(
                    adjustment_rows,
                    [
                        ("csv_row", "csv_row"),
                        ("inventory", "inventory"),
                        ("name", "name"),
                        ("set", "set"),
                        ("number", "number"),
                        ("from", "from"),
                        ("to", "to"),
                        ("reason", "reason"),
                    ],
                ),
            ]
        )

        remaining_adjustments = result["finish_adjustment_count"] - len(adjustment_rows)
        if remaining_adjustments > 0:
            lines.append(f"... {remaining_adjustments} more finish adjustment(s) not shown.")

    return "\n".join(lines)


def render_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "No rows found."

    widths: list[int] = []
    for key, label in columns:
        width = len(label)
        for row in rows:
            width = max(width, len(str(row.get(key, ""))))
        widths.append(width)

    header = "  ".join(label.ljust(width) for (_, label), width in zip(columns, widths))
    separator = "  ".join("-" * width for width in widths)
    lines = [header, separator]
    for row in rows:
        line = "  ".join(str(row.get(key, "")).ljust(width) for (key, _), width in zip(columns, widths))
        lines.append(line)
    return "\n".join(lines)


def print_table(rows: list[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    print(render_table(rows, columns))


def append_snapshot_notice(text: str, snapshot: dict[str, Any] | None) -> str:
    if snapshot is None:
        return text
    return (
        f"{text}\n\n"
        "Safety snapshot created\n\n"
        f"Snapshot: {snapshot['snapshot_path']}\n"
        f"Label: {snapshot['label']}"
    )


def write_report(path: str | Path, text: str) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return report_path


def write_json_report(path: str | Path, payload: dict[str, Any]) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return report_path


def write_rows_csv(path: str | Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return report_path


def flatten_import_csv_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    adjustment_by_row = {
        row["csv_row"]: row
        for row in result.get("finish_adjustments", [])
    }
    flattened: list[dict[str, Any]] = []
    for row in result.get("imported_rows", []):
        adjustment = adjustment_by_row.get(row["csv_row"])
        flattened.append(
            {
                "csv_path": result["csv_path"],
                "dry_run": result.get("dry_run", False),
                "default_inventory": result.get("default_inventory") or "",
                "csv_row": row["csv_row"],
                "inventory": row["inventory"],
                "card_name": row["card_name"],
                "set_code": row["set_code"],
                "set_name": row["set_name"],
                "collector_number": row["collector_number"],
                "quantity": row["quantity"],
                "finish": row["finish"],
                "condition_code": row["condition_code"],
                "language_code": row["language_code"],
                "location": row["location"],
                "tags": format_tags(row["tags"]),
                "item_id": row["item_id"],
                "scryfall_id": row["scryfall_id"],
                "finish_adjusted": adjustment is not None,
                "old_finish": adjustment["old_finish"] if adjustment is not None else "",
                "new_finish": adjustment["new_finish"] if adjustment is not None else "",
                "adjustment_reason": adjustment["reason"] if adjustment is not None else "",
            }
        )
    return flattened


def write_csv_report(path: str | Path, result: dict[str, Any]) -> Path:
    report_path = Path(path)
    rows = flatten_import_csv_rows(result)
    fieldnames = [
        "csv_path",
        "dry_run",
        "default_inventory",
        "csv_row",
        "inventory",
        "card_name",
        "set_code",
        "set_name",
        "collector_number",
        "quantity",
        "finish",
        "condition_code",
        "language_code",
        "location",
        "tags",
        "item_id",
        "scryfall_id",
        "finish_adjusted",
        "old_finish",
        "new_finish",
        "adjustment_reason",
    ]
    return write_rows_csv(report_path, rows, fieldnames)


def coerce_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def flatten_owned_export_rows(
    rows: list[dict[str, Any]],
    *,
    inventory_slug: str,
    provider: str,
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for row in rows:
        flattened.append(
            {
                "inventory": inventory_slug,
                "provider": provider,
                "item_id": row["item_id"],
                "scryfall_id": row["scryfall_id"],
                "card_name": row["name"],
                "set_code": row["set_code"],
                "set_name": row["set_name"],
                "collector_number": row["collector_number"],
                "rarity": row["rarity"],
                "quantity": row["quantity"],
                "condition_code": row["condition_code"],
                "finish": row["finish"],
                "language_code": row["language_code"],
                "location": text_or_none(row["location"]) or "",
                "tags": format_tags(load_tags_json(row["tags_json"])),
                "notes": text_or_none(row["notes"]) or "",
                "acquisition_price": row["acquisition_price"] if row["acquisition_price"] is not None else "",
                "acquisition_currency": text_or_none(row["acquisition_currency"]) or "",
                "unit_price": row["unit_price"],
                "price_currency": row["currency"],
                "est_value": row["est_value"],
                "price_date": row["price_date"],
            }
        )
    return flattened


EXPORT_CSV_FIELDNAMES = [
    "inventory",
    "provider",
    "item_id",
    "scryfall_id",
    "card_name",
    "set_code",
    "set_name",
    "collector_number",
    "rarity",
    "quantity",
    "condition_code",
    "finish",
    "language_code",
    "location",
    "tags",
    "notes",
    "acquisition_price",
    "acquisition_currency",
    "unit_price",
    "price_currency",
    "est_value",
    "price_date",
]


def write_inventory_export_csv(
    path: str | Path,
    rows: list[dict[str, Any]],
    *,
    inventory_slug: str,
    provider: str,
) -> Path:
    flattened_rows = flatten_owned_export_rows(rows, inventory_slug=inventory_slug, provider=provider)
    return write_rows_csv(path, flattened_rows, EXPORT_CSV_FIELDNAMES)


def format_owned_rows(rows: list[dict[str, Any]]) -> str:
    formatted = []
    for row in rows:
        formatted.append(
            {
                "item_id": row["item_id"],
                "name": truncate(row["name"], 28),
                "set": row["set_code"],
                "number": row["collector_number"],
                "rarity": row["rarity"],
                "qty": row["quantity"],
                "cond": row["condition_code"],
                "finish": row["finish"],
                "location": truncate(row["location"], 16),
                "tags": truncate(format_tags(load_tags_json(row["tags_json"])), 24),
                "notes": truncate(row["notes"], 24),
                "unit_price": row["unit_price"],
                "currency": row["currency"],
                "est_value": row["est_value"],
            }
        )

    return render_table(
        formatted,
        [
            ("item_id", "item_id"),
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("rarity", "rarity"),
            ("qty", "qty"),
            ("cond", "cond"),
            ("finish", "finish"),
            ("location", "location"),
            ("tags", "tags"),
            ("notes", "notes"),
            ("unit_price", "unit_price"),
            ("currency", "currency"),
            ("est_value", "est_value"),
        ],
    )


def summarize_filters(
    *,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
) -> str:
    filters: list[str] = []
    if query:
        filters.append(f"query={query}")
    if set_code:
        filters.append(f"set={set_code}")
    if rarity:
        filters.append(f"rarity={rarity}")
    if finish:
        filters.append(f"finish={finish}")
    if condition_code:
        filters.append(f"condition={condition_code}")
    if language_code:
        filters.append(f"language={language_code}")
    if location:
        filters.append(f"location~={location}")
    normalized_tags = parse_tag_filters(tags)
    if normalized_tags:
        filters.append(f"tags={', '.join(normalized_tags)}")
    return ", ".join(filters) if filters else "(none)"


def format_export_csv_result(result: dict[str, Any]) -> str:
    lines = [
        "Exported inventory rows to CSV",
        "",
        f"Inventory: {result['inventory']}",
        f"Provider: {result['provider']}",
        f"Filters: {result['filters_text']}",
        f"Rows exported: {result['rows_exported']}",
        f"Output: {result['output_path']}",
    ]
    return "\n".join(lines)


def build_currency_totals(
    rows: list[dict[str, Any]],
    *,
    value_key: str,
    currency_key: str,
    quantity_key: str,
) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        amount = coerce_float(row.get(value_key))
        currency = text_or_none(row.get(currency_key))
        if amount is None or currency is None:
            continue
        bucket = totals.setdefault(
            currency,
            {"currency": currency, "item_rows": 0, "total_cards": 0, "total_amount": 0.0},
        )
        bucket["item_rows"] += 1
        bucket["total_cards"] += int(row.get(quantity_key, 0) or 0)
        bucket["total_amount"] += amount * int(row.get(quantity_key, 0) or 0) if value_key == "acquisition_price" else amount
    formatted: list[dict[str, Any]] = []
    for currency, bucket in sorted(totals.items()):
        formatted.append(
            {
                "currency": currency,
                "item_rows": bucket["item_rows"],
                "total_cards": bucket["total_cards"],
                "total_amount": round(bucket["total_amount"], 2),
            }
        )
    return formatted


def build_top_value_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    ranked = sorted(
        rows,
        key=lambda row: (coerce_float(row.get("est_value")) or 0.0, int(row.get("quantity", 0) or 0)),
        reverse=True,
    )
    top_rows: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        top_rows.append(
            {
                "item_id": row["item_id"],
                "name": truncate(row["name"], 28),
                "set": row["set_code"],
                "number": row["collector_number"],
                "qty": row["quantity"],
                "finish": row["finish"],
                "location": truncate(text_or_none(row["location"]) or "(none)", 18),
                "est_value": row["est_value"],
                "currency": row["currency"],
            }
        )
    return top_rows


def format_inventory_report_result(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "Inventory report",
        "",
        f"Generated: {result['generated_at']}",
        f"Inventory: {result['inventory']}",
        f"Provider: {result['provider']}",
        f"Filters: {result['filters_text']}",
        f"Item rows: {summary['item_rows']}",
        f"Total cards: {summary['total_cards']}",
        f"Unique printings: {summary['unique_printings']}",
        f"Unique card names: {summary['unique_card_names']}",
        f"Valued rows: {summary['valued_rows']}",
        f"Unpriced rows: {summary['unpriced_rows']}",
    ]

    if result["valuation_rows"]:
        lines.extend(
            [
                "",
                "Valuation totals",
                "",
                render_table(
                    result["valuation_rows"],
                    [
                        ("provider", "provider"),
                        ("currency", "currency"),
                        ("item_rows", "item_rows"),
                        ("total_cards", "total_cards"),
                        ("total_value", "total_value"),
                    ],
                ),
            ]
        )

    if result["acquisition_totals"]:
        lines.extend(
            [
                "",
                "Tracked acquisition totals",
                "",
                render_table(
                    result["acquisition_totals"],
                    [
                        ("currency", "currency"),
                        ("item_rows", "item_rows"),
                        ("total_cards", "total_cards"),
                        ("total_amount", "total_amount"),
                    ],
                ),
            ]
        )

    if result["top_rows"]:
        lines.extend(
            [
                "",
                "Top holdings by estimated value",
                "",
                render_table(
                    result["top_rows"],
                    [
                        ("item_id", "item_id"),
                        ("name", "name"),
                        ("set", "set"),
                        ("number", "number"),
                        ("qty", "qty"),
                        ("finish", "finish"),
                        ("location", "location"),
                        ("est_value", "est_value"),
                        ("currency", "currency"),
                    ],
                ),
            ]
        )

    health_summary = result["health"]["summary"]
    lines.extend(
        [
            "",
            "Health summary",
            "",
            f"Missing current-price rows: {health_summary['missing_price_rows']}",
            f"Missing location rows: {health_summary['missing_location_rows']}",
            f"Missing tag rows: {health_summary['missing_tag_rows']}",
            f"Merged acquisition note rows: {health_summary['merge_note_rows']}",
            f"Stale price rows: {health_summary['stale_price_rows']}",
            f"Duplicate-like groups: {health_summary['duplicate_groups']}",
        ]
    )

    return "\n".join(lines)


def format_price_gap_rows(rows: list[dict[str, Any]]) -> str:
    formatted = []
    for row in rows:
        formatted.append(
            {
                "item_id": row["item_id"],
                "name": truncate(row["card_name"], 28),
                "set": row["set_code"],
                "number": row["collector_number"],
                "finish": row["finish"],
                "priced_finishes": truncate(format_finishes(row["available_finishes"]), 18),
                "suggested": row["suggested_finish"] or "",
                "status": truncate(row["reconcile_status"], 24),
            }
        )

    return render_table(
        formatted,
        [
            ("item_id", "item_id"),
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("finish", "finish"),
            ("priced_finishes", "priced_finishes"),
            ("suggested", "suggested"),
            ("status", "status"),
        ],
    )


def format_reconcile_prices_result(result: dict[str, Any]) -> str:
    lines = [
        "Reconciled inventory pricing finishes",
        "",
        f"Inventory: {result['inventory']}",
        f"Provider: {result['provider']}",
        f"Rows with missing current-price matches: {result['rows_seen']}",
        f"Rows with a single suggested finish: {result['rows_fixable']}",
        f"Rows updated: {result['rows_updated']}",
    ]
    if not result["applied"]:
        lines.append("Mode: preview only")

    if result["updated_rows"]:
        lines.extend(
            [
                "",
                "Updated rows",
                "",
                format_price_gap_rows(result["updated_rows"]),
            ]
        )

    if result["remaining_rows"]:
        lines.extend(
            [
                "",
                "Still unresolved",
                "",
                format_price_gap_rows(result["remaining_rows"]),
            ]
        )

    return "\n".join(lines)


def append_preview_section(
    lines: list[str],
    *,
    title: str,
    rows: list[dict[str, Any]],
    columns: list[tuple[str, str]],
    overflow_label: str,
    limit: int,
) -> None:
    if not rows:
        return

    preview_rows = rows[:limit]
    lines.extend(
        [
            "",
            title,
            "",
            render_table(preview_rows, columns),
        ]
    )
    remaining = len(rows) - len(preview_rows)
    if remaining > 0:
        lines.append(f"... {remaining} more {overflow_label} not shown.")


def format_inventory_health_result(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "Inventory health report",
        "",
        f"Inventory: {result['inventory']}",
        f"Provider: {result['provider']}",
        f"Stale price threshold: {result['stale_days']} day(s)",
        f"Current date: {result['current_date']}",
        f"Item rows: {summary['item_rows']}",
        f"Total cards: {summary['total_cards']}",
        f"Rows missing current prices: {summary['missing_price_rows']}",
        f"Rows missing location: {summary['missing_location_rows']}",
        f"Rows missing tags: {summary['missing_tag_rows']}",
        f"Rows with merged acquisition notes: {summary['merge_note_rows']}",
        f"Rows with stale prices: {summary['stale_price_rows']}",
        f"Duplicate-like groups: {summary['duplicate_groups']}",
    ]

    if not any(
        summary[key]
        for key in (
            "missing_price_rows",
            "missing_location_rows",
            "missing_tag_rows",
            "merge_note_rows",
            "stale_price_rows",
            "duplicate_groups",
        )
    ):
        lines.extend(["", "No issues detected in the current inventory-health checks."])
        return "\n".join(lines)

    append_preview_section(
        lines,
        title="Missing current-price matches",
        rows=result["missing_price_rows"],
        columns=[
            ("item_id", "item_id"),
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("finish", "finish"),
            ("priced_finishes", "priced_finishes"),
            ("status", "status"),
        ],
        overflow_label="missing-price row(s)",
        limit=result["preview_limit"],
    )
    append_preview_section(
        lines,
        title="Missing location",
        rows=result["missing_location_rows"],
        columns=[
            ("item_id", "item_id"),
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("qty", "qty"),
            ("cond", "cond"),
            ("finish", "finish"),
            ("tags", "tags"),
        ],
        overflow_label="location row(s)",
        limit=result["preview_limit"],
    )
    append_preview_section(
        lines,
        title="Missing tags",
        rows=result["missing_tag_rows"],
        columns=[
            ("item_id", "item_id"),
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("qty", "qty"),
            ("cond", "cond"),
            ("finish", "finish"),
            ("location", "location"),
        ],
        overflow_label="tag row(s)",
        limit=result["preview_limit"],
    )
    append_preview_section(
        lines,
        title="Merged acquisition notes",
        rows=result["merge_note_rows"],
        columns=[
            ("item_id", "item_id"),
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("location", "location"),
            ("note", "note"),
        ],
        overflow_label="merge-note row(s)",
        limit=result["preview_limit"],
    )
    append_preview_section(
        lines,
        title="Stale prices",
        rows=result["stale_price_rows"],
        columns=[
            ("item_id", "item_id"),
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("finish", "finish"),
            ("price_date", "price_date"),
            ("age_days", "age_days"),
        ],
        overflow_label="stale-price row(s)",
        limit=result["preview_limit"],
    )
    append_preview_section(
        lines,
        title="Duplicate-like groups",
        rows=result["duplicate_groups"],
        columns=[
            ("name", "name"),
            ("set", "set"),
            ("number", "number"),
            ("cond", "cond"),
            ("finish", "finish"),
            ("rows", "rows"),
            ("qty", "qty"),
            ("locations", "locations"),
        ],
        overflow_label="duplicate group(s)",
        limit=result["preview_limit"],
    )

    return "\n".join(lines)


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


def parse_finish_list(value: str | None) -> list[str]:
    finishes: list[str] = []
    text = text_or_none(value)
    if text is None:
        return finishes
    for part in text.split(","):
        finish = text_or_none(part)
        if finish is None:
            continue
        normalized = normalize_finish(finish)
        if normalized not in finishes:
            finishes.append(normalized)
    return finishes


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


def normalize_csv_header(header: str) -> str:
    normalized = header.strip().lower()
    for old, new in ((" ", "_"), ("-", "_"), ("/", "_"), (".", "_")):
        normalized = normalized.replace(old, new)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return CSV_HEADER_ALIASES.get(normalized, normalized)


def normalize_csv_row(raw_row: dict[str, Any]) -> dict[str, str | None]:
    normalized: dict[str, str | None] = {}
    for key, value in raw_row.items():
        if key is None:
            continue
        normalized[normalize_csv_header(key)] = text_or_none(value)
    return normalized


def is_blank_csv_row(row: dict[str, str | None]) -> bool:
    return not any(value is not None for value in row.values())


def parse_csv_float(value: str | None, field_name: str, row_number: int) -> float | None:
    text = text_or_none(value)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"CSV row {row_number}: {field_name} must be a number.") from exc


def build_add_card_kwargs_from_csv_row(
    row: dict[str, str | None],
    *,
    row_number: int,
    default_inventory: str | None,
) -> dict[str, Any] | None:
    inventory_display_name = text_or_none(row.get("inventory_name"))
    inventory_slug = first_non_empty(
        row.get("inventory"),
        slugify_inventory_name(inventory_display_name) if inventory_display_name else None,
        default_inventory,
    )
    if inventory_slug is None:
        raise ValueError(f"CSV row {row_number}: provide an inventory column or pass --inventory.")

    scryfall_id = text_or_none(row.get("scryfall_id"))
    tcgplayer_product_id = normalize_external_id(row.get("tcgplayer_product_id"))
    name = text_or_none(row.get("name"))
    if scryfall_id is None and tcgplayer_product_id is None and name is None:
        raise ValueError(
            f"CSV row {row_number}: provide one of scryfall_id, tcgplayer product id, or name."
        )

    quantity = resolve_csv_quantity(row, row_number=row_number)
    if quantity is None:
        return None

    finish, finish_source = finish_and_source_from_row(row)

    return {
        "inventory_slug": inventory_slug,
        "inventory_display_name": inventory_display_name,
        "scryfall_id": scryfall_id,
        "tcgplayer_product_id": tcgplayer_product_id,
        "name": name,
        "set_code": text_or_none(row.get("set_code")),
        "collector_number": text_or_none(row.get("collector_number")),
        "lang": text_or_none(row.get("lang")),
        "quantity": quantity,
        "condition_code": normalize_condition_code(row.get("condition")),
        "finish": finish,
        "language_code": normalize_language_code(row.get("language_code")),
        "location": text_or_none(row.get("location")) or "",
        "acquisition_price": parse_csv_float(row.get("acquisition_price"), "acquisition_price", row_number),
        "acquisition_currency": text_or_none(row.get("acquisition_currency")),
        "notes": text_or_none(row.get("notes")),
        "tags": text_or_none(row.get("tags")),
        "_csv_finish_source": finish_source,
    }


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


def maybe_adjust_finish_for_csv_import(
    connection: sqlite3.Connection,
    *,
    row_number: int,
    finish_source: str,
    add_kwargs: dict[str, Any],
) -> dict[str, Any] | None:
    if finish_source != "default":
        return None

    card = resolve_card_row(
        connection,
        scryfall_id=add_kwargs.get("scryfall_id"),
        tcgplayer_product_id=normalize_external_id(add_kwargs.get("tcgplayer_product_id")),
        name=add_kwargs.get("name"),
        set_code=add_kwargs.get("set_code"),
        collector_number=add_kwargs.get("collector_number"),
        lang=add_kwargs.get("lang"),
    )

    available_finishes = normalized_catalog_finish_list(card["finishes_json"])
    if len(available_finishes) != 1:
        return None

    current_finish = normalize_finish(add_kwargs["finish"])
    suggested_finish = available_finishes[0]
    if suggested_finish == current_finish:
        return None

    add_kwargs["finish"] = suggested_finish
    return {
        "csv_row": row_number,
        "inventory": add_kwargs["inventory_slug"],
        "card_name": card["name"],
        "set_code": card["set_code"],
        "collector_number": card["collector_number"],
        "old_finish": current_finish,
        "new_finish": suggested_finish,
        "available_finishes": available_finishes,
        "reason": "single catalog finish",
    }


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


def import_csv(
    db_path: str | Path,
    *,
    csv_path: str | Path,
    default_inventory: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    initialize_database(db_path)
    imported_rows: list[dict[str, Any]] = []
    finish_adjustments: list[dict[str, Any]] = []
    rows_seen = 0
    inventory_cache: dict[str, sqlite3.Row] = {}

    try:
        with Path(csv_path).open(mode="r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV file must include a header row.")

            with connect(db_path) as connection:
                for row_number, raw_row in enumerate(reader, start=2):
                    row = normalize_csv_row(raw_row)
                    if is_blank_csv_row(row):
                        continue

                    rows_seen += 1
                    add_kwargs = build_add_card_kwargs_from_csv_row(
                        row,
                        row_number=row_number,
                        default_inventory=default_inventory,
                    )
                    if add_kwargs is None:
                        continue
                    finish_source = str(add_kwargs.pop("_csv_finish_source", "default"))
                    finish_adjustment = maybe_adjust_finish_for_csv_import(
                        connection,
                        row_number=row_number,
                        finish_source=finish_source,
                        add_kwargs=add_kwargs,
                    )
                    result = add_card_with_connection(
                        connection,
                        inventory_cache=inventory_cache,
                        **add_kwargs,
                    )
                    imported_rows.append({"csv_row": row_number, **result})
                    if finish_adjustment is not None:
                        finish_adjustments.append(finish_adjustment)

                if dry_run:
                    connection.rollback()
                else:
                    connection.commit()
    except OSError as exc:
        raise ValueError(f"Could not read CSV file '{csv_path}'.") from exc
    except csv.Error as exc:
        raise ValueError(f"Could not parse CSV file '{csv_path}': {exc}") from exc

    return {
        "csv_path": str(csv_path),
        "default_inventory": default_inventory,
        "rows_seen": rows_seen,
        "rows_written": len(imported_rows),
        "imported_rows": imported_rows,
        "dry_run": dry_run,
        "finish_adjustment_count": len(finish_adjustments),
        "finish_adjustments": finish_adjustments,
    }


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Thin personal inventory CLI for the isolated MTG MVP database.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_inv = subparsers.add_parser("create-inventory", help="Create a personal inventory.")
    create_inv.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    create_inv.add_argument("--slug", required=True, help="Stable inventory slug, such as personal.")
    create_inv.add_argument("--display-name", required=True, help="Human-friendly inventory name.")
    create_inv.add_argument("--description", help="Optional inventory description.")

    list_inv = subparsers.add_parser("list-inventories", help="List inventories and their row counts.")
    list_inv.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")

    search = subparsers.add_parser("search-cards", help="Search imported MTG printings.")
    search.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    search.add_argument("--query", required=True, help="Card name search string.")
    search.add_argument("--set-code", help="Optional set code filter.")
    search.add_argument("--rarity", help="Optional rarity filter, such as common or mythic.")
    search.add_argument("--finish", help="Optional finish filter, such as normal or foil.")
    search.add_argument("--lang", help="Optional printing language filter.")
    search.add_argument("--exact", action="store_true", help="Require an exact card name match.")
    search.add_argument("--limit", type=int, default=10, help="Maximum number of rows to show.")

    add = subparsers.add_parser("add-card", help="Add owned copies into an inventory.")
    add.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    add.add_argument("--inventory", required=True, help="Inventory slug.")
    add.add_argument("--scryfall-id", help="Exact Scryfall printing ID to add.")
    add.add_argument("--tcgplayer-product-id", help="Exact TCGplayer product id to add.")
    add.add_argument("--name", help="Exact card name if not using --scryfall-id.")
    add.add_argument("--set-code", help="Optional set code to disambiguate name matches.")
    add.add_argument("--collector-number", help="Optional collector number to disambiguate name matches.")
    add.add_argument("--lang", help="Optional printing language to disambiguate name matches.")
    add.add_argument("--quantity", type=int, default=1, help="Number of copies to add.")
    add.add_argument("--condition", default="NM", help="Condition code, such as NM, LP, MP.")
    add.add_argument("--finish", default="normal", help="normal, nonfoil, foil, or etched.")
    add.add_argument("--language-code", default="en", help="Owned card language code.")
    add.add_argument("--location", default="", help="Storage location, such as Binder 1.")
    add.add_argument("--acquisition-price", type=float, help="Optional acquisition price per row.")
    add.add_argument("--acquisition-currency", help="Optional acquisition currency, such as USD.")
    add.add_argument("--notes", help="Optional notes.")
    add.add_argument("--tags", help="Optional comma-separated custom tags, such as commander,trade.")

    csv_import = subparsers.add_parser("import-csv", help="Import inventory rows from a CSV file.")
    csv_import.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    csv_import.add_argument("--csv", required=True, help="CSV file to import.")
    csv_import.add_argument("--inventory", help="Default inventory slug if the CSV does not include one.")
    csv_import.add_argument("--dry-run", action="store_true", help="Preview the import without saving any changes.")
    csv_import.add_argument("--report-out", help="Optional path to save the import report text.")
    csv_import.add_argument("--report-out-json", help="Optional path to save the structured import report JSON.")
    csv_import.add_argument("--report-out-csv", help="Optional path to save a flattened per-row import CSV report.")

    set_qty = subparsers.add_parser("set-quantity", help="Set the quantity for an existing inventory row.")
    set_qty.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    set_qty.add_argument("--inventory", required=True, help="Inventory slug.")
    set_qty.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")
    set_qty.add_argument("--quantity", required=True, type=int, help="New quantity for the row.")

    set_finish_parser = subparsers.add_parser("set-finish", help="Set the finish for an existing inventory row.")
    set_finish_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    set_finish_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    set_finish_parser.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")
    set_finish_parser.add_argument("--finish", required=True, help="New finish: normal, foil, or etched.")

    set_location_parser = subparsers.add_parser("set-location", help="Set the location for an existing inventory row.")
    set_location_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    set_location_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    set_location_parser.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")
    set_location_group = set_location_parser.add_mutually_exclusive_group(required=True)
    set_location_group.add_argument("--location", help="New location string, such as Binder 2.")
    set_location_group.add_argument("--clear", action="store_true", help="Clear the location from the row.")
    set_location_parser.add_argument(
        "--merge",
        action="store_true",
        help="If the new location collides with another row, merge into that row instead of failing.",
    )

    set_condition_parser = subparsers.add_parser(
        "set-condition",
        help="Set the condition code for an existing inventory row.",
    )
    set_condition_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    set_condition_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    set_condition_parser.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")
    set_condition_parser.add_argument("--condition", required=True, help="New condition code, such as NM, LP, MP.")
    set_condition_parser.add_argument(
        "--merge",
        action="store_true",
        help="If the new condition collides with another row, merge into that row instead of failing.",
    )

    set_notes_parser = subparsers.add_parser("set-notes", help="Replace the notes for an existing inventory row.")
    set_notes_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    set_notes_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    set_notes_parser.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")
    set_notes_group = set_notes_parser.add_mutually_exclusive_group(required=True)
    set_notes_group.add_argument("--notes", help="New notes text to store on the row.")
    set_notes_group.add_argument("--clear", action="store_true", help="Clear notes from the row.")

    set_acquisition_parser = subparsers.add_parser(
        "set-acquisition",
        help="Set or clear acquisition price metadata for an existing inventory row.",
    )
    set_acquisition_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    set_acquisition_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    set_acquisition_parser.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")
    set_acquisition_parser.add_argument("--price", type=float, help="Acquisition price to store on the row.")
    set_acquisition_parser.add_argument("--currency", help="Acquisition currency, such as USD.")
    set_acquisition_parser.add_argument("--clear", action="store_true", help="Clear acquisition price and currency.")

    set_tags_parser = subparsers.add_parser("set-tags", help="Replace the custom tags for an existing inventory row.")
    set_tags_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    set_tags_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    set_tags_parser.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")
    set_tags_group = set_tags_parser.add_mutually_exclusive_group(required=True)
    set_tags_group.add_argument("--tags", help="Comma-separated custom tags to store on the row.")
    set_tags_group.add_argument("--clear", action="store_true", help="Clear all tags from the row.")

    split_row_parser = subparsers.add_parser(
        "split-row",
        help="Move part of a row's quantity into a new or existing target row.",
    )
    split_row_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    split_row_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    split_row_parser.add_argument("--item-id", required=True, type=int, help="Source inventory row id from list-owned.")
    split_row_parser.add_argument("--quantity", required=True, type=int, help="Quantity to move into the target row.")
    split_row_parser.add_argument("--condition", help="Optional target condition code.")
    split_row_parser.add_argument("--finish", help="Optional target finish.")
    split_row_parser.add_argument("--language-code", help="Optional target language code.")
    split_row_parser.add_argument("--location", help="Optional target location.")
    split_row_parser.add_argument("--clear-location", action="store_true", help="Clear the target row location.")

    merge_rows_parser = subparsers.add_parser(
        "merge-rows",
        help="Explicitly merge one inventory row into another row for the same printing.",
    )
    merge_rows_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    merge_rows_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    merge_rows_parser.add_argument("--source-item-id", required=True, type=int, help="Source row id to remove.")
    merge_rows_parser.add_argument("--target-item-id", required=True, type=int, help="Target row id to keep.")

    remove = subparsers.add_parser("remove-card", help="Delete an inventory row by item id.")
    remove.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    remove.add_argument("--inventory", required=True, help="Inventory slug.")
    remove.add_argument("--item-id", required=True, type=int, help="Inventory row id from list-owned.")

    health = subparsers.add_parser(
        "inventory-health",
        aliases=["doctor"],
        help="Run a quick health report for an inventory.",
    )
    health.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    health.add_argument("--inventory", required=True, help="Inventory slug.")
    health.add_argument("--provider", default=DEFAULT_PROVIDER, help="Price provider, such as tcgplayer.")
    health.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_HEALTH_STALE_DAYS,
        help="Flag matching prices older than this many days.",
    )
    health.add_argument(
        "--limit",
        type=int,
        default=HEALTH_PREVIEW_LIMIT,
        help="Maximum rows to preview per health section.",
    )

    price_gaps = subparsers.add_parser("price-gaps", help="List inventory rows whose current finish has no retail price.")
    price_gaps.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    price_gaps.add_argument("--inventory", required=True, help="Inventory slug.")
    price_gaps.add_argument("--provider", default=DEFAULT_PROVIDER, help="Price provider, such as tcgplayer.")
    price_gaps.add_argument("--limit", type=int, help="Optional max number of rows to show.")

    reconcile = subparsers.add_parser(
        "reconcile-prices",
        help="Suggest or apply finish updates when exactly one priced finish is available.",
    )
    reconcile.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    reconcile.add_argument("--inventory", required=True, help="Inventory slug.")
    reconcile.add_argument("--provider", default=DEFAULT_PROVIDER, help="Price provider, such as tcgplayer.")
    reconcile.add_argument(
        "--apply",
        action="store_true",
        help="Apply suggested finish updates. Without this flag, the command is preview-only.",
    )

    export_csv_parser = subparsers.add_parser(
        "export-csv",
        help="Export filtered inventory rows to a CSV file.",
    )
    export_csv_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    export_csv_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    export_csv_parser.add_argument("--output", required=True, help="CSV file to write.")
    export_csv_parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Price provider, such as tcgplayer.")
    export_csv_parser.add_argument("--query", help="Optional card name substring filter.")
    export_csv_parser.add_argument("--set-code", help="Optional set code filter.")
    export_csv_parser.add_argument("--rarity", help="Optional rarity filter, such as common or mythic.")
    export_csv_parser.add_argument("--finish", help="Optional finish filter, such as normal or foil.")
    export_csv_parser.add_argument("--condition", help="Optional condition filter, such as NM or LP.")
    export_csv_parser.add_argument("--language-code", help="Optional owned language code filter.")
    export_csv_parser.add_argument("--location", help="Optional location substring filter.")
    export_csv_parser.add_argument("--tag", action="append", help="Optional custom tag filter. Repeat to require multiple tags.")
    export_csv_parser.add_argument("--limit", type=int, help="Optional max number of rows to export.")

    report_parser = subparsers.add_parser(
        "inventory-report",
        aliases=["report"],
        help="Create a summary report for an inventory, with optional file outputs.",
    )
    report_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    report_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    report_parser.add_argument("--provider", default=DEFAULT_PROVIDER, help="Price provider, such as tcgplayer.")
    report_parser.add_argument("--query", help="Optional card name substring filter.")
    report_parser.add_argument("--set-code", help="Optional set code filter.")
    report_parser.add_argument("--rarity", help="Optional rarity filter, such as common or mythic.")
    report_parser.add_argument("--finish", help="Optional finish filter, such as normal or foil.")
    report_parser.add_argument("--condition", help="Optional condition filter, such as NM or LP.")
    report_parser.add_argument("--language-code", help="Optional owned language code filter.")
    report_parser.add_argument("--location", help="Optional location substring filter.")
    report_parser.add_argument("--tag", action="append", help="Optional custom tag filter. Repeat to require multiple tags.")
    report_parser.add_argument(
        "--stale-days",
        type=int,
        default=DEFAULT_HEALTH_STALE_DAYS,
        help="Flag matching prices older than this many days inside the report.",
    )
    report_parser.add_argument(
        "--limit",
        type=int,
        default=HEALTH_PREVIEW_LIMIT,
        help="Maximum rows to preview in the report sections.",
    )
    report_parser.add_argument("--report-out", help="Optional path to save the text report.")
    report_parser.add_argument("--report-out-json", help="Optional path to save the structured report JSON.")
    report_parser.add_argument("--report-out-csv", help="Optional path to save the filtered inventory rows as CSV.")

    owned = subparsers.add_parser("list-owned", help="List inventory rows with latest retail prices.")
    owned.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    owned.add_argument("--inventory", required=True, help="Inventory slug.")
    owned.add_argument("--provider", default=DEFAULT_PROVIDER, help="Price provider, such as tcgplayer.")
    owned.add_argument("--query", help="Optional card name substring filter.")
    owned.add_argument("--set-code", help="Optional set code filter.")
    owned.add_argument("--rarity", help="Optional rarity filter, such as common or mythic.")
    owned.add_argument("--finish", help="Optional finish filter, such as normal or foil.")
    owned.add_argument("--condition", help="Optional condition filter, such as NM or LP.")
    owned.add_argument("--language-code", help="Optional owned language code filter.")
    owned.add_argument("--location", help="Optional location substring filter.")
    owned.add_argument("--tag", action="append", help="Optional custom tag filter. Repeat to require multiple tags.")
    owned.add_argument("--limit", type=int, help="Optional max number of rows to show.")

    value = subparsers.add_parser("valuation", help="Summarize inventory value from latest retail prices.")
    value.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    value.add_argument("--inventory", required=True, help="Inventory slug.")
    value.add_argument("--provider", help="Optional provider filter, such as tcgplayer.")
    value.add_argument("--query", help="Optional card name substring filter.")
    value.add_argument("--set-code", help="Optional set code filter.")
    value.add_argument("--rarity", help="Optional rarity filter, such as common or mythic.")
    value.add_argument("--finish", help="Optional finish filter, such as normal or foil.")
    value.add_argument("--condition", help="Optional condition filter, such as NM or LP.")
    value.add_argument("--language-code", help="Optional owned language code filter.")
    value.add_argument("--location", help="Optional location substring filter.")
    value.add_argument("--tag", action="append", help="Optional custom tag filter. Repeat to require multiple tags.")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    initialize_database(args.db)

    try:
        if args.command == "create-inventory":
            inventory_id = create_inventory(args.db, args.slug, args.display_name, args.description)
            print(f"Created inventory '{args.slug}' with id={inventory_id}")
            return

        if args.command == "list-inventories":
            rows = list_inventories(args.db)
            print_table(
                rows,
                [
                    ("slug", "slug"),
                    ("display_name", "display_name"),
                    ("item_rows", "item_rows"),
                    ("total_cards", "total_cards"),
                    ("description", "description"),
                ],
            )
            return

        if args.command == "search-cards":
            rows = search_cards(
                args.db,
                args.query,
                args.set_code,
                args.rarity,
                args.finish,
                args.lang,
                args.exact,
                args.limit,
            )
            simplified = []
            for row in rows:
                simplified.append(
                    {
                        "name": truncate(row["name"], 28),
                        "set": row["set_code"],
                        "number": row["collector_number"],
                        "lang": row["lang"],
                        "rarity": row["rarity"] or "",
                        "finishes": row["finishes"],
                        "scryfall_id": row["scryfall_id"],
                    }
                )
            print_table(
                simplified,
                [
                    ("name", "name"),
                    ("set", "set"),
                    ("number", "number"),
                    ("lang", "lang"),
                    ("rarity", "rarity"),
                    ("finishes", "finishes"),
                    ("scryfall_id", "scryfall_id"),
                ],
            )
            return

        if args.command == "add-card":
            result = add_card(
                args.db,
                inventory_slug=args.inventory,
                scryfall_id=args.scryfall_id,
                tcgplayer_product_id=args.tcgplayer_product_id,
                name=args.name,
                set_code=args.set_code,
                collector_number=args.collector_number,
                lang=args.lang,
                quantity=args.quantity,
                condition_code=args.condition,
                finish=args.finish,
                language_code=args.language_code,
                location=args.location,
                acquisition_price=args.acquisition_price,
                acquisition_currency=args.acquisition_currency,
                notes=args.notes,
                tags=args.tags,
            )
            print(format_add_card_result(result))
            return

        if args.command == "import-csv":
            snapshot = None
            if not args.dry_run:
                snapshot = create_database_snapshot(
                    args.db,
                    label=f"before_import_csv_{Path(args.csv).stem}",
                )
            result = import_csv(
                args.db,
                csv_path=args.csv,
                default_inventory=args.inventory,
                dry_run=args.dry_run,
            )
            report_text = append_snapshot_notice(format_import_csv_result(result), snapshot)
            report_paths: list[str] = []
            if args.report_out:
                report_path = write_report(args.report_out, report_text)
                report_paths.append(f"Text report saved to: {report_path}")
            if args.report_out_json:
                report_path = write_json_report(args.report_out_json, result)
                report_paths.append(f"JSON report saved to: {report_path}")
            if args.report_out_csv:
                report_path = write_csv_report(args.report_out_csv, result)
                report_paths.append(f"CSV report saved to: {report_path}")
            if report_paths:
                report_text = f"{report_text}\n\n" + "\n".join(report_paths)
            print(report_text)
            return

        if args.command == "set-tags":
            result = set_tags(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                tags="" if args.clear else args.tags,
            )
            print(format_set_tags_result(result))
            return

        if args.command == "set-location":
            snapshot = None
            if args.merge:
                snapshot = create_database_snapshot(
                    args.db,
                    label=f"before_set_location_merge_item_{args.item_id}",
                )
            result = set_location(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                location=None if args.clear else args.location,
                merge=args.merge,
            )
            print(append_snapshot_notice(format_set_location_result(result), snapshot))
            return

        if args.command == "set-condition":
            snapshot = None
            if args.merge:
                snapshot = create_database_snapshot(
                    args.db,
                    label=f"before_set_condition_merge_item_{args.item_id}",
                )
            result = set_condition(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                condition_code=args.condition,
                merge=args.merge,
            )
            print(append_snapshot_notice(format_set_condition_result(result), snapshot))
            return

        if args.command == "set-acquisition":
            snapshot = create_database_snapshot(
                args.db,
                label=f"before_set_acquisition_item_{args.item_id}",
            )
            result = set_acquisition(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                acquisition_price=args.price,
                acquisition_currency=args.currency,
                clear=args.clear,
            )
            print(append_snapshot_notice(format_set_acquisition_result(result), snapshot))
            return

        if args.command == "set-notes":
            result = set_notes(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                notes=None if args.clear else args.notes,
            )
            print(format_set_notes_result(result))
            return

        if args.command == "set-finish":
            result = set_finish(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                finish=args.finish,
            )
            print(format_set_finish_result(result))
            return

        if args.command == "set-quantity":
            result = set_quantity(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                quantity=args.quantity,
            )
            print(format_set_quantity_result(result))
            return

        if args.command == "split-row":
            snapshot = create_database_snapshot(
                args.db,
                label=f"before_split_row_item_{args.item_id}",
            )
            result = split_row(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                quantity=args.quantity,
                condition_code=args.condition,
                finish=args.finish,
                language_code=args.language_code,
                location=args.location,
                clear_location=args.clear_location,
            )
            print(append_snapshot_notice(format_split_row_result(result), snapshot))
            return

        if args.command == "merge-rows":
            snapshot = create_database_snapshot(
                args.db,
                label=f"before_merge_rows_{args.source_item_id}_into_{args.target_item_id}",
            )
            result = merge_rows(
                args.db,
                inventory_slug=args.inventory,
                source_item_id=args.source_item_id,
                target_item_id=args.target_item_id,
            )
            print(append_snapshot_notice(format_merge_rows_result(result), snapshot))
            return

        if args.command == "remove-card":
            snapshot = create_database_snapshot(
                args.db,
                label=f"before_remove_card_item_{args.item_id}",
            )
            result = remove_card(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
            )
            print(append_snapshot_notice(format_remove_card_result(result), snapshot))
            return

        if args.command in {"inventory-health", "doctor"}:
            result = inventory_health(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                stale_days=args.stale_days,
                preview_limit=args.limit,
            )
            print(format_inventory_health_result(result))
            return

        if args.command == "price-gaps":
            rows = list_price_gaps(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                limit=args.limit,
            )
            print(format_price_gap_rows(rows))
            return

        if args.command == "reconcile-prices":
            snapshot = None
            if args.apply:
                snapshot = create_database_snapshot(
                    args.db,
                    label=f"before_reconcile_prices_{args.inventory}_{args.provider}",
                )
            result = reconcile_prices(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                apply_changes=args.apply,
            )
            print(append_snapshot_notice(format_reconcile_prices_result(result), snapshot))
            return

        if args.command == "export-csv":
            result = export_inventory_csv(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                output_path=args.output,
                query=args.query,
                set_code=args.set_code,
                rarity=args.rarity,
                finish=args.finish,
                condition_code=args.condition,
                language_code=args.language_code,
                location=args.location,
                tags=args.tag,
                limit=args.limit,
            )
            print(format_export_csv_result(result))
            return

        if args.command in {"inventory-report", "report"}:
            result = inventory_report(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                query=args.query,
                set_code=args.set_code,
                rarity=args.rarity,
                finish=args.finish,
                condition_code=args.condition,
                language_code=args.language_code,
                location=args.location,
                tags=args.tag,
                limit=args.limit,
                stale_days=args.stale_days,
            )
            report_text = format_inventory_report_result(result)
            report_paths: list[str] = []
            if args.report_out:
                report_path = write_report(args.report_out, report_text)
                report_paths.append(f"Text report saved to: {report_path}")
            if args.report_out_json:
                report_path = write_json_report(args.report_out_json, result)
                report_paths.append(f"JSON report saved to: {report_path}")
            if args.report_out_csv:
                report_path = write_rows_csv(args.report_out_csv, result["rows"], EXPORT_CSV_FIELDNAMES)
                report_paths.append(f"CSV report saved to: {report_path}")
            if report_paths:
                report_text = f"{report_text}\n\n" + "\n".join(report_paths)
            print(report_text)
            return

        if args.command == "list-owned":
            rows = list_owned_filtered(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                limit=args.limit,
                query=args.query,
                set_code=args.set_code,
                rarity=args.rarity,
                finish=args.finish,
                condition_code=args.condition,
                language_code=args.language_code,
                location=args.location,
                tags=args.tag,
            )
            print(format_owned_rows(rows))
            return

        if args.command == "valuation":
            rows = valuation_filtered(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                query=args.query,
                set_code=args.set_code,
                rarity=args.rarity,
                finish=args.finish,
                condition_code=args.condition,
                language_code=args.language_code,
                location=args.location,
                tags=args.tag,
            )
            print_table(
                rows,
                [
                    ("provider", "provider"),
                    ("currency", "currency"),
                    ("item_rows", "item_rows"),
                    ("total_cards", "total_cards"),
                    ("total_value", "total_value"),
                ],
            )
            return

    except ValueError as exc:
        parser.exit(status=2, message=f"Error: {exc}\n")


if __name__ == "__main__":
    main()
