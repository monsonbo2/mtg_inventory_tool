"""Focused tests for the schema migration framework."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.migrator import current_schema_version
from mtg_source_stack.db.schema import initialize_database


class SchemaMigrationTest(unittest.TestCase):
    def _build_legacy_card_scope_db(self, *, type_line: str | None) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        db_path = Path(temp_dir.name) / "legacy-cards.db"

        connection = sqlite3.connect(db_path)
        connection.executescript(
            """
            CREATE TABLE mtg_cards (
                scryfall_id TEXT PRIMARY KEY,
                type_line TEXT
            );

            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            INSERT INTO schema_migrations (version, name)
            VALUES
                (1, 'mvp base'),
                (2, 'add tags json'),
                (3, 'add inventory audit log'),
                (4, 'add card search fts'),
                (5, 'normalize price snapshot finishes'),
                (6, 'add inventory memberships'),
                (7, 'add actor default inventories');
            """
        )
        connection.execute(
            """
            INSERT INTO mtg_cards (scryfall_id, type_line)
            VALUES ('legacy-card-1', ?)
            """,
            (type_line,),
        )
        connection.commit()
        connection.close()

        return db_path

    def test_initialize_database_records_all_current_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            initialize_database(db_path)

            with connect(db_path) as connection:
                versions = [
                    row["version"]
                    for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
                ]
                latest_version = current_schema_version(connection)
                audit_log_exists = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'inventory_audit_log'"
                ).fetchone()[0]
                card_search_fts_exists = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'mtg_cards_fts'"
                ).fetchone()[0]
                inventory_memberships_exists = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'inventory_memberships'"
                ).fetchone()[0]
                actor_default_inventories_exists = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'actor_default_inventories'"
                ).fetchone()[0]
                mtg_card_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(mtg_cards)").fetchall()
                }

            self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], versions)
            self.assertEqual(10, latest_version)
            self.assertEqual(1, audit_log_exists)
            self.assertEqual(1, card_search_fts_exists)
            self.assertEqual(1, inventory_memberships_exists)
            self.assertEqual(1, actor_default_inventories_exists)
            self.assertTrue(
                {
                    "layout",
                    "set_type",
                    "games_json",
                    "digital",
                    "oversized",
                    "booster",
                    "promo_types_json",
                    "edhrec_rank",
                    "is_default_add_searchable",
                }.issubset(mtg_card_columns)
            )

    def test_initialize_database_is_idempotent_for_schema_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            initialize_database(db_path)
            initialize_database(db_path)

            with connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT version, name FROM schema_migrations ORDER BY version"
                ).fetchall()

            self.assertEqual(10, len(rows))
            self.assertEqual(
                [
                    (1, "mvp base"),
                    (2, "add tags json"),
                    (3, "add inventory audit log"),
                    (4, "add card search fts"),
                    (5, "normalize price snapshot finishes"),
                    (6, "add inventory memberships"),
                    (7, "add actor default inventories"),
                    (8, "add catalog classification fields"),
                    (9, "add catalog relevance rank"),
                    (10, "add inventory printing selection mode"),
                ],
                [(row["version"], row["name"]) for row in rows],
            )

    def test_initialize_database_upgrades_legacy_schema_and_records_migrations(self) -> None:
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

            with connect(db_path) as migrated:
                columns = {row["name"] for row in migrated.execute("PRAGMA table_info(inventory_items)")}
                tags_value = migrated.execute("SELECT tags_json FROM inventory_items").fetchone()[0]
                printing_selection_mode = migrated.execute(
                    "SELECT printing_selection_mode FROM inventory_items"
                ).fetchone()[0]
                versions = [
                    row["version"]
                    for row in migrated.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
                ]
                audit_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(inventory_audit_log)")}
                fts_exists = migrated.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'mtg_cards_fts'"
                ).fetchone()[0]
                memberships_exists = migrated.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'inventory_memberships'"
                ).fetchone()[0]
                actor_default_inventories_exists = migrated.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'actor_default_inventories'"
                ).fetchone()[0]

            self.assertIn("tags_json", columns)
            self.assertIn("printing_selection_mode", columns)
            self.assertEqual("[]", tags_value)
            self.assertEqual("explicit", printing_selection_mode)
            self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], versions)
            self.assertIn("before_json", audit_columns)
            self.assertIn("after_json", audit_columns)
            self.assertIn("metadata_json", audit_columns)
            self.assertEqual(1, fts_exists)
            self.assertEqual(1, memberships_exists)
            self.assertEqual(1, actor_default_inventories_exists)

    def test_initialize_database_normalizes_legacy_price_snapshot_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "legacy-prices.db"

            connection = sqlite3.connect(db_path)
            connection.executescript(
                """
                CREATE TABLE mtg_cards (
                    scryfall_id TEXT PRIMARY KEY,
                    type_line TEXT
                );

                CREATE TABLE price_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scryfall_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    price_kind TEXT NOT NULL,
                    finish TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    snapshot_date TEXT NOT NULL,
                    price_value NUMERIC NOT NULL,
                    source_name TEXT NOT NULL
                );

                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                INSERT INTO mtg_cards (scryfall_id, type_line)
                VALUES ('card-1', 'Instant');

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
                VALUES
                    ('card-1', 'tcgplayer', 'retail', 'nonfoil', 'USD', '2026-03-30', 1.25, 'legacy'),
                    ('card-1', 'tcgplayer', 'retail', 'normal', 'USD', '2026-03-30', 1.50, 'legacy');

                INSERT INTO schema_migrations (version, name)
                VALUES
                    (1, 'mvp base'),
                    (2, 'add tags json'),
                    (3, 'add inventory audit log'),
                    (4, 'add card search fts');
                """
            )
            connection.commit()
            connection.close()

            initialize_database(db_path)

            with connect(db_path) as migrated:
                rows = migrated.execute(
                    """
                    SELECT finish, price_value
                    FROM price_snapshots
                    ORDER BY id
                    """
                ).fetchall()
                versions = [
                    row["version"]
                    for row in migrated.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
                ]

            self.assertEqual([("normal", 1.5)], [(row["finish"], row["price_value"]) for row in rows])
            self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], versions)

    def test_initialize_database_backfills_default_add_search_scope_for_legacy_rows(self) -> None:
        for type_line, expected in (
            ("Token Artifact — Food", 0),
            ("Emblem — Ajani", 0),
            ("Card", 0),
            ("Card // Card", 0),
            ("Instant", 1),
            ("Creature — Wizard", 1),
            (None, 1),
        ):
            with self.subTest(type_line=type_line):
                db_path = self._build_legacy_card_scope_db(type_line=type_line)

                initialize_database(db_path)

                with connect(db_path) as migrated:
                    row = migrated.execute(
                        """
                        SELECT
                            layout,
                            set_type,
                            games_json,
                            digital,
                            oversized,
                            booster,
                            promo_types_json,
                            edhrec_rank,
                            is_default_add_searchable
                        FROM mtg_cards
                        WHERE scryfall_id = 'legacy-card-1'
                        """
                    ).fetchone()

                self.assertIsNone(row["layout"])
                self.assertIsNone(row["set_type"])
                self.assertEqual("[]", row["games_json"])
                self.assertEqual(0, row["digital"])
                self.assertEqual(0, row["oversized"])
                self.assertEqual(0, row["booster"])
                self.assertEqual("[]", row["promo_types_json"])
                self.assertIsNone(row["edhrec_rank"])
                self.assertEqual(expected, row["is_default_add_searchable"])
