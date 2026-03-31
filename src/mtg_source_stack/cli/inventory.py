from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from ..db.connection import DEFAULT_DB_PATH
from ..db.snapshots import create_database_snapshot
from ..inventory.csv_import import import_csv
from ..inventory.normalize import (
    DEFAULT_HEALTH_STALE_DAYS,
    DEFAULT_PROVIDER,
    HEALTH_PREVIEW_LIMIT,
    truncate,
)
from ..inventory.reports import (
    EXPORT_CSV_FIELDNAMES,
    append_snapshot_notice,
    format_add_card_result,
    format_export_csv_result,
    format_import_csv_result,
    format_inventory_health_result,
    format_inventory_report_result,
    format_merge_rows_result,
    format_owned_rows,
    format_price_gap_rows,
    format_reconcile_prices_result,
    format_remove_card_result,
    format_set_acquisition_result,
    format_set_condition_result,
    format_set_finish_result,
    format_set_location_result,
    format_set_notes_result,
    format_set_quantity_result,
    format_set_tags_result,
    format_split_row_result,
    print_table,
    write_csv_report,
    write_json_report,
    write_report,
    write_rows_csv,
)
from ..inventory.service import (
    add_card,
    create_inventory,
    export_inventory_csv,
    inventory_health,
    inventory_report,
    list_inventories,
    list_owned_filtered,
    list_price_gaps,
    merge_rows,
    reconcile_prices,
    remove_card,
    search_cards,
    set_acquisition,
    set_condition,
    set_finish,
    set_location,
    set_notes,
    set_quantity,
    set_tags,
    split_row,
    valuation_filtered,
)


