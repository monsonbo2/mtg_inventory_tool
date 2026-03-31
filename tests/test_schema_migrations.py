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

            self.assertEqual([1, 2, 3], versions)
            self.assertEqual(3, latest_version)
            self.assertEqual(1, audit_log_exists)

    def test_initialize_database_is_idempotent_for_schema_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            initialize_database(db_path)
            initialize_database(db_path)

            with connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT version, name FROM schema_migrations ORDER BY version"
                ).fetchall()

            self.assertEqual(3, len(rows))
            self.assertEqual(
                [(1, "mvp base"), (2, "add tags json"), (3, "add inventory audit log")],
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
                versions = [
                    row["version"]
                    for row in migrated.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
                ]
                audit_columns = {row["name"] for row in migrated.execute("PRAGMA table_info(inventory_audit_log)")}

            self.assertIn("tags_json", columns)
            self.assertEqual("[]", tags_value)
            self.assertEqual([1, 2, 3], versions)
            self.assertIn("before_json", audit_columns)
            self.assertIn("after_json", audit_columns)
            self.assertIn("metadata_json", audit_columns)
