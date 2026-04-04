"""Focused tests for CSV import behavior and reporting."""

from __future__ import annotations

from decimal import Decimal
from io import StringIO
import json
import tempfile
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import NotFoundError
from mtg_source_stack.inventory.csv_import import (
    build_add_card_kwargs_from_csv_row,
    import_csv,
    import_csv_stream,
    normalize_csv_row,
)
from tests.common import RepoSmokeTestCase, materialize_fixture_bundle


class InventoryCsvImportTest(RepoSmokeTestCase):
    def test_build_add_card_kwargs_normalizes_headers_and_derives_inventory_slug(self) -> None:
        # This mirrors the kind of mixed-header export a user is likely to hand
        # us from another tool, so the assertions focus on normalization rather
        # than on one exact CSV dialect.
        row = normalize_csv_row(
            {
                "Collection Name": "Trade Binder",
                "Product ID": "534658",
                "Quantity": "2",
                "Cond": "Near Mint",
                "Language": "English",
                "Variant": "Traditional Foil",
                "Purchase Price": "1.25",
                "Currency": "USD",
                "Tag": "burn, modern",
            }
        )

        add_kwargs = build_add_card_kwargs_from_csv_row(
            row,
            row_number=2,
            default_inventory=None,
        )

        self.assertIsNotNone(add_kwargs)
        assert add_kwargs is not None
        self.assertEqual("trade-binder", add_kwargs["inventory_slug"])
        self.assertEqual("Trade Binder", add_kwargs["inventory_display_name"])
        self.assertEqual("534658", add_kwargs["tcgplayer_product_id"])
        self.assertEqual(2, add_kwargs["quantity"])
        self.assertEqual("NM", add_kwargs["condition_code"])
        self.assertEqual("foil", add_kwargs["finish"])
        self.assertEqual("en", add_kwargs["language_code"])
        self.assertEqual(Decimal("1.25"), add_kwargs["acquisition_price"])
        self.assertEqual("USD", add_kwargs["acquisition_currency"])
        self.assertEqual("burn, modern", add_kwargs["tags"])

    def test_build_add_card_kwargs_uses_total_plus_delta_and_skips_zero_rows(self) -> None:
        # Seller/export-style CSVs often express quantity as "total plus delta"
        # instead of a single quantity column, and zero net rows should vanish
        # before they ever reach the add-card workflow.
        computed_row = normalize_csv_row(
            {
                "Inventory": "personal",
                "Scryfall ID": "csv-card-1",
                "Total Quantity": "3",
                "Add to Quantity": "-1",
            }
        )
        computed_kwargs = build_add_card_kwargs_from_csv_row(
            computed_row,
            row_number=2,
            default_inventory=None,
        )

        self.assertIsNotNone(computed_kwargs)
        assert computed_kwargs is not None
        self.assertEqual(2, computed_kwargs["quantity"])

        zero_row = normalize_csv_row(
            {
                "Inventory": "personal",
                "Scryfall ID": "csv-card-1",
                "Total Quantity": "3",
                "Add to Quantity": "-3",
            }
        )
        self.assertIsNone(
            build_add_card_kwargs_from_csv_row(
                zero_row,
                row_number=3,
                default_inventory=None,
            )
        )

    def test_build_add_card_kwargs_accepts_oracle_id_without_defaulting_owned_language(self) -> None:
        row = normalize_csv_row(
            {
                "Inventory": "personal",
                "Oracle ID": "oracle-csv-1",
                "Quantity": "1",
                "Finish": "foil",
            }
        )

        add_kwargs = build_add_card_kwargs_from_csv_row(
            row,
            row_number=2,
            default_inventory=None,
        )

        self.assertIsNotNone(add_kwargs)
        assert add_kwargs is not None
        self.assertEqual("oracle-csv-1", add_kwargs["oracle_id"])
        self.assertIsNone(add_kwargs["language_code"])

    def test_import_csv_returns_serialized_rows_and_creates_inventory_from_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            csv_path = tmp / "inventory_import.csv"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        lang,
                        finishes_json
                    )
                    VALUES (
                        'csv-card-1',
                        'csv-oracle-1',
                        'CSV Test Card',
                        'tst',
                        'Test Set',
                        '5',
                        'en',
                        '["normal"]'
                    )
                    """
                )
                connection.commit()

            # The direct service path should be able to create the inventory
            # from the display name in the CSV and still return API-friendly
            # serialized rows for reporting.
            csv_path.write_text(
                (
                    "Collection Name,Scryfall ID,Qty,Cond,Location,Purchase Price,Currency,Tag,Notes\n"
                    "Trade Binder,csv-card-1,2,NM,Blue Binder,1.25,USD,burn,Imported from CSV\n"
                ),
                encoding="utf-8",
            )

            report = import_csv(
                db_path,
                csv_path=csv_path,
                default_inventory=None,
                dry_run=False,
            )

            self.assertEqual(1, report["rows_seen"])
            self.assertEqual(1, report["rows_written"])
            self.assertEqual(False, report["dry_run"])
            self.assertEqual(1, len(report["imported_rows"]))
            imported_row = report["imported_rows"][0]
            self.assertEqual(2, imported_row["csv_row"])
            self.assertEqual("trade-binder", imported_row["inventory"])
            self.assertEqual("CSV Test Card", imported_row["card_name"])
            self.assertEqual("1.25", imported_row["acquisition_price"])
            self.assertEqual("USD", imported_row["acquisition_currency"])
            self.assertEqual(["burn"], imported_row["tags"])
            self.assertEqual("Imported from CSV", imported_row["notes"])

            with connect(db_path) as connection:
                inventory_row = connection.execute(
                    """
                    SELECT slug, display_name
                    FROM inventories
                    WHERE slug = 'trade-binder'
                    """
                ).fetchone()
                item_row = connection.execute(
                    """
                    SELECT quantity, location, acquisition_price, acquisition_currency, notes
                    FROM inventory_items
                    """
                ).fetchone()

            self.assertEqual(("trade-binder", "Trade Binder"), tuple(inventory_row))
            self.assertEqual(2, item_row["quantity"])
            self.assertEqual("Blue Binder", item_row["location"])
            self.assertEqual("1.25", str(item_row["acquisition_price"]))
            self.assertEqual("USD", item_row["acquisition_currency"])
            self.assertEqual("Imported from CSV", item_row["notes"])

    def test_import_csv_stream_can_disable_inventory_auto_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        lang,
                        finishes_json
                    )
                    VALUES (
                        'csv-card-1',
                        'csv-oracle-1',
                        'CSV Test Card',
                        'tst',
                        'Test Set',
                        '5',
                        'en',
                        '["normal"]'
                    )
                    """
                )
                connection.commit()

            csv_handle = StringIO(
                "Collection Name,Scryfall ID,Qty,Cond\n"
                "Trade Binder,csv-card-1,2,NM\n"
            )

            with self.assertRaises(NotFoundError):
                import_csv_stream(
                    db_path,
                    csv_handle=csv_handle,
                    csv_filename="inventory_import.csv",
                    default_inventory=None,
                    allow_inventory_auto_create=False,
                )

    def test_import_csv_detects_tcgplayer_legacy_collection_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            csv_path = tmp / "legacy_data.csv"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        lang,
                        tcgplayer_product_id,
                        finishes_json
                    )
                    VALUES (
                        'csv-card-legacy',
                        'csv-oracle-legacy',
                        'Legacy Product Card',
                        'tst',
                        'Test Set',
                        '11',
                        'en',
                        '534658',
                        '["normal","foil"]'
                    )
                    """
                )
                connection.commit()

            csv_path.write_text(
                (
                    "Collection Name,Product ID,Condition,Language,Variant,Quantity\n"
                    "Trade Binder,534658,Near Mint,English,Traditional Foil,2\n"
                ),
                encoding="utf-8",
            )

            report = import_csv(
                db_path,
                csv_path=csv_path,
                default_inventory=None,
                dry_run=False,
            )

            self.assertEqual("tcgplayer_legacy_collection_csv", report["detected_format"])
            self.assertEqual(1, report["rows_written"])
            self.assertEqual("foil", report["imported_rows"][0]["finish"])
            self.assertEqual("trade-binder", report["imported_rows"][0]["inventory"])

    def test_import_csv_detects_tcgplayer_app_collection_and_maps_printing_to_finish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            csv_path = tmp / "tcgplayer_app.csv"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        lang,
                        tcgplayer_product_id,
                        finishes_json
                    )
                    VALUES (
                        'csv-card-app',
                        'csv-oracle-app',
                        'App Product Card',
                        'tst',
                        'Test Set',
                        '12',
                        'en',
                        '777888',
                        '["normal","foil"]'
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name)
                    VALUES ('personal', 'Personal Collection')
                    """
                )
                connection.commit()

            csv_path.write_text(
                (
                    "List Name,Product ID,Name,Condition,Language,Printing,Quantity\n"
                    "Personal Collection,777888,App Product Card,Near Mint,English,Non-Foil,3\n"
                ),
                encoding="utf-8",
            )

            report = import_csv(
                db_path,
                csv_path=csv_path,
                default_inventory="personal",
                dry_run=False,
            )

            self.assertEqual("tcgplayer_app_collection_csv", report["detected_format"])
            self.assertEqual(1, report["rows_written"])
            self.assertEqual("normal", report["imported_rows"][0]["finish"])

            with connect(db_path) as connection:
                item_row = connection.execute(
                    """
                    SELECT quantity, finish
                    FROM inventory_items
                    """
                ).fetchone()

            self.assertEqual(3, item_row["quantity"])
            self.assertEqual("normal", item_row["finish"])

    def test_import_csv_accepts_oracle_id_and_infers_resolved_printing_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            csv_path = tmp / "inventory_import.csv"
            initialize_database(db_path)

            with connect(db_path) as connection:
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
                    VALUES (?, 'csv-oracle-add', 'CSV Oracle Card', ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "csv-oracle-ja",
                            "neo",
                            "Kamigawa: Neon Dynasty",
                            "21",
                            "ja",
                            "2024-02-01",
                            '["foil"]',
                        ),
                        (
                            "csv-oracle-en",
                            "neo",
                            "Kamigawa: Neon Dynasty",
                            "22",
                            "en",
                            "2024-01-01",
                            '["nonfoil","foil"]',
                        ),
                    ],
                )
                connection.commit()

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name)
                    VALUES ('personal', 'Personal Collection')
                    """
                )
                connection.commit()

            csv_path.write_text(
                (
                    "Inventory,Oracle ID,Qty,Cond,Lang,Finish\n"
                    "personal,csv-oracle-add,1,Near Mint,ja,foil\n"
                ),
                encoding="utf-8",
            )

            report = import_csv(
                db_path,
                csv_path=csv_path,
                default_inventory=None,
                dry_run=False,
            )

            self.assertEqual(1, report["rows_written"])
            self.assertEqual("csv-oracle-ja", report["imported_rows"][0]["scryfall_id"])
            self.assertEqual("ja", report["imported_rows"][0]["language_code"])

            with connect(db_path) as connection:
                item_row = connection.execute(
                    """
                    SELECT scryfall_id, language_code
                    FROM inventory_items
                    """
                ).fetchone()

            self.assertEqual("csv-oracle-ja", item_row["scryfall_id"])
            self.assertEqual("ja", item_row["language_code"])

    def test_import_csv_reports_invalid_acquisition_values_with_row_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            csv_path = tmp / "inventory_import.csv"
            csv_path.write_text(
                (
                    "Inventory,Scryfall ID,Quantity,Acquisition Price\n"
                    "personal,csv-card-1,1,not-a-number\n"
                ),
                encoding="utf-8",
            )

            # Parse failures should point at the exact CSV row and should happen
            # before the importer creates a database file or partial writes.
            with self.assertRaisesRegex(ValueError, "CSV row 2: acquisition_price must be a number."):
                import_csv(
                    db_path,
                    csv_path=csv_path,
                    default_inventory=None,
                    dry_run=False,
                )

            self.assertFalse(db_path.exists())

    def test_import_csv_infers_single_supported_finish_when_csv_omits_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "shiny_bird_foil_only",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
                "archidekt_like.csv",
            )
            scryfall_path = bundle["scryfall.json"]
            identifiers_path = bundle["identifiers.json"]
            prices_path = bundle["prices.json"]
            csv_path = bundle["archidekt_like.csv"]

            # Seed the catalog with a card that only has foil pricing so the CSV
            # import can prove it no longer rewrites finish based on pricing data.
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

            # When the CSV omits finish and the printing only has one legal
            # finish, the importer can infer it safely instead of forcing the
            # user to restate the only available option.
            csv_import_output = self.run_cli(
                "import-csv",
                "--db",
                str(db_path),
                "--csv",
                str(csv_path),
                "--inventory",
                "personal",
            )
            self.assertIn("Rows imported: 1", csv_import_output)

            with connect(db_path) as connection:
                item_row = connection.execute(
                    """
                    SELECT finish
                    FROM inventory_items
                    """
                ).fetchone()

            self.assertEqual("foil", item_row["finish"])

    def test_import_csv_rejects_ambiguous_missing_finish_with_row_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            csv_path = tmp / "inventory_import.csv"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        lang,
                        finishes_json
                    )
                    VALUES (
                        'csv-card-ambiguous',
                        'csv-oracle-ambiguous',
                        'Ambiguous Finish Card',
                        'tst',
                        'Test Set',
                        '8',
                        'en',
                        '["normal","foil"]'
                    )
                    """
                )
                connection.commit()

            csv_path.write_text(
                (
                    "Collection Name,Scryfall ID,Qty,Cond\n"
                    "Trade Binder,csv-card-ambiguous,1,NM\n"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ValueError,
                "CSV row 2: finish is required for this printing when multiple finishes are available. "
                "Available finishes: normal, foil.",
            ):
                import_csv(
                    db_path,
                    csv_path=csv_path,
                    default_inventory=None,
                    dry_run=False,
                )

    def test_import_csv_dry_run_writes_report_and_leaves_db_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            report_path = tmp / "reports" / "import_preview.txt"
            report_json_path = tmp / "reports" / "import_preview.json"
            report_csv_path = tmp / "reports" / "import_preview.csv"
            bundle = materialize_fixture_bundle(
                tmp,
                "preview_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
                "inventory_import.csv",
            )
            scryfall_path = bundle["scryfall.json"]
            identifiers_path = bundle["identifiers.json"]
            prices_path = bundle["prices.json"]
            csv_path = bundle["inventory_import.csv"]

            # Populate the database normally first; the behavior under test is
            # that the later CSV preview reports what would happen without
            # mutating inventory rows.
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

            # Dry-run mode should still emit the same user-facing reports, but
            # all writes stay in the preview artifacts instead of the database.
            preview_output = self.run_cli(
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

            # Listing inventory at the end verifies that the preview did not
            # create any persistent inventory rows.
            owned_output = self.run_cli(
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertEqual("No rows found.", owned_output)
