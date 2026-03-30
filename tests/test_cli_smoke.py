from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tests.common import RepoSmokeTestCase, materialize_fixture_bundle


class CliSmokeTest(RepoSmokeTestCase):
    def test_import_and_personal_inventory_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "lightning_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
                "inventory_import.csv",
                "tcgplayer_collection_export.csv",
                "tcgplayer_seller_export.csv",
            )
            scryfall_path = bundle["scryfall.json"]
            identifiers_path = bundle["identifiers.json"]
            prices_path = bundle["prices.json"]
            csv_path = bundle["inventory_import.csv"]
            tcgplayer_csv_path = bundle["tcgplayer_collection_export.csv"]
            seller_csv_path = bundle["tcgplayer_seller_export.csv"]

            import_output = self.run_importer(
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

            create_output = self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            search_output = self.run_cli(
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning Bolt",
            )
            self.assertIn("Lightning Bolt", search_output)
            self.assertIn("s1", search_output)

            filtered_search_output = self.run_cli(
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

            empty_search_output = self.run_cli(
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning",
                "--rarity",
                "mythic",
            )
            self.assertEqual("No rows found.", empty_search_output)

            add_output = self.run_cli(
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

            set_quantity_output = self.run_cli(
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

            set_tags_output = self.run_cli(
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

            set_location_output = self.run_cli(
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

            set_condition_output = self.run_cli(
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

            set_notes_output = self.run_cli(
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

            owned_output = self.run_cli(
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

            clear_notes_output = self.run_cli(
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

            valuation_output = self.run_cli(
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

            remove_output = self.run_cli(
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

            empty_owned_output = self.run_cli(
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertEqual("No rows found.", empty_owned_output)

            empty_valuation_output = self.run_cli(
                "valuation",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertEqual("No rows found.", empty_valuation_output)

            import_csv_output = self.run_cli(
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

            csv_owned_output = self.run_cli(
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

            filtered_owned_output = self.run_cli(
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

            empty_filtered_owned_output = self.run_cli(
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

            csv_valuation_output = self.run_cli(
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

            tcgplayer_import_output = self.run_cli(
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(tcgplayer_csv_path),
            )
            self.assertIn("Imported inventory rows from CSV", tcgplayer_import_output)
            self.assertIn("Rows imported: 1", tcgplayer_import_output)
            self.assertIn("trade-binder", tcgplayer_import_output)

            inventories_output = self.run_cli(
                "list-inventories",
                "--db",
                str(db_path),
            )
            self.assertIn("trade-binder", inventories_output)
            self.assertIn("Trade Binder", inventories_output)

            tcgplayer_owned_output = self.run_cli(
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

            seller_inventory_output = self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "seller-live",
                "--display-name",
                "Seller Live",
            )
            self.assertIn("Created inventory 'seller-live'", seller_inventory_output)

            seller_import_output = self.run_cli(
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

            seller_owned_output = self.run_cli(
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

            filtered_valuation_output = self.run_cli(
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

            import_output = self.run_importer(
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

            create_output = self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            self.run_cli(
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
            self.run_cli(
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

            location_failure = self.run_failing_cli(
                "set-location",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                str(location_source_item_id),
                "--location",
                "Deck Box",
            )
            self.assertNotEqual(0, location_failure.returncode)
            self.assertIn("--merge", location_failure.stderr)

            location_merge_output = self.run_cli(
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

            self.run_cli(
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
            self.run_cli(
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

            condition_failure = self.run_failing_cli(
                "set-condition",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                str(condition_source_item_id),
                "--condition",
                "NM",
            )
            self.assertNotEqual(0, condition_failure.returncode)
            self.assertIn("--merge", condition_failure.stderr)

            condition_merge_output = self.run_cli(
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
