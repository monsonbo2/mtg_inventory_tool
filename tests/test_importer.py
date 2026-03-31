"""Tests for importer, migration, and snapshot workflows."""

from __future__ import annotations

import gzip
import json
import sqlite3
import tempfile
from pathlib import Path

from mtg_source_stack.db.connection import connect
from tests.common import RepoSmokeTestCase
from mtg_source_stack.mvp_importer import import_scryfall_cards, initialize_database


class ImporterTest(RepoSmokeTestCase):
    def test_import_all_missing_file_fails_cleanly_without_creating_db_or_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            missing_json = tmp / "missing.json"

            result = self.run_failing_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(missing_json),
                "--identifiers-json",
                str(missing_json),
                "--prices-json",
                str(missing_json),
            )

            self.assertEqual(2, result.returncode)
            self.assertIn(f"Could not read JSON file '{missing_json}'", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(db_path.exists())
            self.assertFalse((tmp / "_snapshots").exists())

    def test_connect_enables_foreign_key_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            with connect(db_path) as connection:
                pragma_value = connection.execute("PRAGMA foreign_keys").fetchone()[0]

            self.assertEqual(1, pragma_value)

    def test_foreign_keys_reject_orphan_inventory_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                inventory_id = connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name)
                    VALUES ('personal', 'Personal Collection')
                    RETURNING id
                    """
                ).fetchone()[0]

                # A row that points at a non-existent printing should fail at the
                # database layer instead of relying on application code alone.
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO inventory_items (
                            inventory_id,
                            scryfall_id,
                            quantity,
                            condition_code,
                            finish,
                            language_code,
                            location,
                            tags_json
                        )
                        VALUES (?, 'missing-card', 1, 'NM', 'normal', 'en', '', '[]')
                        """,
                        (inventory_id,),
                    )

    def test_foreign_keys_apply_inventory_and_price_cascades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
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
                        collector_number
                    )
                    VALUES ('card-1', 'oracle-1', 'Cascade Test Card', 'tst', 'Test Set', '1')
                    """
                )
                inventory_id = connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name)
                    VALUES ('personal', 'Personal Collection')
                    RETURNING id
                    """
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO inventory_items (
                        inventory_id,
                        scryfall_id,
                        quantity,
                        condition_code,
                        finish,
                        language_code,
                        location,
                        tags_json
                    )
                    VALUES (?, 'card-1', 2, 'NM', 'normal', 'en', 'Binder', '[]')
                    """,
                    (inventory_id,),
                )
                connection.execute(
                    """
                    INSERT INTO price_snapshots (
                        scryfall_id,
                        provider,
                        price_kind,
                        finish,
                        currency,
                        snapshot_date,
                        price_value,
                        source_name
                    )
                    VALUES ('card-1', 'tcgplayer', 'retail', 'normal', 'USD', '2026-03-30', 1.25, 'test')
                    """
                )

                connection.execute("DELETE FROM inventories WHERE id = ?", (inventory_id,))
                inventory_item_count = connection.execute(
                    "SELECT COUNT(*) FROM inventory_items WHERE inventory_id = ?",
                    (inventory_id,),
                ).fetchone()[0]
                price_snapshot_count = connection.execute(
                    "SELECT COUNT(*) FROM price_snapshots WHERE scryfall_id = 'card-1'"
                ).fetchone()[0]

                connection.execute("DELETE FROM mtg_cards WHERE scryfall_id = 'card-1'")
                remaining_price_snapshot_count = connection.execute(
                    "SELECT COUNT(*) FROM price_snapshots WHERE scryfall_id = 'card-1'"
                ).fetchone()[0]

            self.assertEqual(0, inventory_item_count)
            self.assertEqual(1, price_snapshot_count)
            self.assertEqual(0, remaining_price_snapshot_count)

    def test_initialize_database_migrates_existing_inventory_items_for_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.db"

            # Build a pre-migration schema by hand so the test exercises the
            # bootstrap path that adds the newer `tags_json` column.
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
            # Reversible layouts can omit the top-level oracle id, so the
            # importer falls back to the face data instead of dropping the row.
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

    def test_import_mtgjson_prices_skips_non_usd_provider_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            prices_path = Path(tmp_dir) / "prices.json"

            initialize_database(db_path)
            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        mtgjson_uuid,
                        name,
                        set_code,
                        set_name,
                        collector_number
                    )
                    VALUES ('card-1', 'oracle-1', 'uuid-1', 'Currency Test', 'tst', 'Test Set', '1')
                    """
                )

            prices_payload = {
                "data": {
                    "uuid-1": {
                        "paper": {
                            "cardmarket": {
                                "currency": "EUR",
                                "retail": {"normal": {"2026-03-27": 3.50}},
                            }
                        }
                    }
                }
            }
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            from mtg_source_stack.importer.mtgjson import import_mtgjson_prices

            stats = import_mtgjson_prices(db_path, prices_path)

            with connect(db_path) as connection:
                snapshot_count = connection.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]

            self.assertEqual(1, stats.rows_seen)
            self.assertEqual(0, stats.rows_written)
            self.assertEqual(1, stats.rows_skipped)
            self.assertEqual(0, snapshot_count)

    def test_import_mtgjson_prices_normalizes_nonfoil_finish_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            prices_path = Path(tmp_dir) / "prices.json"

            initialize_database(db_path)
            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        mtgjson_uuid,
                        name,
                        set_code,
                        set_name,
                        collector_number
                    )
                    VALUES ('card-2', 'oracle-2', 'uuid-2', 'Finish Alias Test', 'tst', 'Test Set', '2')
                    """
                )
                connection.commit()

            prices_payload = {
                "data": {
                    "uuid-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"nonfoil": {"2026-03-27": 3.50}},
                            }
                        }
                    }
                }
            }
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            from mtg_source_stack.importer.mtgjson import import_mtgjson_prices

            stats = import_mtgjson_prices(db_path, prices_path)

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT finish, price_value
                    FROM price_snapshots
                    """
                ).fetchall()

            self.assertEqual(1, stats.rows_seen)
            self.assertEqual(1, stats.rows_written)
            self.assertEqual(0, stats.rows_skipped)
            self.assertEqual([("normal", 3.5)], [(row["finish"], row["price_value"]) for row in rows])

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

            # Point every download URL at local files so the end-to-end sync path
            # can be exercised without real network traffic.
            scryfall_bulk_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            metadata_path.write_text(json.dumps(metadata_payload), encoding="utf-8")
            with gzip.open(identifiers_path, "wt", encoding="utf-8") as handle:
                json.dump(identifiers_payload, handle)
            with gzip.open(prices_path, "wt", encoding="utf-8") as handle:
                json.dump(prices_payload, handle)

            sync_output = self.run_importer(
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

            # Seed a tiny but fully linked catalog so the snapshot assertions are
            # about inventory behavior, not fixture resolution.
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
            self.assertIn("snapshot:", import_output)

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
                "snapshot-card-1",
                "--quantity",
                "2",
                "--finish",
                "normal",
            )

            remove_output = self.run_cli(
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
            # The command names the snapshot after the destructive action so the
            # operator can tell at a glance what recovery point to use.
            remove_snapshot = next(
                snapshot for snapshot in snapshots if "before_remove_card_item_1" in snapshot.name
            )

            list_output = self.run_importer(
                "list-snapshots",
                "--db",
                str(db_path),
            )
            self.assertIn(remove_snapshot.name, list_output)
            self.assertIn("before_remove_card_item_1", list_output)

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

            restore_output = self.run_importer(
                "restore-snapshot",
                "--db",
                str(db_path),
                "--snapshot",
                remove_snapshot.name,
            )
            self.assertIn("Restored snapshot", restore_output)
            self.assertIn("pre_restore_snapshot:", restore_output)

            # Restoring the snapshot should bring the removed inventory row back
            # with its valuation context intact.
            restored_owned_output = self.run_cli(
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
