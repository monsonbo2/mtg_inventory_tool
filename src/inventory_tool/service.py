from __future__ import annotations

import csv
from pathlib import Path

from inventory_tool.db import DEFAULT_DB_PATH, DEFAULT_FIELDS, connect, initialize_database
from inventory_tool.models import InventoryDefinition, InventoryField, InventoryItem


def create_inventory(inventory: InventoryDefinition, db_path: str | Path = DEFAULT_DB_PATH) -> int:
    initialize_database(db_path)
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            INSERT INTO inventories (inventory_name, description)
            VALUES (?, ?)
            """,
            (inventory.inventory_name, inventory.description),
        )
        inventory_id = int(cursor.lastrowid)

        for display_order, (field_name, field_type, required, default_value) in enumerate(DEFAULT_FIELDS, start=1):
            connection.execute(
                """
                INSERT INTO inventory_fields (
                    inventory_id,
                    field_name,
                    field_type,
                    required,
                    default_value,
                    display_order
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (inventory_id, field_name, field_type, required, default_value, display_order),
            )

        connection.commit()
        return inventory_id


def list_inventories(db_path: str | Path = DEFAULT_DB_PATH) -> list[dict]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                inventories.id,
                inventories.inventory_name,
                inventories.description,
                inventories.created_at,
                COUNT(inventory_fields.id) AS field_count
            FROM inventories
            LEFT JOIN inventory_fields ON inventory_fields.inventory_id = inventories.id
            GROUP BY inventories.id, inventories.inventory_name, inventories.description, inventories.created_at
            ORDER BY inventories.inventory_name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_inventory(db_path: str | Path, inventory_name: str) -> dict | None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT id, inventory_name, description, created_at
            FROM inventories
            WHERE inventory_name = ?
            """,
            (inventory_name,),
        ).fetchone()
    return dict(row) if row else None


def add_field(
    inventory_name: str,
    field: InventoryField,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> int:
    initialize_database(db_path)
    with connect(db_path) as connection:
        inventory = connection.execute(
            "SELECT id FROM inventories WHERE inventory_name = ?",
            (inventory_name,),
        ).fetchone()
        if not inventory:
            raise ValueError(f"Unknown inventory '{inventory_name}'. Create it first with create-inventory.")

        next_order = connection.execute(
            "SELECT COALESCE(MAX(display_order), 0) + 1 AS next_order FROM inventory_fields WHERE inventory_id = ?",
            (inventory["id"],),
        ).fetchone()["next_order"]

        cursor = connection.execute(
            """
            INSERT INTO inventory_fields (
                inventory_id,
                field_name,
                field_type,
                required,
                default_value,
                display_order
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                inventory["id"],
                field.field_name,
                field.field_type,
                1 if field.required else 0,
                field.default_value,
                field.display_order or next_order,
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_fields(inventory_name: str, db_path: str | Path = DEFAULT_DB_PATH) -> list[dict]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT
                inventory_fields.id,
                inventory_fields.field_name,
                inventory_fields.field_type,
                inventory_fields.required,
                inventory_fields.default_value,
                inventory_fields.display_order
            FROM inventory_fields
            JOIN inventories ON inventories.id = inventory_fields.inventory_id
            WHERE inventories.inventory_name = ?
            ORDER BY inventory_fields.display_order, inventory_fields.field_name
            """,
            (inventory_name,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_item(item: InventoryItem, db_path: str | Path = DEFAULT_DB_PATH) -> int:
    initialize_database(db_path)
    with connect(db_path) as connection:
        inventory = connection.execute(
            "SELECT id FROM inventories WHERE inventory_name = ?",
            (item.inventory_name,),
        ).fetchone()
        if not inventory:
            raise ValueError(f"Unknown inventory '{item.inventory_name}'. Create it first with create-inventory.")

        field_rows = connection.execute(
            """
            SELECT id, field_name, field_type, required, default_value
            FROM inventory_fields
            WHERE inventory_id = ?
            ORDER BY display_order, field_name
            """,
            (inventory["id"],),
        ).fetchall()
        fields = {row["field_name"]: row for row in field_rows}

        unknown_fields = sorted(set(item.values) - set(fields))
        if unknown_fields:
            raise ValueError(f"Unknown fields for inventory '{item.inventory_name}': {', '.join(unknown_fields)}")

        normalized_values: dict[str, str | None] = {}
        for field_name, row in fields.items():
            raw_value = item.values.get(field_name, row["default_value"])
            if row["required"] and (raw_value is None or str(raw_value).strip() == ""):
                raise ValueError(f"Missing required field '{field_name}' for inventory '{item.inventory_name}'.")
            if raw_value is not None:
                validate_field_value(field_name, str(raw_value), row["field_type"])
                normalized_values[field_name] = str(raw_value)
            else:
                normalized_values[field_name] = None

        existing_item_id = find_matching_item_id(connection, inventory["id"], normalized_values)
        if existing_item_id is not None:
            existing_quantity = int(normalized_values.get("quantity") or "0")
            merge_quantities(connection, existing_item_id, fields["quantity"]["id"], existing_quantity)
            connection.commit()
            return existing_item_id

        cursor = connection.execute(
            """
            INSERT INTO inventory_items (inventory_id)
            VALUES (?)
            """,
            (inventory["id"],),
        )
        item_id = int(cursor.lastrowid)

        for field_name, value in normalized_values.items():
            connection.execute(
                """
                INSERT INTO inventory_item_values (item_id, field_id, value_text)
                VALUES (?, ?, ?)
                """,
                (item_id, fields[field_name]["id"], value),
            )

        connection.commit()
        return item_id


def find_matching_item_id(
    connection,
    inventory_id: int,
    normalized_values: dict[str, str | None],
) -> int | None:
    item_rows = connection.execute(
        """
        SELECT id
        FROM inventory_items
        WHERE inventory_id = ?
        ORDER BY id
        """,
        (inventory_id,),
    ).fetchall()

    comparable_values = {key: value for key, value in normalized_values.items() if key != "quantity"}

    for item_row in item_rows:
        stored_rows = connection.execute(
            """
            SELECT inventory_fields.field_name, inventory_item_values.value_text
            FROM inventory_item_values
            JOIN inventory_fields ON inventory_fields.id = inventory_item_values.field_id
            WHERE inventory_item_values.item_id = ?
            """,
            (item_row["id"],),
        ).fetchall()
        stored_values = {row["field_name"]: row["value_text"] for row in stored_rows}
        stored_comparable = {key: value for key, value in stored_values.items() if key != "quantity"}
        if stored_comparable == comparable_values:
            return int(item_row["id"])

    return None


def merge_quantities(connection, item_id: int, quantity_field_id: int, quantity_to_add: int) -> None:
    quantity_row = connection.execute(
        """
        SELECT value_text
        FROM inventory_item_values
        WHERE item_id = ? AND field_id = ?
        """,
        (item_id, quantity_field_id),
    ).fetchone()
    current_quantity = int(quantity_row["value_text"]) if quantity_row and quantity_row["value_text"] else 0
    new_quantity = current_quantity + quantity_to_add
    connection.execute(
        """
        UPDATE inventory_item_values
        SET value_text = ?
        WHERE item_id = ? AND field_id = ?
        """,
        (str(new_quantity), item_id, quantity_field_id),
    )
    connection.execute(
        """
        UPDATE inventory_items
        SET updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (item_id,),
    )


