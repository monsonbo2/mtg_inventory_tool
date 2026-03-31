"""File writers and row flatteners for inventory reporting."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .normalize import format_tags, text_or_none
from .response_models import serialize_response


def write_report(path: str | Path, text: str) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(text, encoding="utf-8")
    return report_path


def write_json_report(path: str | Path, payload: Any) -> Path:
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(serialize_response(payload), ensure_ascii=True, indent=2), encoding="utf-8")
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
    flattened: list[dict[str, Any]] = []
    for row in result.get("imported_rows", []):
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
    ]
    return write_rows_csv(report_path, rows, fieldnames)


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
                "tags": format_tags(row.get("tags", [])),
                "notes": text_or_none(row["notes"]) or "",
                "acquisition_price": row["acquisition_price"] if row["acquisition_price"] is not None else "",
                "acquisition_currency": text_or_none(row["acquisition_currency"]) or "",
                "unit_price": row["unit_price"] if row["unit_price"] is not None else "",
                "price_currency": text_or_none(row["currency"]) or "",
                "est_value": row["est_value"] if row["est_value"] is not None else "",
                "price_date": text_or_none(row["price_date"]) or "",
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
