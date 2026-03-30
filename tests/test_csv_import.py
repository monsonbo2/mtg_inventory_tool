from __future__ import annotations

import json
import tempfile
from pathlib import Path

from tests.common import RepoSmokeTestCase, materialize_fixture_bundle


class InventoryCsvImportTest(RepoSmokeTestCase):
    def test_import_csv_auto_adjusts_single_catalog_finish_and_reports_it(self) -> None:
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
            self.assertIn("Finish adjustments: 1", csv_import_output)
            self.assertIn("Automatic finish adjustments", csv_import_output)
            self.assertIn("Shiny Bird", csv_import_output)
            self.assertIn("single catalog finish", csv_import_output)

            owned_output = self.run_cli(
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
