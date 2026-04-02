"""Focused tests for shared-service SQLite runtime posture."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from mtg_source_stack.db.connection import (
    SQLITE_BUSY_TIMEOUT_MS,
    SQLITE_JOURNAL_MODE,
    SQLITE_SYNCHRONOUS_MODE,
    connect,
    describe_sqlite_runtime_posture,
)
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.db.snapshots import create_database_snapshot, restore_database_snapshot


class DbRuntimeTest(unittest.TestCase):
    def test_connect_reports_shared_service_friendly_sqlite_posture(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            posture = describe_sqlite_runtime_posture(db_path)

            self.assertEqual(SQLITE_JOURNAL_MODE, posture["journal_mode"])
            self.assertEqual(SQLITE_BUSY_TIMEOUT_MS, posture["busy_timeout_ms"])
            self.assertEqual(SQLITE_SYNCHRONOUS_MODE, posture["synchronous"])
            self.assertTrue(posture["foreign_keys"])

    def test_busy_timeout_allows_waiting_writer_to_succeed_after_brief_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "lock_test.db"

            with connect(db_path) as connection:
                connection.execute("CREATE TABLE lock_test (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
                connection.commit()

            held = connect(db_path)
            errors: list[Exception] = []

            def waiting_writer() -> None:
                try:
                    with connect(db_path) as contender:
                        contender.execute("INSERT INTO lock_test (value) VALUES ('waiting')")
                        contender.commit()
                except Exception as exc:  # pragma: no cover - failure path asserted below
                    errors.append(exc)

            try:
                held.execute("BEGIN IMMEDIATE")
                held.execute("INSERT INTO lock_test (value) VALUES ('held')")

                worker = threading.Thread(target=waiting_writer)
                worker.start()

                time.sleep(0.2)
                self.assertTrue(worker.is_alive(), "Second writer should still be waiting on the DB lock.")

                held.commit()
                worker.join(timeout=2)

                self.assertFalse(worker.is_alive(), "Second writer did not complete after the lock was released.")
                self.assertEqual([], errors)

                with connect(db_path) as check:
                    row_count = check.execute("SELECT COUNT(*) FROM lock_test").fetchone()[0]
                self.assertEqual(2, row_count)
            finally:
                held.close()

    def test_snapshot_restore_recovers_previous_state_and_creates_pre_restore_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    "INSERT INTO inventories (slug, display_name) VALUES ('personal', 'Personal Collection')"
                )
                connection.commit()

            snapshot = create_database_snapshot(db_path, label="before_trade_inventory")

            with connect(db_path) as connection:
                connection.execute(
                    "INSERT INTO inventories (slug, display_name) VALUES ('trade', 'Trade Binder')"
                )
                connection.commit()

            restore_result = restore_database_snapshot(db_path, snapshot=snapshot["snapshot_name"])

            self.assertEqual(snapshot["snapshot_name"], restore_result["snapshot_name"])
            self.assertIsNotNone(restore_result["pre_restore_snapshot"])
            self.assertIn("before_restore_", restore_result["pre_restore_snapshot"]["snapshot_name"])

            with connect(db_path) as connection:
                slugs = [row["slug"] for row in connection.execute("SELECT slug FROM inventories ORDER BY slug")]

            self.assertEqual(["personal"], slugs)
