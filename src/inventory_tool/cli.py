from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from inventory_tool.db import DEFAULT_DB_PATH, initialize_database
from inventory_tool.models import InventoryDefinition, InventoryField, InventoryItem
from inventory_tool.state import clear_active_inventory, get_active_inventory, set_active_inventory
from inventory_tool.service import (
    add_field,
    add_item,
    create_inventory,
    delete_item,
    export_csv,
    get_inventory,
    list_fields,
    list_inventories,
    list_items,
    summary,
    update_field_value,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Track user-defined inventory with SQLite.")
    shared_parser = argparse.ArgumentParser(add_help=False)
    shared_parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path. Defaults to inventory.db in the project root.",
    )
    inventory_parser = argparse.ArgumentParser(add_help=False)
    inventory_parser.add_argument("--inventory", help="Inventory name. Defaults to the active inventory if one is set.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", parents=[shared_parser], help="Create the SQLite database schema.")
    subparsers.add_parser("list-inventories", parents=[shared_parser], help="List configured inventories.")
    subparsers.add_parser("current-inventory", parents=[shared_parser], help="Show the current active inventory.")

    use_parser = subparsers.add_parser("use-inventory", parents=[shared_parser], help="Set the active inventory for future commands.")
    use_parser.add_argument("--inventory", required=True, help="Inventory name to make active.")

    subparsers.add_parser("clear-current-inventory", parents=[shared_parser], help="Clear the active inventory.")

    create_parser = subparsers.add_parser("create-inventory", parents=[shared_parser], help="Create a new inventory.")
    create_parser.add_argument("--name", required=True, help="Inventory name.")
    create_parser.add_argument("--description", help="Optional inventory description.")

    add_field_parser = subparsers.add_parser(
        "add-field",
        parents=[shared_parser, inventory_parser],
        help="Add a custom field to an inventory.",
    )
    add_field_parser.add_argument("--field-name", required=True, help="Field name, such as sku or supplier.")
    add_field_parser.add_argument(
        "--field-type",
        default="string",
        choices=["string", "integer", "number"],
        help="Field type.",
    )
    add_field_parser.add_argument("--required", action="store_true", help="Mark the field as required.")
    add_field_parser.add_argument("--default", help="Optional default value.")

    subparsers.add_parser("list-fields", parents=[shared_parser, inventory_parser], help="List fields for an inventory.")

    add_item_parser = subparsers.add_parser(
        "add-item",
        aliases=["add-card"],
        parents=[shared_parser, inventory_parser],
        help="Add an item to an inventory.",
    )
    add_item_parser.add_argument(
        "--value",
        action="append",
        default=[],
        help="Item field assignment in key=value form. Repeat for multiple fields.",
    )

    list_items_parser = subparsers.add_parser(
        "list-items",
        aliases=["list-cards"],
        parents=[shared_parser],
        help="List items in one inventory or all inventories.",
    )
    list_items_parser.add_argument("--inventory", help="Inventory name.")
    list_items_parser.add_argument("--name", help="Filter by item name substring.")
    list_items_parser.add_argument("--all-inventories", action="store_true", help="List items across all inventories.")

    update_parser = subparsers.add_parser(
        "update-field",
        parents=[shared_parser],
        help="Update one field value for an existing item.",
    )
    update_parser.add_argument("--id", type=int, required=True, help="Inventory record ID.")
    update_parser.add_argument("--field-name", required=True, help="Field name to update.")
    update_parser.add_argument("--value", required=True, help="New value.")

    delete_parser = subparsers.add_parser(
        "delete-item",
        aliases=["delete-card"],
        parents=[shared_parser],
        help="Delete an inventory record.",
    )
    delete_parser.add_argument("--id", type=int, required=True, help="Inventory record ID.")

    summary_parser = subparsers.add_parser("summary", parents=[shared_parser], help="Show inventory totals.")
    summary_parser.add_argument("--inventory", help="Inventory name.")
    summary_parser.add_argument("--all-inventories", action="store_true", help="Summarize items across all inventories.")

    export_parser = subparsers.add_parser("export-csv", parents=[shared_parser], help="Export inventory records to CSV.")
    export_parser.add_argument("--inventory", help="Inventory name.")
    export_parser.add_argument("--all-inventories", action="store_true", help="Export items across all inventories.")
    export_parser.add_argument("--output", default="exports/inventory.csv", help="Output CSV path.")

    return parser


def parse_key_values(assignments: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for assignment in assignments:
        if "=" not in assignment:
            raise ValueError(f"Invalid assignment '{assignment}'. Use key=value.")
        key, value = assignment.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def format_currency(value: float | None) -> str:
    if value is None:
        return "-"
    return f"${value:,.2f}"


def print_inventories(rows: list[dict]) -> None:
    if not rows:
        print("No inventories found.")
        return
    active_inventory = get_active_inventory()
    for row in rows:
        active_marker = " [active]" if row["inventory_name"] == active_inventory else ""
        print(f"{row['inventory_name']}: {row['field_count']} fields{active_marker}")
        if row["description"]:
            print(f"  {row['description']}")


def print_fields(rows: list[dict]) -> None:
    if not rows:
        print("No fields found.")
        return
    for row in rows:
        required = "required" if row["required"] else "optional"
        default = f", default={row['default_value']}" if row["default_value"] is not None else ""
        print(f"{row['field_name']}: {row['field_type']} ({required}{default})")


def print_items(rows: list[dict]) -> None:
    if not rows:
        print("No items found.")
        return
    header = f"{'ID':<4} {'Inventory':<20} {'Name':<24} {'Qty':<6} {'Price':>10} {'Value':>10}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['id']:<4} "
            f"{row['inventory_name'][:20]:<20} "
            f"{row['name'][:24]:<24} "
            f"{row['quantity']:<6} "
            f"{format_currency(row['price']):>10} "
            f"{format_currency(row['market_value']):>10}"
        )