def validate_field_value(field_name: str, raw_value: str, field_type: str) -> None:
    if field_type == "integer":
        int(raw_value)
        return
    if field_type == "number":
        float(raw_value)
        return


def list_items(
    db_path: str | Path = DEFAULT_DB_PATH,
    inventory_name: str | None = None,
    name_filter: str | None = None,
) -> list[dict]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        item_rows = connection.execute(
            """
            SELECT
                inventory_items.id,
                inventories.inventory_name
            FROM inventory_items
            JOIN inventories ON inventories.id = inventory_items.inventory_id
            WHERE (? IS NULL OR inventories.inventory_name = ?)
            ORDER BY inventories.inventory_name, inventory_items.id
            """,
            (inventory_name, inventory_name),
        ).fetchall()

        rows: list[dict] = []
        for item_row in item_rows:
            values = connection.execute(
                """
                SELECT
                    inventory_fields.field_name,
                    inventory_item_values.value_text
                FROM inventory_item_values
                JOIN inventory_fields ON inventory_fields.id = inventory_item_values.field_id
                WHERE inventory_item_values.item_id = ?
                ORDER BY inventory_fields.display_order, inventory_fields.field_name
                """,
                (item_row["id"],),
            ).fetchall()
            value_map = {row["field_name"]: row["value_text"] for row in values}
            item_name = value_map.get("name", "")
            if name_filter and name_filter.lower() not in item_name.lower():
                continue
            quantity_text = value_map.get("quantity") or "0"
            price_text = value_map.get("price") or "0"
            quantity = int(quantity_text)
            price = float(price_text)
            rows.append(
                {
                    "id": item_row["id"],
                    "inventory_name": item_row["inventory_name"],
                    "values": value_map,
                    "name": item_name,
                    "quantity": quantity,
                    "price": price,
                    "market_value": round(quantity * price, 2),
                }
            )
    return rows


def update_field_value(
    item_id: int,
    field_name: str,
    value: str,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        field_row = connection.execute(
            """
            SELECT inventory_fields.id, inventory_fields.field_type
            FROM inventory_items
            JOIN inventories ON inventories.id = inventory_items.inventory_id
            JOIN inventory_fields ON inventory_fields.inventory_id = inventories.id
            WHERE inventory_items.id = ? AND inventory_fields.field_name = ?
            """,
            (item_id, field_name),
        ).fetchone()
        if not field_row:
            raise ValueError(f"Field '{field_name}' is not defined for item #{item_id}.")
        validate_field_value(field_name, value, field_row["field_type"])
        connection.execute(
            """
            UPDATE inventory_item_values
            SET value_text = ?
            WHERE item_id = ? AND field_id = ?
            """,
            (value, item_id, field_row["id"]),
        )
        connection.execute(
            """
            UPDATE inventory_items
            SET updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (item_id,),
        )
        connection.commit()


def delete_item(item_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    initialize_database(db_path)
    with connect(db_path) as connection:
        connection.execute("DELETE FROM inventory_item_values WHERE item_id = ?", (item_id,))
        connection.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        connection.commit()


def summary(db_path: str | Path = DEFAULT_DB_PATH, inventory_name: str | None = None) -> dict:
    rows = list_items(db_path=db_path, inventory_name=inventory_name)
    return {
        "unique_items": len(rows),
        "total_quantity": sum(row["quantity"] for row in rows),
        "total_market_value": round(sum(row["market_value"] for row in rows), 2),
    }


def export_csv(
    output_path: str | Path,
    db_path: str | Path = DEFAULT_DB_PATH,
    inventory_name: str | None = None,
) -> Path:
    rows = list_items(db_path=db_path, inventory_name=inventory_name)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["id", "inventory_name"]
    extra_fieldnames = sorted({field for row in rows for field in row["values"].keys()})
    fieldnames.extend(extra_fieldnames)
    fieldnames.append("market_value")

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            export_row = {"id": row["id"], "inventory_name": row["inventory_name"], "market_value": row["market_value"]}
            export_row.update(row["values"])
            writer.writerow(export_row)

    return output
