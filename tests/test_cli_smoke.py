"""End-to-end CLI smoke tests for the main inventory workflows."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from tests.common import RepoSmokeTestCase, materialize_fixture_bundle
from mtg_source_stack.db.schema import initialize_database, load_schema_sql


class CliSmokeTest(RepoSmokeTestCase):
    def test_missing_database_read_commands_fail_without_creating_a_new_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "missing.db"

            # Read-only commands should fail cleanly on a missing path instead of
            # helpfully creating an empty database behind the user's back.
            result = self.run_failing_cli(
                "list-inventories",
                "--db",
                str(db_path),
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("does not exist", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(db_path.exists())

    def test_create_inventory_duplicate_slug_returns_a_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            # The first create establishes the happy path; the second call checks
            # that uniqueness failures stay user-friendly.
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )

            result = self.run_failing_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("Inventory 'personal' already exists.", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

    def test_read_commands_require_explicit_migration_for_legacy_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.db"

            # Simulate a pre-migration database that has the old runtime schema
            # but no schema_migrations tracking yet.
            connection = sqlite3.connect(db_path)
            connection.executescript(load_schema_sql())
            connection.commit()
            connection.close()

            result = self.run_failing_cli(
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning Bolt",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("migrate-db", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

            # Read-only commands should not stamp schema state on their own.
            raw = sqlite3.connect(db_path)
            schema_migrations_exists = raw.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()[0]
            raw.close()
            self.assertEqual(0, schema_migrations_exists)

            migrate_output = self.run_importer(
                "migrate-db",
                "--db",
                str(db_path),
            )
            self.assertIn("Migrated database", migrate_output)
            self.assertIn("0001 mvp base", migrate_output)
            self.assertIn("0002 add tags json", migrate_output)
            self.assertIn("0003 add inventory audit log", migrate_output)
            self.assertIn("0004 add card search fts", migrate_output)
            self.assertIn("0005 normalize price snapshot finishes", migrate_output)
            self.assertIn("0006 add inventory memberships", migrate_output)

            search_output = self.run_cli(
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning Bolt",
            )
            self.assertEqual("No rows found.", search_output)

    def test_import_csv_missing_file_fails_without_creating_db_or_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            csv_path = tmp / "missing.csv"

            result = self.run_failing_cli(
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(csv_path),
                "--inventory",
                "personal",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn(f"Could not read CSV file '{csv_path}'", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(db_path.exists())
            self.assertFalse((tmp / "_snapshots").exists())

    def test_remove_card_validation_failure_does_not_create_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"

            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )

            result = self.run_failing_cli(
                "remove-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "99",
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("No inventory row found", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse((tmp / "_snapshots").exists())

    def test_inventory_membership_cli_can_grant_list_and_revoke_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )

            grant_output = self.run_cli(
                "grant-inventory-membership",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--actor-id",
                "alice@example.com",
                "--role",
                "viewer",
            )
            self.assertIn("Granted role 'viewer' on inventory 'personal' to actor 'alice@example.com'", grant_output)

            update_output = self.run_cli(
                "grant-inventory-membership",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--actor-id",
                "alice@example.com",
                "--role",
                "editor",
            )
            self.assertIn("Granted role 'editor' on inventory 'personal' to actor 'alice@example.com'", update_output)

            self.run_cli(
                "grant-inventory-membership",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--actor-id",
                "bob@example.com",
                "--role",
                "owner",
            )

            list_output = self.run_cli(
                "list-inventory-memberships",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
            )
            self.assertIn("actor_id", list_output)
            self.assertIn("alice@example.com", list_output)
            self.assertIn("editor", list_output)
            self.assertIn("bob@example.com", list_output)
            self.assertIn("owner", list_output)

            revoke_output = self.run_cli(
                "revoke-inventory-membership",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--actor-id",
                "alice@example.com",
            )
            self.assertIn("Revoked role 'editor' on inventory 'personal' from actor 'alice@example.com'", revoke_output)

            final_list = self.run_cli(
                "list-inventory-memberships",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
            )
            self.assertNotIn("alice@example.com", final_list)
            self.assertIn("bob@example.com", final_list)

    def test_inventory_audit_log_tracks_simple_item_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "lightning_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(bundle["scryfall.json"]),
                "--identifiers-json",
                str(bundle["identifiers.json"]),
                "--prices-json",
                str(bundle["prices.json"]),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "3",
                "--location",
                "Binder A",
                "--tags",
                "burn",
                "--acquisition-price",
                "1.25",
                "--acquisition-currency",
                "USD",
            )
            self.run_cli(
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
            self.run_cli(
                "set-notes",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--notes",
                "Checked after deck night",
            )
            self.run_cli(
                "remove-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
            )

            connection = sqlite3.connect(db_path)
            rows = connection.execute(
                """
                SELECT action, item_id, before_json, after_json, metadata_json
                FROM inventory_audit_log
                ORDER BY id
                """
            ).fetchall()
            connection.close()

            self.assertEqual(["add_card", "set_quantity", "set_notes", "remove_card"], [row[0] for row in rows])

            add_before, add_after, add_metadata = rows[0][2], json.loads(rows[0][3]), json.loads(rows[0][4])
            self.assertIsNone(add_before)
            self.assertEqual("Lightning Bolt", add_after["card_name"])
            self.assertEqual(3, add_after["quantity"])
            self.assertEqual("1.25", add_after["acquisition_price"])
            self.assertEqual({"mode": "create"}, add_metadata)

            set_qty_before = json.loads(rows[1][2])
            set_qty_after = json.loads(rows[1][3])
            self.assertEqual(3, set_qty_before["quantity"])
            self.assertEqual(2, set_qty_after["quantity"])

            set_notes_before = json.loads(rows[2][2])
            set_notes_after = json.loads(rows[2][3])
            self.assertIsNone(set_notes_before["notes"])
            self.assertEqual("Checked after deck night", set_notes_after["notes"])

            remove_before, remove_after = json.loads(rows[3][2]), rows[3][3]
            self.assertEqual(2, remove_before["quantity"])
            self.assertIsNone(remove_after)

    def test_inventory_audit_log_tracks_location_merge_as_delete_plus_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "lightning_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(bundle["scryfall.json"]),
                "--identifiers-json",
                str(bundle["identifiers.json"]),
                "--prices-json",
                str(bundle["prices.json"]),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "2",
                "--location",
                "Binder A",
                "--notes",
                "Source row",
                "--tags",
                "source-tag",
                "--acquisition-price",
                "1.50",
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
                "s1",
                "--quantity",
                "1",
                "--location",
                "Deck Box",
                "--notes",
                "Target row",
                "--tags",
                "target-tag",
                "--acquisition-price",
                "2.00",
                "--acquisition-currency",
                "USD",
            )
            self.run_cli(
                "set-location",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--location",
                "Deck Box",
                "--merge",
                "--keep-acquisition",
                "target",
            )

            connection = sqlite3.connect(db_path)
            rows = connection.execute(
                """
                SELECT item_id, before_json, after_json, metadata_json
                FROM inventory_audit_log
                WHERE action = 'set_location'
                ORDER BY id
                """
            ).fetchall()
            connection.close()

            self.assertEqual(2, len(rows))
            source_row = next(row for row in rows if row[0] == 1)
            target_row = next(row for row in rows if row[0] == 2)

            source_before = json.loads(source_row[1])
            source_after = source_row[2]
            source_metadata = json.loads(source_row[3])
            self.assertEqual("Binder A", source_before["location"])
            self.assertIsNone(source_after)
            self.assertTrue(source_metadata["merged"])
            self.assertEqual(2, source_metadata["target_item_id"])

            target_before = json.loads(target_row[1])
            target_after = json.loads(target_row[2])
            target_metadata = json.loads(target_row[3])
            self.assertEqual(1, target_before["quantity"])
            self.assertEqual(3, target_after["quantity"])
            self.assertEqual("Deck Box", target_after["location"])
            self.assertTrue(target_metadata["merged"])
            self.assertEqual(1, target_metadata["source_item_id"])

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

            # Build the smallest realistic card catalog so the rest of the test
            # can walk through the CLI the way an operator would.
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

            # Basic and filtered searches confirm that the imported card metadata
            # is queryable before any inventory rows exist.
            search_output = self.run_cli(
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Lightning Bolt",
            )
            self.assertIn("Lightning Bolt", search_output)
            self.assertIn("s1", search_output)

            reordered_search_output = self.run_cli(
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Bolt Lightning",
            )
            self.assertIn("Lightning Bolt", reordered_search_output)

            prefix_search_output = self.run_cli(
                "search-cards",
                "--db",
                str(db_path),
                "--query",
                "Light Bol",
            )
            self.assertIn("Lightning Bolt", prefix_search_output)

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

            # Mutate the same inventory row a few different ways to verify the
            # edit commands preserve surrounding fields and report diffs back.
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

            # Clearing notes exercises the explicit "remove metadata" path rather
            # than only the "set metadata" path above.
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

            # After the manual row is removed, the rest of the flow switches to
            # CSV imports to cover bulk ingestion and valuation/report filters.
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

            # Collection-export imports can create inventories implicitly, while
            # seller exports can also target an already-created inventory.
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

    def test_add_card_same_row_accumulates_quantity_and_tags_without_rewriting_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "lightning_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(bundle["scryfall.json"]),
                "--identifiers-json",
                str(bundle["identifiers.json"]),
                "--prices-json",
                str(bundle["prices.json"]),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--notes",
                "Main copy",
                "--tags",
                "alpha",
                "--acquisition-price",
                "1.25",
                "--acquisition-currency",
                "USD",
            )

            # Re-adding the same identity should behave like a quantity bump,
            # not like a stealth metadata edit path.
            add_again_output = self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--tags",
                "beta",
            )
            self.assertIn("Quantity now: 3", add_again_output)
            self.assertIn("Tags: alpha, beta", add_again_output)

            note_failure = self.run_failing_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--notes",
                "Replacement note",
            )
            self.assertNotEqual(0, note_failure.returncode)
            self.assertIn("Use set-notes instead", note_failure.stderr)
            self.assertNotIn("Traceback", note_failure.stderr)

            acquisition_failure = self.run_failing_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--acquisition-price",
                "2.50",
                "--acquisition-currency",
                "USD",
            )
            self.assertNotEqual(0, acquisition_failure.returncode)
            self.assertIn("Use set-acquisition instead", acquisition_failure.stderr)
            self.assertNotIn("Traceback", acquisition_failure.stderr)

            connection = sqlite3.connect(db_path)
            row = connection.execute(
                """
                SELECT quantity, notes, tags_json, acquisition_price, acquisition_currency
                FROM inventory_items
                WHERE id = 1
                """
            ).fetchone()
            connection.close()

            self.assertEqual(3, row[0])
            self.assertEqual("Main copy", row[1])
            self.assertCountEqual(["alpha", "beta"], json.loads(row[2]))
            self.assertEqual(1.25, float(row[3]))
            self.assertEqual("USD", row[4])

    def test_add_card_accepts_oracle_id_and_infers_resolved_printing_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            initialize_database(db_path)

            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                INSERT INTO inventories (slug, display_name)
                VALUES ('personal', 'Personal Collection')
                """
            )
            connection.executemany(
                """
                INSERT INTO mtg_cards (
                    scryfall_id,
                    oracle_id,
                    name,
                    set_code,
                    set_name,
                    collector_number,
                    lang,
                    released_at,
                    finishes_json
                )
                VALUES (?, 'cli-oracle-1', 'CLI Oracle Card', ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "cli-oracle-ja",
                        "neo",
                        "Kamigawa: Neon Dynasty",
                        "81",
                        "ja",
                        "2024-02-01",
                        '["foil"]',
                    ),
                    (
                        "cli-oracle-en",
                        "neo",
                        "Kamigawa: Neon Dynasty",
                        "82",
                        "en",
                        "2024-01-01",
                        '["nonfoil","foil"]',
                    ),
                ],
            )
            connection.commit()
            connection.close()

            add_output = self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--oracle-id",
                "cli-oracle-1",
                "--lang",
                "ja",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "foil",
            )
            self.assertIn("CLI Oracle Card", add_output)

            connection = sqlite3.connect(db_path)
            row = connection.execute(
                """
                SELECT scryfall_id, language_code
                FROM inventory_items
                """
            ).fetchone()
            connection.close()

            self.assertEqual("cli-oracle-ja", row[0])
            self.assertEqual("ja", row[1])

            failure = self.run_failing_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--oracle-id",
                "cli-oracle-1",
                "--lang",
                "ja",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "foil",
                "--language-code",
                "en",
            )
            self.assertNotEqual(0, failure.returncode)
            self.assertIn("language_code must match the resolved printing language", failure.stderr)
            self.assertNotIn("Traceback", failure.stderr)

    def test_add_card_rejects_acquisition_currency_without_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "lightning_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(bundle["scryfall.json"]),
                "--identifiers-json",
                str(bundle["identifiers.json"]),
                "--prices-json",
                str(bundle["prices.json"]),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )

            result = self.run_failing_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "1",
                "--acquisition-currency",
                "USD",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Cannot store an acquisition currency without an acquisition price", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

            connection = sqlite3.connect(db_path)
            row_count = connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
            connection.close()

            self.assertEqual(0, row_count)

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

            # Start with two otherwise-identical rows that only differ by
            # location, so changing the location creates a merge collision.
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

            # Without `--merge`, the command should stop and explain why it would
            # collapse two rows into one.
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

            # Once the user opts into merging, conflicting acquisition metadata
            # must still be resolved explicitly instead of silently picking one.
            location_acquisition_failure = self.run_failing_cli(
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
            self.assertNotEqual(0, location_acquisition_failure.returncode)
            self.assertIn("--keep-acquisition", location_acquisition_failure.stderr)

            connection = sqlite3.connect(db_path)
            location_rows_after_failure = connection.execute(
                """
                SELECT id, quantity, location
                FROM inventory_items
                ORDER BY id
                """
            ).fetchall()
            connection.close()

            self.assertEqual(
                [
                    (location_source_item_id, 2, "Binder A"),
                    (location_target_item_id, 3, "Deck Box"),
                ],
                location_rows_after_failure,
            )

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
                "--keep-acquisition",
                "target",
            )
            self.assertIn("Merge applied: yes", location_merge_output)
            self.assertIn(f"Merged source item ID: {location_source_item_id}", location_merge_output)
            self.assertIn(f"Active item ID: {location_target_item_id}", location_merge_output)
            self.assertIn("Quantity now: 5", location_merge_output)

            # Inspect the stored row directly to prove that notes, tags, and
            # acquisition data were merged instead of silently discarded.
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
            self.assertNotIn("Merged source acquisition", location_row[3])
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

            # Repeat the same collision story for condition changes because the
            # merge semantics should be identical across mutating commands.
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

            condition_acquisition_failure = self.run_failing_cli(
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
            self.assertNotEqual(0, condition_acquisition_failure.returncode)
            self.assertIn("--keep-acquisition", condition_acquisition_failure.stderr)

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
                "--keep-acquisition",
                "source",
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
            self.assertNotIn("Merged source acquisition", condition_row[4])
            self.assertCountEqual(["condition-target", "condition-source"], json.loads(condition_row[5]))
            self.assertEqual(4.0, float(condition_row[6]))
            self.assertEqual("USD", condition_row[7])

    def test_split_row_requires_explicit_acquisition_choice_when_merging_into_existing_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "lightning_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(bundle["scryfall.json"]),
                "--identifiers-json",
                str(bundle["identifiers.json"]),
                "--prices-json",
                str(bundle["prices.json"]),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "3",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--acquisition-price",
                "1.75",
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
                "s1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Deck Box",
                "--acquisition-price",
                "2.25",
                "--acquisition-currency",
                "USD",
            )

            # Splitting into an existing identity is really a merge operation,
            # so conflicting acquisition data should be resolved before any
            # quantity changes are allowed to happen.
            split_failure = self.run_failing_cli(
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
            self.assertNotEqual(0, split_failure.returncode)
            self.assertIn("--keep-acquisition", split_failure.stderr)

            connection = sqlite3.connect(db_path)
            rows_after_failure = connection.execute(
                """
                SELECT id, quantity, location, acquisition_price, acquisition_currency
                FROM inventory_items
                ORDER BY id
                """
            ).fetchall()
            connection.close()

            self.assertEqual(
                [
                    (1, 3, "Binder A", 1.75, "USD"),
                    (2, 2, "Deck Box", 2.25, "USD"),
                ],
                rows_after_failure,
            )

            split_output = self.run_cli(
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
                "--keep-acquisition",
                "source",
            )
            self.assertIn("Split inventory row", split_output)
            self.assertIn("Merged into existing row: yes", split_output)

            connection = sqlite3.connect(db_path)
            rows_after_success = connection.execute(
                """
                SELECT id, quantity, location, acquisition_price, acquisition_currency
                FROM inventory_items
                ORDER BY id
                """
            ).fetchall()
            connection.close()

            self.assertEqual(
                [
                    (1, 2, "Binder A", 1.75, "USD"),
                    (2, 3, "Deck Box", 1.75, "USD"),
                ],
                rows_after_success,
            )