def build_snapshot_callback(
    db_path: str | Path,
    *,
    label: str,
) -> tuple[Callable[[], dict[str, Any]], Callable[[], dict[str, Any] | None]]:
    snapshot: dict[str, Any] | None = None

    def ensure_snapshot() -> dict[str, Any]:
        nonlocal snapshot
        if snapshot is None:
            snapshot = create_database_snapshot(db_path, label=label)
        return snapshot

    def current_snapshot() -> dict[str, Any] | None:
        return snapshot

    return ensure_snapshot, current_snapshot


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
    add.add_argument("--acquisition-price", type=float, help="Optional acquisition price per copy.")
    add.add_argument("--acquisition-currency", help="Optional acquisition currency, such as USD.")
    add.add_argument("--notes", help="Optional notes.")
    add.add_argument("--tags", help="Optional comma-separated custom tags, such as commander,trade.")

    csv_import_parser = subparsers.add_parser("import-csv", help="Import inventory rows from a CSV file.")
    csv_import_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    csv_import_parser.add_argument("--csv", required=True, help="CSV file to import.")
    csv_import_parser.add_argument("--inventory", help="Default inventory slug if the CSV does not include one.")
    csv_import_parser.add_argument("--dry-run", action="store_true", help="Preview the import without saving any changes.")
    csv_import_parser.add_argument("--report-out", help="Optional path to save the import report text.")
    csv_import_parser.add_argument("--report-out-json", help="Optional path to save the structured import report JSON.")
    csv_import_parser.add_argument("--report-out-csv", help="Optional path to save a flattened per-row import CSV report.")

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
    set_location_parser.add_argument(
        "--keep-acquisition",
        choices=("target", "source"),
        help="When a merge hits different acquisition values, choose which row's acquisition to keep.",
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
    set_condition_parser.add_argument(
        "--keep-acquisition",
        choices=("target", "source"),
        help="When a merge hits different acquisition values, choose which row's acquisition to keep.",
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
    split_row_parser.add_argument(
        "--keep-acquisition",
        choices=("target", "source"),
        help="When splitting into an existing row with different acquisition values, choose which acquisition to keep.",
    )

    merge_rows_parser = subparsers.add_parser(
        "merge-rows",
        help="Explicitly merge one inventory row into another row for the same printing.",
    )
    merge_rows_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    merge_rows_parser.add_argument("--inventory", required=True, help="Inventory slug.")
    merge_rows_parser.add_argument("--source-item-id", required=True, type=int, help="Source row id to remove.")
    merge_rows_parser.add_argument("--target-item-id", required=True, type=int, help="Target row id to keep.")
    merge_rows_parser.add_argument(
        "--keep-acquisition",
        choices=("target", "source"),
        help="When rows have different acquisition values, choose which row's acquisition to keep.",
    )

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
        help="Review finish mismatches and suggest manual updates when exactly one priced finish is available.",
    )
    reconcile.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    reconcile.add_argument("--inventory", required=True, help="Inventory slug.")
    reconcile.add_argument("--provider", default=DEFAULT_PROVIDER, help="Price provider, such as tcgplayer.")
    reconcile.add_argument(
        "--apply",
        action="store_true",
        help="Deprecated. reconcile-prices is suggestion-only and no longer updates finish values.",
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
            before_write = None
            if not args.dry_run:
                before_write, get_snapshot = build_snapshot_callback(
                    args.db,
                    label=f"before_import_csv_{Path(args.csv).stem}",
                )
            result = import_csv(
                args.db,
                csv_path=args.csv,
                default_inventory=args.inventory,
                dry_run=args.dry_run,
                before_write=before_write,
            )
            if not args.dry_run:
                snapshot = get_snapshot()
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
            before_write = None
            if args.merge:
                before_write, get_snapshot = build_snapshot_callback(
                    args.db,
                    label=f"before_set_location_merge_item_{args.item_id}",
                )
            result = set_location(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                location=None if args.clear else args.location,
                merge=args.merge,
                keep_acquisition=args.keep_acquisition,
                before_write=before_write,
            )
            if args.merge:
                snapshot = get_snapshot()
            print(append_snapshot_notice(format_set_location_result(result), snapshot))
            return

        if args.command == "set-condition":
            snapshot = None
            before_write = None
            if args.merge:
                before_write, get_snapshot = build_snapshot_callback(
                    args.db,
                    label=f"before_set_condition_merge_item_{args.item_id}",
                )
            result = set_condition(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                condition_code=args.condition,
                merge=args.merge,
                keep_acquisition=args.keep_acquisition,
                before_write=before_write,
            )
            if args.merge:
                snapshot = get_snapshot()
            print(append_snapshot_notice(format_set_condition_result(result), snapshot))
            return

        if args.command == "set-acquisition":
            before_write, get_snapshot = build_snapshot_callback(
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
                before_write=before_write,
            )
            snapshot = get_snapshot()
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
            before_write, get_snapshot = build_snapshot_callback(
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
                keep_acquisition=args.keep_acquisition,
                before_write=before_write,
            )
            snapshot = get_snapshot()
            print(append_snapshot_notice(format_split_row_result(result), snapshot))
            return

        if args.command == "merge-rows":
            before_write, get_snapshot = build_snapshot_callback(
                args.db,
                label=f"before_merge_rows_{args.source_item_id}_into_{args.target_item_id}",
            )
            result = merge_rows(
                args.db,
                inventory_slug=args.inventory,
                source_item_id=args.source_item_id,
                target_item_id=args.target_item_id,
                keep_acquisition=args.keep_acquisition,
                before_write=before_write,
            )
            snapshot = get_snapshot()
            print(append_snapshot_notice(format_merge_rows_result(result), snapshot))
            return

        if args.command == "remove-card":
            before_write, get_snapshot = build_snapshot_callback(
                args.db,
                label=f"before_remove_card_item_{args.item_id}",
            )
            result = remove_card(
                args.db,
                inventory_slug=args.inventory,
                item_id=args.item_id,
                before_write=before_write,
            )
            snapshot = get_snapshot()
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
            result = reconcile_prices(
                args.db,
                inventory_slug=args.inventory,
                provider=args.provider,
                apply_changes=args.apply,
            )
            print(format_reconcile_prices_result(result))
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
