"""Human-readable inventory report formatting helpers."""

from __future__ import annotations

from typing import Any

from .normalize import (
    CSV_PREVIEW_LIMIT,
    format_acquisition_text,
    format_finishes,
    format_optional_text,
    format_tags,
    load_tags_json,
    truncate,
)
from .report_helpers import append_preview_section, render_table


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
            f"Acquisition: {format_acquisition_text(result['acquisition_price'], result['acquisition_currency'])}",
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
            f"Acquisition: {format_acquisition_text(result['acquisition_price'], result['acquisition_currency'])}",
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

    return "\n".join(lines)


def append_snapshot_notice(text: str, snapshot: dict[str, Any] | None) -> str:
    if snapshot is None:
        return text
    return (
        f"{text}\n\n"
        "Safety snapshot created\n\n"
        f"Snapshot: {snapshot['snapshot_path']}\n"
        f"Label: {snapshot['label']}"
    )


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
        "Reviewed inventory pricing finishes",
        "",
        f"Inventory: {result['inventory']}",
        f"Provider: {result['provider']}",
        f"Rows with missing current-price matches: {result['rows_seen']}",
        f"Rows with a single suggested finish: {result['rows_fixable']}",
        "Mode: suggestion only (no changes applied)",
    ]

    if result["suggested_rows"]:
        lines.extend(
            [
                "",
                "Suggested rows",
                "",
                format_price_gap_rows(result["suggested_rows"]),
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
