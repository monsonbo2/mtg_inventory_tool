from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


from inventory_tool import cli
from inventory_tool.models import InventoryDefinition, InventoryField, InventoryItem
from inventory_tool.service import add_field, add_item, create_inventory, list_fields, list_items, summary


class InventoryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.original_cwd = Path.cwd()
        os.chdir(self.temp_dir.name)
        self.addCleanup(lambda: os.chdir(self.original_cwd))
        self.db_path = Path(self.temp_dir.name) / "test_inventory.db"

    def test_create_inventory_seeds_default_fields(self) -> None:
        create_inventory(
            InventoryDefinition(
                inventory_name="office_supplies",
                description="General office supply inventory",
            ),
            self.db_path,
        )

        fields = list_fields("office_supplies", self.db_path)
        field_names = [field["field_name"] for field in fields]

        self.assertEqual(field_names, ["name", "quantity", "price", "location", "notes"])

    def test_add_item_merges_identical_item_by_quantity(self) -> None:
        create_inventory(InventoryDefinition(inventory_name="office_supplies"), self.db_path)
        add_field("office_supplies", InventoryField(field_name="sku"), self.db_path)

        add_item(
            InventoryItem(
                inventory_name="office_supplies",
                values={
                    "name": "Printer Paper",
                    "quantity": "12",
                    "price": "6.99",
                    "location": "Shelf A",
                    "sku": "PAPER-001",
                },
            ),
            self.db_path,
        )
        add_item(
            InventoryItem(
                inventory_name="office_supplies",
                values={
                    "name": "Printer Paper",
                    "quantity": "3",
                    "price": "6.99",
                    "location": "Shelf A",
                    "sku": "PAPER-001",
                },
            ),
            self.db_path,
        )

        rows = list_items(self.db_path, inventory_name="office_supplies")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Printer Paper")
        self.assertEqual(rows[0]["quantity"], 15)
        self.assertAlmostEqual(rows[0]["market_value"], 104.85, places=2)

    def test_add_item_with_different_field_values_stays_separate(self) -> None:
        create_inventory(InventoryDefinition(inventory_name="office_supplies"), self.db_path)
        add_field("office_supplies", InventoryField(field_name="sku"), self.db_path)

        add_item(
            InventoryItem(
                inventory_name="office_supplies",
                values={
                    "name": "Printer Paper",
                    "quantity": "12",
                    "price": "6.99",
                    "sku": "PAPER-001",
                },
            ),
            self.db_path,
        )
        add_item(
            InventoryItem(
                inventory_name="office_supplies",
                values={
                    "name": "Printer Paper",
                    "quantity": "3",
                    "price": "6.99",
                    "sku": "PAPER-002",
                },
            ),
            self.db_path,
        )

        rows = list_items(self.db_path, inventory_name="office_supplies")

        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["quantity"] for row in rows), 15)

    def test_summary_uses_quantity_and_price_defaults(self) -> None:
        create_inventory(InventoryDefinition(inventory_name="office_supplies"), self.db_path)

        add_item(
            InventoryItem(
                inventory_name="office_supplies",
                values={
                    "name": "Printer Paper",
                    "quantity": "12",
                    "price": "6.99",
                },
            ),
            self.db_path,
        )
        add_item(
            InventoryItem(
                inventory_name="office_supplies",
                values={
                    "name": "Blue Pens",
                    "quantity": "48",
                    "price": "1.25",
                },
            ),
            self.db_path,
        )

        totals = summary(self.db_path, inventory_name="office_supplies")

        self.assertEqual(totals["unique_items"], 2)
        self.assertEqual(totals["total_quantity"], 60)
        self.assertAlmostEqual(totals["total_market_value"], 143.88, places=2)

    def test_cli_active_inventory_flow(self) -> None:
        result = cli.main(
            [
                "create-inventory",
                "--db",
                str(self.db_path),
                "--name",
                "office_supplies",
                "--description",
                "General office supply inventory",
            ]
        )
        self.assertEqual(result, 0)

        result = cli.main(
            [
                "add-field",
                "--db",
                str(self.db_path),
                "--field-name",
                "sku",
                "--field-type",
                "string",
            ]
        )
        self.assertEqual(result, 0)

        result = cli.main(
            [
                "add-item",
                "--db",
                str(self.db_path),
                "--value",
                "name=Printer Paper",
                "--value",
                "quantity=12",
                "--value",
                "price=6.99",
                "--value",
                "sku=PAPER-001",
            ]
        )
        self.assertEqual(result, 0)

        rows = list_items(self.db_path, inventory_name="office_supplies")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Printer Paper")
        self.assertEqual(rows[0]["quantity"], 12)


if __name__ == "__main__":
    unittest.main()
