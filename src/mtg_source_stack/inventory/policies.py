"""Inventory business rules that sit above raw SQL helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from .normalize import load_tags_json, merge_note_text, merge_tags, tags_to_json, text_or_none


def canonical_acquisition(price: Any, currency: Any) -> tuple[Any, str | None] | None:
    if price is None:
        return None
    return price, text_or_none(currency)


def resolve_merge_acquisition(
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    *,
    acquisition_preference: str | None = None,
) -> tuple[Any, str | None]:
    if acquisition_preference not in (None, "source", "target"):
        raise ValueError("keep_acquisition must be one of: source, target.")

    source_acquisition = canonical_acquisition(
        source_item["acquisition_price"],
        source_item["acquisition_currency"],
    )
    target_acquisition = canonical_acquisition(
        target_item["acquisition_price"],
        target_item["acquisition_currency"],
    )

    if target_acquisition is None:
        return source_acquisition or (None, None)
    if source_acquisition is None or source_acquisition == target_acquisition:
        return target_acquisition

    if acquisition_preference == "target":
        return target_acquisition
    if acquisition_preference == "source":
        return source_acquisition

    raise ValueError(
        "Merging rows with different acquisition values requires choosing which acquisition to keep. "
        "Re-run with --keep-acquisition target or --keep-acquisition source."
    )


def build_merged_inventory_item_update(
    source_item: sqlite3.Row,
    target_item: sqlite3.Row,
    *,
    source_quantity: int | None = None,
    acquisition_preference: str | None = None,
) -> dict[str, Any]:
    moved_quantity = int(source_item["quantity"]) if source_quantity is None else int(source_quantity)
    merged_tags = merge_tags(load_tags_json(target_item["tags_json"]), load_tags_json(source_item["tags_json"]))
    merged_acquisition_price, merged_acquisition_currency = resolve_merge_acquisition(
        source_item,
        target_item,
        acquisition_preference=acquisition_preference,
    )
    merged_notes = merge_note_text(
        target_notes=text_or_none(target_item["notes"]),
        source_notes=text_or_none(source_item["notes"]),
    )
    return {
        "quantity": int(target_item["quantity"]) + moved_quantity,
        "acquisition_price": merged_acquisition_price,
        "acquisition_currency": merged_acquisition_currency,
        "notes": merged_notes,
        "tags_json": tags_to_json(merged_tags),
    }


def ensure_add_card_metadata_compatible(
    existing_row: sqlite3.Row,
    *,
    incoming_notes: str | None,
    incoming_acquisition_price: float | None,
    incoming_acquisition_currency: str | None,
) -> None:
    existing_notes = text_or_none(existing_row["notes"])
    if incoming_notes is not None and incoming_notes != existing_notes:
        raise ValueError(
            f"Adding to existing row would overwrite notes on item {existing_row['id']}. "
            "Use set-notes instead."
        )

    incoming_acquisition = canonical_acquisition(
        float(incoming_acquisition_price) if incoming_acquisition_price is not None else None,
        incoming_acquisition_currency,
    )
    existing_acquisition = canonical_acquisition(
        existing_row["acquisition_price"],
        existing_row["acquisition_currency"],
    )
    if incoming_acquisition is not None and incoming_acquisition != existing_acquisition:
        raise ValueError(
            f"Adding to existing row would overwrite acquisition metadata on item {existing_row['id']}. "
            "Use set-acquisition instead."
        )


def row_matches_identity(
    row: sqlite3.Row | dict[str, Any],
    *,
    condition_code: str,
    finish: str,
    language_code: str,
    location: str,
) -> bool:
    return (
        row["condition_code"] == condition_code
        and row["finish"] == finish
        and row["language_code"] == language_code
        and row["location"] == location
    )
