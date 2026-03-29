from __future__ import annotations

import gzip
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
IMPORTER = REPO_ROOT / "MtG Source Stack" / "mvp_importer.py"
CLI = REPO_ROOT / "MtG Source Stack" / "personal_inventory_cli.py"
STACK_DIR = REPO_ROOT / "MtG Source Stack"
if str(STACK_DIR) not in sys.path:
    sys.path.insert(0, str(STACK_DIR))

from mtg_source_stack.mvp_importer import import_scryfall_cards, initialize_database


class MtGSourceStackSmokeTest(unittest.TestCase):
    def run_cmd(self, *args: str) -> str:
        result = subprocess.run(
            [sys.executable, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def test_import_and_personal_inventory_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"
            csv_path = tmp / "inventory_import.csv"
            tcgplayer_csv_path = tmp / "tcgplayer_collection_export.csv"
            seller_csv_path = tmp / "tcgplayer_seller_export.csv"

            scryfall_payload = [
                {
                    "id": "s1",
                    "oracle_id": "o1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "mana_cost": "{R}",
                    "type_line": "Instant",
                    "oracle_text": "Lightning Bolt deals 3 damage to any target.",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                    "cardmarket_id": 752712,
                }
            ]
            identifiers_payload = {
                "data": {
                    "uuid-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "s1",
                            "tcgplayerProductId": "534658",
                            "cardKingdomId": "12345",
                            "mcmId": "752712",
                            "cardsphereId": "98765",
                        },
                    }
                }
            }
            prices_payload = {
                "data": {
                    "uuid-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.92}},
                                "buylist": {"normal": {"2026-03-27": 1.10}},
                            }
                        }
                    }
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            import_output = self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.assertIn("import-scryfall: seen=1 written=1 skipped=0", import_output)
            self.assertIn("import-identifiers: seen=1 written=1 skipped=0", import_output)
            self.assertIn("import-prices: seen=1 written=2 skipped=0", import_output)

            create_output = self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            search_output = self.run_cmd(
                str(CLI),
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning Bolt",
            )
            self.assertIn("Lightning Bolt", search_output)
            self.assertIn("s1", search_output)

            filtered_search_output = self.run_cmd(
                str(CLI),
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning",
                "--set-code",
                "lea",
                "--rarity",
                "common",
                "--finish",
                "normal",
                "--lang",
                "en",
            )
            self.assertIn("Lightning Bolt", filtered_search_output)

            empty_search_output = self.run_cmd(
                str(CLI),
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning",
                "--rarity",
                "mythic",
            )
            self.assertEqual("No rows found.", empty_search_output)

            add_output = self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "4",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Red Binder",
                "--tags",
                "burn,trade",
            )
            self.assertIn("Added to inventory", add_output)
            self.assertIn("Card: Lightning Bolt", add_output)
            self.assertIn("Printing: Limited Edition Alpha (LEA #161)", add_output)
            self.assertIn("Quantity now: 4", add_output)
            self.assertIn("Location: Red Binder", add_output)
            self.assertIn("Tags: burn, trade", add_output)

            set_quantity_output = self.run_cmd(
                str(CLI),
                "set-quantity",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--quantity",
                "2",
            )
            self.assertIn("Updated inventory quantity", set_quantity_output)
            self.assertIn("Previous quantity: 4", set_quantity_output)
            self.assertIn("Quantity now: 2", set_quantity_output)
            self.assertIn("Tags: burn, trade", set_quantity_output)

            set_tags_output = self.run_cmd(
                str(CLI),
                "set-tags",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--tags",
                "deck, staples",
            )
            self.assertIn("Updated card tags", set_tags_output)
            self.assertIn("Previous tags: burn, trade", set_tags_output)
            self.assertIn("Tags now: deck, staples", set_tags_output)

            set_location_output = self.run_cmd(
                str(CLI),
                "set-location",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--location",
                "Deck Box",
            )
            self.assertIn("Updated card location", set_location_output)
            self.assertIn("Previous location: Red Binder", set_location_output)
            self.assertIn("Location now: Deck Box", set_location_output)

            set_condition_output = self.run_cmd(
                str(CLI),
                "set-condition",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--condition",
                "LP",
            )
            self.assertIn("Updated card condition", set_condition_output)
            self.assertIn("Previous condition: NM", set_condition_output)
            self.assertIn("Condition now: LP", set_condition_output)

            set_notes_output = self.run_cmd(
                str(CLI),
                "set-notes",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--notes",
                "Needs fresh inner sleeve",
            )
            self.assertIn("Updated card notes", set_notes_output)
            self.assertIn("Previous notes: (none)", set_notes_output)
            self.assertIn("Notes now: Needs fresh inner sleeve", set_notes_output)

            owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Lightning Bolt", owned_output)
            self.assertIn("deck, staples", owned_output)
            self.assertIn("Deck Box", owned_output)
            self.assertIn("Needs fresh inner sleeve", owned_output)
            self.assertIn("5.84", owned_output)

            clear_notes_output = self.run_cmd(
                str(CLI),
                "set-notes",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--clear",
            )
            self.assertIn("Updated card notes", clear_notes_output)
            self.assertIn("Previous notes: Needs fresh inner sleeve", clear_notes_output)
            self.assertIn("Notes now: (none)", clear_notes_output)

            valuation_output = self.run_cmd(
                str(CLI),
                "valuation",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("tcgplayer", valuation_output)
            self.assertIn("5.84", valuation_output)

            remove_output = self.run_cmd(
                str(CLI),
                "remove-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
            )
            self.assertIn("Removed from inventory", remove_output)
            self.assertIn("Removed quantity: 2", remove_output)
            self.assertIn("Card: Lightning Bolt", remove_output)
            self.assertIn("Tags: deck, staples", remove_output)

            empty_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertEqual("No rows found.", empty_owned_output)

            empty_valuation_output = self.run_cmd(
                str(CLI),
                "valuation",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertEqual("No rows found.", empty_valuation_output)

            csv_path.write_text(
                "name,set,number,qty,cond,finish,location,tags,notes\n"
                "Lightning Bolt,lea,161,3,NM,normal,Blue Binder,bulk import,CSV import row\n",
                encoding="utf-8",
            )

            import_csv_output = self.run_cmd(
                str(CLI),
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(csv_path),
                "--inventory",
                "personal",
            )
            self.assertIn("Imported inventory rows from CSV", import_csv_output)
            self.assertIn("Rows seen: 1", import_csv_output)
            self.assertIn("Rows imported: 1", import_csv_output)
            self.assertIn("Lightning Bolt", import_csv_output)
            self.assertIn("bulk import", import_csv_output)

            csv_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Lightning Bolt", csv_owned_output)
            self.assertIn("Blue Binder", csv_owned_output)
            self.assertIn("bulk import", csv_owned_output)
            self.assertIn("8.76", csv_owned_output)

            filtered_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--set-code",
                "lea",
                "--rarity",
                "common",
                "--finish",
                "normal",
                "--condition",
                "NM",
                "--location",
                "Blue",
                "--tag",
                "bulk import",
            )
            self.assertIn("Lightning Bolt", filtered_owned_output)
            self.assertIn("bulk import", filtered_owned_output)
            self.assertIn("common", filtered_owned_output)

            empty_filtered_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--tag",
                "commander staple",
            )
            self.assertEqual("No rows found.", empty_filtered_owned_output)

            csv_valuation_output = self.run_cmd(
                str(CLI),
                "valuation",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("tcgplayer", csv_valuation_output)
            self.assertIn("8.76", csv_valuation_output)

            tcgplayer_csv_path.write_text(
                "Collection Name,Created At,Product ID,Condition,Language,Variant,Quantity\n"
                "Trade Binder,2026-03-27 10:00:00,534658,Near Mint,English,,2\n",
                encoding="utf-8",
            )

            tcgplayer_import_output = self.run_cmd(
                str(CLI),
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(tcgplayer_csv_path),
            )
            self.assertIn("Imported inventory rows from CSV", tcgplayer_import_output)
            self.assertIn("Rows imported: 1", tcgplayer_import_output)
            self.assertIn("trade-binder", tcgplayer_import_output)

            inventories_output = self.run_cmd(
                str(CLI),
                "list-inventories",
                "--db",
                str(db_path),
            )
            self.assertIn("trade-binder", inventories_output)
            self.assertIn("Trade Binder", inventories_output)

            tcgplayer_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "trade-binder",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Lightning Bolt", tcgplayer_owned_output)
            self.assertIn("NM", tcgplayer_owned_output)
            self.assertIn("5.84", tcgplayer_owned_output)

            seller_inventory_output = self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "seller-live",
                "--display-name",
                "Seller Live",
            )
            self.assertIn("Created inventory 'seller-live'", seller_inventory_output)

            seller_csv_path.write_text(
                "TCGplayer ID,Product Line,Set Name,Product Name,Number,Rarity,Condition,Total Quantity,Add to Quantity,TCG Marketplace Price\n"
                "534658,Magic,Limited Edition Alpha,Lightning Bolt,161,Common,Near Mint,3,-1,2.92\n",
                encoding="utf-8",
            )

            seller_import_output = self.run_cmd(
                str(CLI),
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(seller_csv_path),
                "--inventory",
                "seller-live",
            )
            self.assertIn("Imported inventory rows from CSV", seller_import_output)
            self.assertIn("Rows imported: 1", seller_import_output)
            self.assertIn("seller-live", seller_import_output)

            seller_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "seller-live",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Lightning Bolt", seller_owned_output)
            self.assertIn("2", seller_owned_output)
            self.assertIn("5.84", seller_owned_output)

            filtered_valuation_output = self.run_cmd(
                str(CLI),
                "valuation",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--set-code",
                "lea",
                "--rarity",
                "common",
                "--tag",
                "bulk import",
            )
            self.assertIn("tcgplayer", filtered_valuation_output)
            self.assertIn("8.76", filtered_valuation_output)

    def test_set_location_and_condition_support_explicit_merge_on_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "merge-1",
                    "oracle_id": "merge-oracle-1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                }
            ]
            identifiers_payload = {
                "data": {
                    "uuid-merge-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "merge-1",
                            "tcgplayerProductId": "534658",
                        },
                    }
                }
            }
            prices_payload = {
                "data": {
                    "uuid-merge-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.92}},
                            }
                        }
                    }
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            import_output = self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.assertIn("import-prices: seen=1 written=1 skipped=0", import_output)

            create_output = self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "merge-1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--notes",
                "Source location row",
                "--tags",
                "source-tag",
                "--acquisition-price",
                "1.5",
                "--acquisition-currency",
                "USD",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "merge-1",
                "--quantity",
                "3",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Deck Box",
                "--notes",
                "Target location row",
                "--tags",
                "target-tag",
                "--acquisition-price",
                "2.0",
                "--acquisition-currency",
                "USD",
            )

            connection = sqlite3.connect(db_path)
            location_source_item_id = connection.execute(
                "SELECT id FROM inventory_items WHERE location = 'Binder A'"
            ).fetchone()[0]
            location_target_item_id = connection.execute(
                "SELECT id FROM inventory_items WHERE location = 'Deck Box'"
            ).fetchone()[0]
            connection.close()

            location_failure = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "set-location",
                    "--db",
                    str(db_path),
                    "--inventory",
                    "personal",
                    "--item-id",
                    str(location_source_item_id),
                    "--location",
                    "Deck Box",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, location_failure.returncode)
            self.assertIn("--merge", location_failure.stderr)

            location_merge_output = self.run_cmd(
                str(CLI),
                "set-location",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                str(location_source_item_id),
                "--location",
                "Deck Box",
                "--merge",
            )
            self.assertIn("Merge applied: yes", location_merge_output)
            self.assertIn(f"Merged source item ID: {location_source_item_id}", location_merge_output)
            self.assertIn(f"Active item ID: {location_target_item_id}", location_merge_output)
            self.assertIn("Quantity now: 5", location_merge_output)

            connection = sqlite3.connect(db_path)
            location_row = connection.execute(
                """
                SELECT id, quantity, location, notes, tags_json, acquisition_price, acquisition_currency
                FROM inventory_items
                WHERE id = ?
                """,
                (location_target_item_id,),
            ).fetchone()
            location_row_count = connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
            connection.close()

            self.assertEqual(1, location_row_count)
            self.assertEqual(location_target_item_id, location_row[0])
            self.assertEqual(5, location_row[1])
            self.assertEqual("Deck Box", location_row[2])
            self.assertIn("Target location row", location_row[3])
            self.assertIn("Source location row", location_row[3])
            self.assertIn(
                f"Merged source acquisition from item {location_source_item_id}: 1.5 USD",
                location_row[3],
            )
            self.assertCountEqual(["target-tag", "source-tag"], json.loads(location_row[4]))
            self.assertEqual(2.0, float(location_row[5]))
            self.assertEqual("USD", location_row[6])

            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "merge-1",
                "--quantity",
                "1",
                "--condition",
                "LP",
                "--finish",
                "normal",
                "--location",
                "Sideboard",
                "--notes",
                "Source condition row",
                "--tags",
                "condition-source",
                "--acquisition-price",
                "4.0",
                "--acquisition-currency",
                "USD",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "merge-1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Sideboard",
                "--notes",
                "Target condition row",
                "--tags",
                "condition-target",
                "--acquisition-price",
                "5.0",
                "--acquisition-currency",
                "USD",
            )

            connection = sqlite3.connect(db_path)
            condition_source_item_id = connection.execute(
                "SELECT id FROM inventory_items WHERE location = 'Sideboard' AND condition_code = 'LP'"
            ).fetchone()[0]
            condition_target_item_id = connection.execute(
                "SELECT id FROM inventory_items WHERE location = 'Sideboard' AND condition_code = 'NM'"
            ).fetchone()[0]
            connection.close()

            condition_failure = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "set-condition",
                    "--db",
                    str(db_path),
                    "--inventory",
                    "personal",
                    "--item-id",
                    str(condition_source_item_id),
                    "--condition",
                    "NM",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, condition_failure.returncode)
            self.assertIn("--merge", condition_failure.stderr)

            condition_merge_output = self.run_cmd(
                str(CLI),
                "set-condition",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                str(condition_source_item_id),
                "--condition",
                "NM",
                "--merge",
            )
            self.assertIn("Merge applied: yes", condition_merge_output)
            self.assertIn(f"Merged source item ID: {condition_source_item_id}", condition_merge_output)
            self.assertIn(f"Active item ID: {condition_target_item_id}", condition_merge_output)
            self.assertIn("Quantity now: 3", condition_merge_output)

            connection = sqlite3.connect(db_path)
            condition_row = connection.execute(
                """
                SELECT id, quantity, condition_code, location, notes, tags_json, acquisition_price, acquisition_currency
                FROM inventory_items
                WHERE id = ?
                """,
                (condition_target_item_id,),
            ).fetchone()
            final_row_count = connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
            connection.close()

            self.assertEqual(2, final_row_count)
            self.assertEqual(condition_target_item_id, condition_row[0])
            self.assertEqual(3, condition_row[1])
            self.assertEqual("NM", condition_row[2])
            self.assertEqual("Sideboard", condition_row[3])
            self.assertIn("Target condition row", condition_row[4])
            self.assertIn("Source condition row", condition_row[4])
            self.assertIn(
                f"Merged source acquisition from item {condition_source_item_id}: 4 USD",
                condition_row[4],
            )
            self.assertCountEqual(["condition-target", "condition-source"], json.loads(condition_row[5]))
            self.assertEqual(5.0, float(condition_row[6]))
            self.assertEqual("USD", condition_row[7])

    def test_initialize_database_migrates_existing_inventory_items_for_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.db"

            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE inventory_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    inventory_id INTEGER NOT NULL,
                    scryfall_id TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 0,
                    condition_code TEXT NOT NULL DEFAULT 'NM',
                    finish TEXT NOT NULL DEFAULT 'normal',
                    language_code TEXT NOT NULL DEFAULT 'en',
                    location TEXT NOT NULL DEFAULT '',
                    acquisition_price NUMERIC,
                    acquisition_currency TEXT,
                    notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO inventory_items (
                    inventory_id,
                    scryfall_id,
                    quantity,
                    condition_code,
                    finish,
                    language_code,
                    location
                )
                VALUES (1, 'legacy-card', 1, 'NM', 'normal', 'en', '');
                """
            )
            connection.commit()
            connection.close()

            initialize_database(db_path)

            migrated = sqlite3.connect(db_path)
            columns = {row[1] for row in migrated.execute("PRAGMA table_info(inventory_items)")}
            tags_value = migrated.execute("SELECT tags_json FROM inventory_items").fetchone()[0]
            migrated.close()

            self.assertIn("tags_json", columns)
            self.assertEqual("[]", tags_value)

    def test_import_scryfall_uses_face_oracle_id_when_top_level_oracle_id_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "reversible.db"
            scryfall_path = tmp / "reversible.json"

            scryfall_payload = [
                {
                    "id": "reversible-1",
                    "oracle_id": None,
                    "name": "Temple Garden // Temple Garden",
                    "set": "ecl",
                    "set_name": "Lorwyn Eclipsed",
                    "collector_number": "351",
                    "lang": "en",
                    "layout": "reversible_card",
                    "rarity": "rare",
                    "colors": [],
                    "color_identity": ["G", "W"],
                    "finishes": ["nonfoil"],
                    "card_faces": [
                        {"name": "Temple Garden", "oracle_id": "face-oracle-1"},
                        {"name": "Temple Garden", "oracle_id": "face-oracle-1"},
                    ],
                }
            ]
            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")

            initialize_database(db_path)
            stats = import_scryfall_cards(db_path, scryfall_path)

            connection = sqlite3.connect(db_path)
            row = connection.execute(
                "SELECT scryfall_id, oracle_id, name, set_code, collector_number FROM mtg_cards"
            ).fetchone()
            connection.close()

            self.assertEqual(1, stats.rows_seen)
            self.assertEqual(1, stats.rows_written)
            self.assertEqual(0, stats.rows_skipped)
            self.assertEqual(
                ("reversible-1", "face-oracle-1", "Temple Garden // Temple Garden", "ecl", "351"),
                row,
            )

    def test_sync_bulk_downloads_and_imports_from_override_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            cache_dir = tmp / "cache"
            metadata_path = tmp / "scryfall_bulk_metadata.json"
            scryfall_bulk_path = tmp / "default_cards.json"
            identifiers_path = tmp / "AllIdentifiers.json.gz"
            prices_path = tmp / "AllPricesToday.json.gz"

            scryfall_payload = [
                {
                    "id": "sync-1",
                    "oracle_id": "sync-oracle-1",
                    "name": "Sync Test Card",
                    "set": "syn",
                    "set_name": "Sync Set",
                    "collector_number": "42",
                    "lang": "en",
                    "rarity": "rare",
                    "released_at": "2026-01-01",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 444,
                }
            ]
            identifiers_payload = {
                "data": {
                    "uuid-sync-1": {
                        "name": "Sync Test Card",
                        "setCode": "syn",
                        "identifiers": {
                            "scryfallId": "sync-1",
                            "tcgplayerProductId": "444",
                        },
                    }
                }
            }
            prices_payload = {
                "data": {
                    "uuid-sync-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 9.99}},
                            }
                        }
                    }
                }
            }
            metadata_payload = {
                "data": [
                    {
                        "type": "default_cards",
                        "download_uri": scryfall_bulk_path.as_uri(),
                    }
                ]
            }

            scryfall_bulk_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            metadata_path.write_text(json.dumps(metadata_payload), encoding="utf-8")
            with gzip.open(identifiers_path, "wt", encoding="utf-8") as handle:
                json.dump(identifiers_payload, handle)
            with gzip.open(prices_path, "wt", encoding="utf-8") as handle:
                json.dump(prices_payload, handle)

            sync_output = self.run_cmd(
                str(IMPORTER),
                "sync-bulk",
                "--db",
                str(db_path),
                "--cache-dir",
                str(cache_dir),
                "--scryfall-metadata-url",
                metadata_path.as_uri(),
                "--mtgjson-identifiers-url",
                identifiers_path.as_uri(),
                "--mtgjson-prices-url",
                prices_path.as_uri(),
            )

            self.assertIn("sync-bulk completed", sync_output)
            self.assertIn("import-scryfall: seen=1 written=1 skipped=0", sync_output)
            self.assertIn("import-identifiers: seen=1 written=1 skipped=0", sync_output)
            self.assertIn("import-prices: seen=1 written=1 skipped=0", sync_output)
            self.assertTrue((cache_dir / "scryfall_default_cards.json").exists())
            self.assertTrue((cache_dir / "AllIdentifiers.json.gz").exists())
            self.assertTrue((cache_dir / "AllPricesToday.json.gz").exists())

            connection = sqlite3.connect(db_path)
            mtg_cards = connection.execute("SELECT COUNT(*) FROM mtg_cards").fetchone()[0]
            price_snapshots = connection.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
            uuid_count = connection.execute(
                "SELECT COUNT(*) FROM mtg_cards WHERE mtgjson_uuid IS NOT NULL"
            ).fetchone()[0]
            connection.close()

            self.assertEqual(1, mtg_cards)
            self.assertEqual(1, price_snapshots)
            self.assertEqual(1, uuid_count)

    def test_reconcile_prices_updates_finish_when_one_priced_finish_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "s2",
                    "oracle_id": "o2",
                    "name": "Shiny Bird",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "7",
                    "lang": "en",
                    "rarity": "rare",
                    "released_at": "2026-01-01",
                    "colors": ["G"],
                    "color_identity": ["G"],
                    "finishes": ["foil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 222,
                }
            ]
            identifiers_payload = {
                "data": {
                    "uuid-2": {
                        "name": "Shiny Bird",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "s2",
                            "tcgplayerProductId": "222",
                        },
                    }
                }
            }
            prices_payload = {
                "data": {
                    "uuid-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"foil": {"2026-03-27": 5.00}},
                            }
                        }
                    }
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            import_output = self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.assertIn("import-prices: seen=1 written=1 skipped=0", import_output)

            create_output = self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            add_output = self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s2",
                "--quantity",
                "1",
                "--finish",
                "normal",
            )
            self.assertIn("Finish: normal", add_output)

            gap_output = self.run_cmd(
                str(CLI),
                "price-gaps",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Shiny Bird", gap_output)
            self.assertIn("foil", gap_output)
            self.assertIn("single priced finish", gap_output)

            preview_output = self.run_cmd(
                str(CLI),
                "reconcile-prices",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Rows updated: 0", preview_output)
            self.assertIn("Mode: preview only", preview_output)

            reconcile_output = self.run_cmd(
                str(CLI),
                "reconcile-prices",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--apply",
            )
            self.assertIn("Rows updated: 1", reconcile_output)
            self.assertIn("Shiny Bird", reconcile_output)

            owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Shiny Bird", owned_output)
            self.assertIn("foil", owned_output)
            self.assertIn("5.0", owned_output)

    def test_import_csv_auto_adjusts_single_catalog_finish_and_reports_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"
            csv_path = tmp / "archidekt_like.csv"

            scryfall_payload = [
                {
                    "id": "foil-only-1",
                    "oracle_id": "oracle-foil-only-1",
                    "name": "Shiny Bird",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "7",
                    "lang": "en",
                    "rarity": "rare",
                    "released_at": "2026-01-01",
                    "colors": ["G"],
                    "color_identity": ["G"],
                    "finishes": ["foil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 222,
                }
            ]
            identifiers_payload = {
                "data": {
                    "uuid-foil-only-1": {
                        "name": "Shiny Bird",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "foil-only-1",
                            "tcgplayerProductId": "222",
                        },
                    }
                }
            }
            prices_payload = {
                "data": {
                    "uuid-foil-only-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"foil": {"2026-03-27": 5.00}},
                            }
                        }
                    }
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")
            csv_path.write_text(
                "Quantity,Name,Condition,Scryfall ID\n"
                "1,Shiny Bird,NM,foil-only-1\n",
                encoding="utf-8",
            )

            import_output = self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.assertIn("import-prices: seen=1 written=1 skipped=0", import_output)

            create_output = self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            csv_import_output = self.run_cmd(
                str(CLI),
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(csv_path),
                "--inventory",
                "personal",
            )
            self.assertIn("Rows imported: 1", csv_import_output)
            self.assertIn("Finish adjustments: 1", csv_import_output)
            self.assertIn("Automatic finish adjustments", csv_import_output)
            self.assertIn("Shiny Bird", csv_import_output)
            self.assertIn("single catalog finish", csv_import_output)

            owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Shiny Bird", owned_output)
            self.assertIn("foil", owned_output)
            self.assertIn("5.0", owned_output)

    def test_import_csv_dry_run_writes_report_and_leaves_db_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"
            csv_path = tmp / "inventory_import.csv"
            report_path = tmp / "reports" / "import_preview.txt"
            report_json_path = tmp / "reports" / "import_preview.json"
            report_csv_path = tmp / "reports" / "import_preview.csv"

            scryfall_payload = [
                {
                    "id": "dry-run-card-1",
                    "oracle_id": "dry-run-oracle-1",
                    "name": "Preview Bolt",
                    "set": "prv",
                    "set_name": "Preview Set",
                    "collector_number": "1",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2026-01-01",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 333,
                }
            ]
            identifiers_payload = {
                "data": {
                    "uuid-dry-run-1": {
                        "name": "Preview Bolt",
                        "setCode": "prv",
                        "identifiers": {
                            "scryfallId": "dry-run-card-1",
                            "tcgplayerProductId": "333",
                        },
                    }
                }
            }
            prices_payload = {
                "data": {
                    "uuid-dry-run-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.25}},
                            }
                        }
                    }
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")
            csv_path.write_text(
                "name,set,number,qty,cond,location\n"
                "Preview Bolt,prv,1,2,NM,Preview Binder\n",
                encoding="utf-8",
            )

            import_output = self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.assertIn("import-prices: seen=1 written=1 skipped=0", import_output)

            create_output = self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            preview_output = self.run_cmd(
                str(CLI),
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(csv_path),
                "--inventory",
                "personal",
                "--dry-run",
                "--report-out",
                str(report_path),
                "--report-out-json",
                str(report_json_path),
                "--report-out-csv",
                str(report_csv_path),
            )
            self.assertIn("Rows imported: 1", preview_output)
            self.assertIn("Mode: dry run (no changes saved)", preview_output)
            self.assertIn("Text report saved to:", preview_output)
            self.assertIn("JSON report saved to:", preview_output)
            self.assertIn("CSV report saved to:", preview_output)
            self.assertTrue(report_path.exists())
            self.assertTrue(report_json_path.exists())
            self.assertTrue(report_csv_path.exists())

            report_text = report_path.read_text(encoding="utf-8")
            self.assertIn("Imported inventory rows from CSV", report_text)
            self.assertIn("Mode: dry run (no changes saved)", report_text)
            self.assertIn("Preview Bolt", report_text)

            report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
            self.assertEqual(True, report_json["dry_run"])
            self.assertEqual(1, report_json["rows_written"])
            self.assertEqual("Preview Bolt", report_json["imported_rows"][0]["card_name"])

            report_csv_text = report_csv_path.read_text(encoding="utf-8")
            self.assertIn("csv_path,dry_run,default_inventory,csv_row,inventory,card_name", report_csv_text)
            self.assertIn("Preview Bolt", report_csv_text)
            self.assertIn("True", report_csv_text)

            owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertEqual("No rows found.", owned_output)

    def test_remove_card_creates_snapshot_and_restore_snapshot_recovers_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "snapshot-card-1",
                    "oracle_id": "snapshot-oracle-1",
                    "name": "Snapshot Bolt",
                    "set": "snp",
                    "set_name": "Snapshot Set",
                    "collector_number": "11",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2026-01-01",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 9001,
                }
            ]
            identifiers_payload = {
                "data": {
                    "uuid-snapshot-1": {
                        "name": "Snapshot Bolt",
                        "setCode": "snp",
                        "identifiers": {
                            "scryfallId": "snapshot-card-1",
                            "tcgplayerProductId": "9001",
                        },
                    }
                }
            }
            prices_payload = {
                "data": {
                    "uuid-snapshot-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.50}},
                            }
                        }
                    }
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            import_output = self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.assertIn("snapshot:", import_output)

            self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "snapshot-card-1",
                "--quantity",
                "2",
                "--finish",
                "normal",
            )

            remove_output = self.run_cmd(
                str(CLI),
                "remove-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
            )
            self.assertIn("Safety snapshot created", remove_output)
            self.assertIn("Removed from inventory", remove_output)

            snapshot_dir = tmp / "_snapshots" / "collection"
            snapshots = sorted(snapshot_dir.glob("*.sqlite3"))
            self.assertTrue(snapshots)
            remove_snapshot = next(
                snapshot for snapshot in snapshots if "before_remove_card_item_1" in snapshot.name
            )

            list_output = self.run_cmd(
                str(IMPORTER),
                "list-snapshots",
                "--db",
                str(db_path),
            )
            self.assertIn(remove_snapshot.name, list_output)
            self.assertIn("before_remove_card_item_1", list_output)

            empty_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertEqual("No rows found.", empty_owned_output)

            restore_output = self.run_cmd(
                str(IMPORTER),
                "restore-snapshot",
                "--db",
                str(db_path),
                "--snapshot",
                remove_snapshot.name,
            )
            self.assertIn("Restored snapshot", restore_output)
            self.assertIn("pre_restore_snapshot:", restore_output)

            restored_owned_output = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Snapshot Bolt", restored_owned_output)
            self.assertIn("3.0", restored_owned_output)

    def test_inventory_health_reports_missing_data_and_stale_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "health-card-1",
                    "oracle_id": "health-oracle-1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                },
                {
                    "id": "health-card-2",
                    "oracle_id": "health-oracle-2",
                    "name": "Shiny Bird",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "7",
                    "lang": "en",
                    "rarity": "rare",
                    "released_at": "2026-01-01",
                    "colors": ["G"],
                    "color_identity": ["G"],
                    "finishes": ["foil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 222,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-health-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "health-card-1",
                            "tcgplayerProductId": "534658",
                        },
                    },
                    "uuid-health-2": {
                        "name": "Shiny Bird",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "health-card-2",
                            "tcgplayerProductId": "222",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-health-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2020-01-01": 2.92}},
                            }
                        }
                    },
                    "uuid-health-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"foil": {"2026-03-27": 5.00}},
                            }
                        }
                    },
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "health-card-1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--notes",
                "Merged source acquisition from item 99: 1.5 USD",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "health-card-1",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "health-card-2",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Deck Box",
                "--tags",
                "foil project",
            )

            health_output = self.run_cmd(
                str(CLI),
                "inventory-health",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--stale-days",
                "30",
                "--limit",
                "5",
            )
            self.assertIn("Inventory health report", health_output)
            self.assertIn("Rows missing current prices: 1", health_output)
            self.assertIn("Rows missing location: 1", health_output)
            self.assertIn("Rows missing tags: 2", health_output)
            self.assertIn("Rows with merged acquisition notes: 1", health_output)
            self.assertIn("Rows with stale prices: 2", health_output)
            self.assertIn("Duplicate-like groups: 1", health_output)
            self.assertIn("Missing current-price matches", health_output)
            self.assertIn("Missing location", health_output)
            self.assertIn("Missing tags", health_output)
            self.assertIn("Merged acquisition notes", health_output)
            self.assertIn("Stale prices", health_output)
            self.assertIn("Duplicate-like groups", health_output)
            self.assertIn("Lightning Bolt", health_output)
            self.assertIn("Shiny Bird", health_output)
            self.assertIn("2020-01-01", health_output)

    def test_set_acquisition_split_row_and_merge_rows_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "edit-card-1",
                    "oracle_id": "edit-oracle-1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                },
                {
                    "id": "edit-card-2",
                    "oracle_id": "edit-oracle-2",
                    "name": "Counterspell",
                    "set": "7ed",
                    "set_name": "Seventh Edition",
                    "collector_number": "73",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2001-04-11",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 123456,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-edit-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "edit-card-1",
                            "tcgplayerProductId": "534658",
                        },
                    },
                    "uuid-edit-2": {
                        "name": "Counterspell",
                        "setCode": "7ed",
                        "identifiers": {
                            "scryfallId": "edit-card-2",
                            "tcgplayerProductId": "123456",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-edit-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.92}},
                            }
                        }
                    },
                    "uuid-edit-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.10}},
                            }
                        }
                    },
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "edit-card-1",
                "--quantity",
                "4",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--notes",
                "Main playset",
                "--tags",
                "deck",
            )

            set_acquisition_output = self.run_cmd(
                str(CLI),
                "set-acquisition",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--price",
                "1.75",
                "--currency",
                "usd",
            )
            self.assertIn("Safety snapshot created", set_acquisition_output)
            self.assertIn("Updated card acquisition", set_acquisition_output)
            self.assertIn("Previous acquisition: (none)", set_acquisition_output)
            self.assertIn("Acquisition now: 1.75 USD", set_acquisition_output)

            split_output = self.run_cmd(
                str(CLI),
                "split-row",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--quantity",
                "1",
                "--location",
                "Deck Box",
            )
            self.assertIn("Safety snapshot created", split_output)
            self.assertIn("Split inventory row", split_output)
            self.assertIn("Moved quantity: 1", split_output)
            self.assertIn("Source quantity now: 3", split_output)
            self.assertIn("Target item ID: 2", split_output)
            self.assertIn("Target quantity now: 1", split_output)
            self.assertIn("Merged into existing row: no", split_output)

            owned_after_split = self.run_cmd(
                str(CLI),
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Binder A", owned_after_split)
            self.assertIn("Deck Box", owned_after_split)

            merge_output = self.run_cmd(
                str(CLI),
                "merge-rows",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--source-item-id",
                "2",
                "--target-item-id",
                "1",
            )
            self.assertIn("Safety snapshot created", merge_output)
            self.assertIn("Merged inventory rows", merge_output)
            self.assertIn("Source item ID: 2", merge_output)
            self.assertIn("Source quantity removed: 1", merge_output)
            self.assertIn("Target item ID: 1", merge_output)
            self.assertIn("Target previous quantity: 3", merge_output)
            self.assertIn("Quantity now: 4", merge_output)
            self.assertIn("Acquisition: 1.75 USD", merge_output)

            connection = sqlite3.connect(db_path)
            rows = connection.execute(
                """
                SELECT id, quantity, location, acquisition_price, acquisition_currency
                FROM inventory_items
                WHERE scryfall_id = 'edit-card-1'
                ORDER BY id
                """
            ).fetchall()
            connection.close()

            self.assertEqual([(1, 4, "Binder A", 1.75, "USD")], rows)

            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "edit-card-2",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Blue Binder",
            )

            merge_failure = subprocess.run(
                [
                    sys.executable,
                    str(CLI),
                    "merge-rows",
                    "--db",
                    str(db_path),
                    "--inventory",
                    "personal",
                    "--source-item-id",
                    "3",
                    "--target-item-id",
                    "1",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, merge_failure.returncode)
            self.assertIn("same printing", merge_failure.stderr)

    def test_export_csv_and_inventory_report_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"
            export_path = tmp / "exports" / "lightning_only.csv"
            report_text_path = tmp / "reports" / "inventory_report.txt"
            report_json_path = tmp / "reports" / "inventory_report.json"
            report_csv_path = tmp / "reports" / "inventory_report_rows.csv"

            scryfall_payload = [
                {
                    "id": "report-card-1",
                    "oracle_id": "report-oracle-1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                },
                {
                    "id": "report-card-2",
                    "oracle_id": "report-oracle-2",
                    "name": "Counterspell",
                    "set": "7ed",
                    "set_name": "Seventh Edition",
                    "collector_number": "73",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2001-04-11",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 123456,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-report-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "report-card-1",
                            "tcgplayerProductId": "534658",
                        },
                    },
                    "uuid-report-2": {
                        "name": "Counterspell",
                        "setCode": "7ed",
                        "identifiers": {
                            "scryfallId": "report-card-2",
                            "tcgplayerProductId": "123456",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-report-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.92}},
                            }
                        }
                    },
                    "uuid-report-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.10}},
                            }
                        }
                    },
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_cmd(
                str(IMPORTER),
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.run_cmd(
                str(CLI),
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-card-1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Red Binder",
                "--tags",
                "burn",
                "--acquisition-price",
                "1.25",
                "--acquisition-currency",
                "USD",
            )
            self.run_cmd(
                str(CLI),
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-card-2",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "",
            )

            export_output = self.run_cmd(
                str(CLI),
                "export-csv",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--query",
                "Lightning",
                "--output",
                str(export_path),
            )
            self.assertIn("Exported inventory rows to CSV", export_output)
            self.assertIn("Rows exported: 1", export_output)
            self.assertIn(str(export_path), export_output)
            export_text = export_path.read_text(encoding="utf-8")
            self.assertIn("inventory,provider,item_id,scryfall_id,card_name", export_text)
            self.assertIn("Lightning Bolt", export_text)
            self.assertNotIn("Counterspell", export_text)

            report_output = self.run_cmd(
                str(CLI),
                "inventory-report",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--limit",
                "5",
                "--report-out",
                str(report_text_path),
                "--report-out-json",
                str(report_json_path),
                "--report-out-csv",
                str(report_csv_path),
            )
            self.assertIn("Inventory report", report_output)
            self.assertIn("Valuation totals", report_output)
            self.assertIn("Tracked acquisition totals", report_output)
            self.assertIn("Top holdings by estimated value", report_output)
            self.assertIn("Health summary", report_output)
            self.assertIn("Text report saved to:", report_output)
            self.assertIn("JSON report saved to:", report_output)
            self.assertIn("CSV report saved to:", report_output)
            self.assertTrue(report_text_path.exists())
            self.assertTrue(report_json_path.exists())
            self.assertTrue(report_csv_path.exists())

            report_text = report_text_path.read_text(encoding="utf-8")
            self.assertIn("Item rows: 2", report_text)
            self.assertIn("Total cards: 3", report_text)
            self.assertIn("Missing location rows: 1", report_text)
            self.assertIn("Missing tag rows: 1", report_text)

            report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
            self.assertEqual("personal", report_json["inventory"])
            self.assertEqual("tcgplayer", report_json["provider"])
            self.assertEqual(2, report_json["summary"]["item_rows"])
            self.assertEqual(3, report_json["summary"]["total_cards"])
            self.assertEqual(2, len(report_json["rows"]))

            report_csv_text = report_csv_path.read_text(encoding="utf-8")
            self.assertIn("Lightning Bolt", report_csv_text)
            self.assertIn("Counterspell", report_csv_text)


if __name__ == "__main__":
    unittest.main()
