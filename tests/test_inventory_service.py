from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

from mtg_source_stack.inventory.service import inventory_report
from tests.common import RepoSmokeTestCase, materialize_fixture_bundle


class InventoryServiceTest(RepoSmokeTestCase):
    def test_reconcile_prices_updates_finish_when_one_priced_finish_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "shiny_bird_foil_only",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )
            scryfall_path = bundle["scryfall.json"]
            identifiers_path = bundle["identifiers.json"]
            prices_path = bundle["prices.json"]

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

            add_output = self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "foil-only-1",
                "--quantity",
                "1",
                "--finish",
                "normal",
            )
            self.assertIn("Finish: normal", add_output)

            gap_output = self.run_cli(
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

            preview_output = self.run_cli(
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

            reconcile_output = self.run_cli(
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

            self.run_importer(
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
            self.run_cli(
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
            self.run_cli(
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

            health_output = self.run_cli(
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

            self.run_importer(
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

            set_acquisition_output = self.run_cli(
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
            )
            self.assertIn("Safety snapshot created", split_output)
            self.assertIn("Split inventory row", split_output)
            self.assertIn("Moved quantity: 1", split_output)
            self.assertIn("Source quantity now: 3", split_output)
            self.assertIn("Target item ID: 2", split_output)
            self.assertIn("Target quantity now: 1", split_output)
            self.assertIn("Merged into existing row: no", split_output)

            owned_after_split = self.run_cli(
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

            merge_output = self.run_cli(
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

            self.run_cli(
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

            merge_failure = self.run_failing_cli(
                "merge-rows",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--source-item-id",
                "3",
                "--target-item-id",
                "1",
            )
            self.assertNotEqual(0, merge_failure.returncode)
            self.assertIn("same printing", merge_failure.stderr)

    def test_add_card_normalizes_identity_fields_before_merging_rows(self) -> None:
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
                "--language-code",
                "en",
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
                "nm",
                "--language-code",
                "EN",
                "--finish",
                "nonfoil",
            )

            connection = sqlite3.connect(db_path)
            rows = connection.execute(
                """
                SELECT quantity, condition_code, language_code
                FROM inventory_items
                """
            ).fetchall()
            connection.close()

            self.assertEqual([(2, "NM", "en")], rows)

    def test_inventory_report_filters_health_payload_to_matching_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "report-filter-a",
                    "oracle_id": "report-filter-oracle-a",
                    "name": "Alpha",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "1",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2026-01-01",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 1001,
                },
                {
                    "id": "report-filter-b",
                    "oracle_id": "report-filter-oracle-b",
                    "name": "Beta",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "2",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2026-01-01",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 1002,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-report-filter-a": {
                        "name": "Alpha",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "report-filter-a",
                            "tcgplayerProductId": "1001",
                        },
                    },
                    "uuid-report-filter-b": {
                        "name": "Beta",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "report-filter-b",
                            "tcgplayerProductId": "1002",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-report-filter-a": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.00}},
                            }
                        }
                    },
                    "uuid-report-filter-b": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.00}},
                            }
                        }
                    },
                }
            }

            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_importer(
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
                "report-filter-a",
                "--quantity",
                "1",
                "--location",
                "Box 1",
                "--tags",
                "dup",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-filter-a",
                "--quantity",
                "1",
                "--location",
                "Box 2",
                "--tags",
                "dup",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-filter-b",
                "--quantity",
                "1",
                "--location",
                "Box 3",
                "--tags",
                "solo",
            )

            report = inventory_report(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                query="Beta",
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
                limit=5,
                stale_days=30,
            )

            self.assertEqual(1, report["summary"]["item_rows"])
            self.assertEqual(0, report["health"]["summary"]["duplicate_groups"])
            self.assertEqual([], report["health"]["duplicate_groups"])

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

            self.run_importer(
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
            self.run_cli(
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

            export_output = self.run_cli(
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

            report_output = self.run_cli(
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