def resolve_inventory_name(args: argparse.Namespace) -> str | None:
    if getattr(args, "all_inventories", False):
        return None
    explicit = getattr(args, "inventory", None)
    if explicit:
        return explicit
    return get_active_inventory()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    db_path = Path(getattr(args, "db", DEFAULT_DB_PATH))

    if args.command == "init-db":
        initialize_database(db_path)
        print(f"Initialized database at {db_path}")
        return 0

    if args.command == "create-inventory":
        inventory = InventoryDefinition(inventory_name=args.name, description=args.description)
        try:
            create_inventory(inventory, db_path=db_path)
        except sqlite3.IntegrityError as exc:
            print("Unable to create inventory. That name already exists.")
            print(str(exc))
            return 1
        set_active_inventory(inventory.inventory_name)
        print(f"Created inventory '{inventory.inventory_name}'")
        print(f"Active inventory set to '{inventory.inventory_name}'")
        return 0

    if args.command == "list-inventories":
        print_inventories(list_inventories(db_path=db_path))
        return 0

    if args.command == "use-inventory":
        if not get_inventory(db_path, args.inventory):
            print(f"Unknown inventory '{args.inventory}'.")
            return 1
        set_active_inventory(args.inventory)
        print(f"Active inventory set to '{args.inventory}'")
        return 0

    if args.command == "current-inventory":
        active_inventory = get_active_inventory()
        if not active_inventory:
            print("No active inventory is set.")
            return 0
        print(active_inventory)
        return 0

    if args.command == "clear-current-inventory":
        clear_active_inventory()
        print("Cleared the active inventory.")
        return 0

    if args.command == "add-field":
        inventory_name = resolve_inventory_name(args)
        if not inventory_name:
            print("No inventory selected. Use --inventory or set one with use-inventory.")
            return 1
        field = InventoryField(
            field_name=args.field_name,
            field_type=args.field_type,
            required=args.required,
            default_value=args.default,
        )
        try:
            add_field(inventory_name, field, db_path=db_path)
        except (sqlite3.IntegrityError, ValueError) as exc:
            print(str(exc))
            return 1
        print(f"Added field '{field.field_name}' to inventory '{inventory_name}'")
        return 0

    if args.command == "list-fields":
        inventory_name = resolve_inventory_name(args)
        if not inventory_name:
            print("No inventory selected. Use --inventory or set one with use-inventory.")
            return 1
        print_fields(list_fields(inventory_name, db_path=db_path))
        return 0

    if args.command in {"add-item", "add-card"}:
        inventory_name = resolve_inventory_name(args)
        if not inventory_name:
            print("No inventory selected. Use --inventory or set one with use-inventory.")
            return 1
        try:
            values = parse_key_values(args.value)
            add_item(InventoryItem(inventory_name=inventory_name, values=values), db_path=db_path)
        except (ValueError, sqlite3.IntegrityError) as exc:
            print(str(exc))
            return 1
        print(f"Added item to inventory '{inventory_name}'")
        return 0

    if args.command in {"list-items", "list-cards"}:
        inventory_name = resolve_inventory_name(args)
        if inventory_name is None and not args.all_inventories:
            print("No inventory selected. Use --inventory, --all-inventories, or set one with use-inventory.")
            return 1
        print_items(list_items(db_path=db_path, inventory_name=inventory_name, name_filter=args.name))
        return 0

    if args.command == "update-field":
        try:
            update_field_value(args.id, args.field_name, args.value, db_path=db_path)
        except ValueError as exc:
            print(str(exc))
            return 1
        print(f"Updated item #{args.id} field '{args.field_name}'")
        return 0

    if args.command in {"delete-item", "delete-card"}:
        delete_item(args.id, db_path=db_path)
        print(f"Deleted record #{args.id}")
        return 0

    if args.command == "summary":
        inventory_name = resolve_inventory_name(args)
        if inventory_name is None and not args.all_inventories:
            print("No inventory selected. Use --inventory, --all-inventories, or set one with use-inventory.")
            return 1
        totals = summary(db_path=db_path, inventory_name=inventory_name)
        print(f"Inventory: {inventory_name or 'all'}")
        print(f"Unique items: {totals['unique_items']}")
        print(f"Total quantity: {totals['total_quantity']}")
        print(f"Total value: {format_currency(totals['total_market_value'])}")
        return 0

    if args.command == "export-csv":
        inventory_name = resolve_inventory_name(args)
        if inventory_name is None and not args.all_inventories:
            print("No inventory selected. Use --inventory, --all-inventories, or set one with use-inventory.")
            return 1
        output = export_csv(args.output, db_path=db_path, inventory_name=inventory_name)
        print(f"Exported inventory to {output}")
        return 0

    parser.error("Unknown command")
    return 2
