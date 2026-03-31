"""CSV ingestion helpers that normalize rows into inventory mutations."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..db.connection import connect
from ..db.schema import initialize_database
from .normalize import (
    CSV_HEADER_ALIASES,
    finish_from_row,
    first_non_empty,
    normalize_condition_code,
    normalize_external_id,
    normalize_language_code,
    resolve_csv_quantity,
    slugify_inventory_name,
    text_or_none,
)
from .service import add_card_with_connection


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
    # Accept either a stable slug, a human display name, or the CLI default so
    # the same import path can handle hand-authored CSVs and exported files.
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
        "finish": finish_from_row(row),
        "language_code": normalize_language_code(row.get("language_code")),
        "location": text_or_none(row.get("location")) or "",
        "acquisition_price": parse_csv_float(row.get("acquisition_price"), "acquisition_price", row_number),
        "acquisition_currency": text_or_none(row.get("acquisition_currency")),
        "notes": text_or_none(row.get("notes")),
        "tags": text_or_none(row.get("tags")),
    }


def import_csv(
    db_path: str | Path,
    *,
    csv_path: str | Path,
    default_inventory: str | None,
    dry_run: bool = False,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    imported_rows: list[dict[str, Any]] = []
    pending_rows: list[tuple[int, dict[str, Any]]] = []
    rows_seen = 0
    inventory_cache: dict[str, sqlite3.Row] = {}

    try:
        with Path(csv_path).open(mode="r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError("CSV file must include a header row.")

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
                pending_rows.append((row_number, add_kwargs))
    except OSError as exc:
        raise ValueError(f"Could not read CSV file '{csv_path}'.") from exc
    except csv.Error as exc:
        raise ValueError(f"Could not parse CSV file '{csv_path}': {exc}") from exc

    initialize_database(db_path)
    with connect(db_path) as connection:
        for row_number, add_kwargs in pending_rows:
            result = add_card_with_connection(
                connection,
                inventory_cache=inventory_cache,
                before_write=None if dry_run else before_write,
                **add_kwargs,
            )
            imported_rows.append({"csv_row": row_number, **result})

        if dry_run:
            # Preview mode reuses the real add-card workflow, then rolls
            # back at the end so validation and reporting stay identical.
            connection.rollback()
        else:
            connection.commit()

    return {
        "csv_path": str(csv_path),
        "default_inventory": default_inventory,
        "rows_seen": rows_seen,
        "rows_written": len(imported_rows),
        "imported_rows": imported_rows,
        "dry_run": dry_run,
    }
