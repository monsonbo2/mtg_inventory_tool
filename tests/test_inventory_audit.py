"""Focused audit-log tests for complex inventory mutations."""

from __future__ import annotations

from decimal import Decimal
import json
import re
import tempfile
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.inventory.service import (
    add_card,
    create_inventory,
    list_inventory_audit_events,
    merge_rows,
    set_acquisition,
    set_condition,
    set_finish,
    split_row,
)
from tests.common import RepoSmokeTestCase


class InventoryAuditTest(RepoSmokeTestCase):
    def _seed_card(
        self,
        db_path: Path,
        *,
        scryfall_id: str = "audit-card-1",
        oracle_id: str = "audit-oracle-1",
        name: str = "Audit Test Card",
        collector_number: str = "11",
        finishes_json: str = '["normal","foil"]',
    ) -> None:
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
                    finishes_json
                )
                VALUES (?, ?, ?, 'tst', 'Test Set', ?, ?)
                """,
                (scryfall_id, oracle_id, name, collector_number, finishes_json),
            )
            connection.commit()

    def _create_personal_inventory(self, db_path: Path) -> None:
        # Most audit tests care about the row mutation that follows, not the
        # inventory bootstrap itself, so keep that setup tucked behind a helper.
        create_inventory(
            db_path,
            slug="personal",
            display_name="Personal Collection",
            description=None,
        )

    def _load_audit_rows(self, db_path: Path, *, action: str) -> list[dict[str, object]]:
        # Decode the JSON blobs here so each test can focus on the meaning of
        # the audit payload instead of the storage format mechanics.
        with connect(db_path) as connection:
            rows = connection.execute(
                """
                SELECT
                    action,
                    item_id,
                    actor_type,
                    actor_id,
                    request_id,
                    before_json,
                    after_json,
                    metadata_json
                FROM inventory_audit_log
                WHERE action = ?
                ORDER BY id
                """,
                (action,),
            ).fetchall()

        decoded_rows: list[dict[str, object]] = []
        for row in rows:
            decoded_rows.append(
                {
                    "action": row["action"],
                    "item_id": row["item_id"],
                    "actor_type": row["actor_type"],
                    "actor_id": row["actor_id"],
                    "request_id": row["request_id"],
                    "before": json.loads(row["before_json"]) if row["before_json"] else None,
                    "after": json.loads(row["after_json"]) if row["after_json"] else None,
                    "metadata": json.loads(row["metadata_json"]),
                }
            )
        return decoded_rows

    def test_set_finish_and_set_acquisition_write_detailed_audit_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._seed_card(db_path)
            self._create_personal_inventory(db_path)

            # Use two field-level edits in sequence so this test covers both the
            # before/after snapshots and the actor/request metadata plumbing.
            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="audit-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=2,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )

            set_finish(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                finish="foil",
                actor_type="user",
                actor_id="audit-user",
                request_id="req-finish",
            )
            set_acquisition(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                acquisition_price=Decimal("1.50"),
                acquisition_currency="USD",
                actor_type="user",
                actor_id="audit-user",
                request_id="req-acquisition",
            )

            finish_rows = self._load_audit_rows(db_path, action="set_finish")
            self.assertEqual(1, len(finish_rows))
            self.assertEqual("user", finish_rows[0]["actor_type"])
            self.assertEqual("audit-user", finish_rows[0]["actor_id"])
            self.assertEqual("req-finish", finish_rows[0]["request_id"])
            self.assertEqual("normal", finish_rows[0]["before"]["finish"])
            self.assertEqual("foil", finish_rows[0]["after"]["finish"])
            self.assertEqual(
                {"old_finish": "normal", "new_finish": "foil"},
                finish_rows[0]["metadata"],
            )

            acquisition_rows = self._load_audit_rows(db_path, action="set_acquisition")
            self.assertEqual(1, len(acquisition_rows))
            self.assertEqual("user", acquisition_rows[0]["actor_type"])
            self.assertEqual("audit-user", acquisition_rows[0]["actor_id"])
            self.assertEqual("req-acquisition", acquisition_rows[0]["request_id"])
            self.assertIsNone(acquisition_rows[0]["before"]["acquisition_price"])
            self.assertIsNone(acquisition_rows[0]["before"]["acquisition_currency"])
            self.assertEqual("1.5", acquisition_rows[0]["after"]["acquisition_price"])
            self.assertEqual("USD", acquisition_rows[0]["after"]["acquisition_currency"])
            self.assertEqual({"clear": False}, acquisition_rows[0]["metadata"])

    def test_set_condition_merge_writes_source_and_target_audit_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._seed_card(db_path)
            self._create_personal_inventory(db_path)

            # Build a deliberate identity collision so `set_condition --merge`
            # has to write the paired delete/update audit story.
            source_row = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="audit-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=2,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=Decimal("1.00"),
                acquisition_currency="USD",
                notes="Source row",
                tags=None,
            )
            target_row = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="audit-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="LP",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=Decimal("2.00"),
                acquisition_currency="USD",
                notes="Target row",
                tags=None,
            )

            set_condition(
                db_path,
                inventory_slug="personal",
                item_id=source_row.item_id,
                condition_code="LP",
                merge=True,
                keep_acquisition="target",
                actor_type="user",
                actor_id="audit-user",
                request_id="req-condition-merge",
            )

            audit_rows = self._load_audit_rows(db_path, action="set_condition")
            self.assertEqual(2, len(audit_rows))
            source_audit = next(row for row in audit_rows if row["item_id"] == source_row.item_id)
            target_audit = next(row for row in audit_rows if row["item_id"] == target_row.item_id)

            self.assertEqual("NM", source_audit["before"]["condition_code"])
            self.assertIsNone(source_audit["after"])
            self.assertEqual(
                {
                    "merged": True,
                    "target_item_id": target_row.item_id,
                    "new_condition_code": "LP",
                    "keep_acquisition": "target",
                },
                source_audit["metadata"],
            )
            self.assertEqual("user", source_audit["actor_type"])
            self.assertEqual("audit-user", source_audit["actor_id"])
            self.assertEqual("req-condition-merge", source_audit["request_id"])

            self.assertEqual(1, target_audit["before"]["quantity"])
            self.assertEqual(3, target_audit["after"]["quantity"])
            self.assertEqual("LP", target_audit["after"]["condition_code"])
            self.assertEqual("2", target_audit["after"]["acquisition_price"])
            self.assertEqual(
                {
                    "merged": True,
                    "source_item_id": source_row.item_id,
                    "new_condition_code": "LP",
                    "keep_acquisition": "target",
                },
                target_audit["metadata"],
            )
            self.assertEqual("user", target_audit["actor_type"])
            self.assertEqual("audit-user", target_audit["actor_id"])
            self.assertEqual("req-condition-merge", target_audit["request_id"])

    def test_split_row_and_merge_rows_record_source_target_audit_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._seed_card(db_path)
            self._create_personal_inventory(db_path)

            # First split one row into two identities, then merge them back
            # together so both multi-row audit payload shapes stay covered.
            source_row = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="audit-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=3,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=Decimal("3.00"),
                acquisition_currency="USD",
                notes="Main row",
                tags="trade",
            )

            split_result = split_row(
                db_path,
                inventory_slug="personal",
                item_id=source_row.item_id,
                quantity=1,
                condition_code=None,
                finish=None,
                language_code=None,
                location="Binder B",
                actor_type="user",
                actor_id="audit-user",
                request_id="req-split",
            )

            split_audit_rows = self._load_audit_rows(db_path, action="split_row")
            self.assertEqual(2, len(split_audit_rows))
            split_source_audit = next(row for row in split_audit_rows if row["item_id"] == source_row.item_id)
            split_target_audit = next(row for row in split_audit_rows if row["item_id"] == split_result.item_id)

            self.assertEqual(3, split_source_audit["before"]["quantity"])
            self.assertEqual(2, split_source_audit["after"]["quantity"])
            self.assertEqual(
                {
                    "role": "source",
                    "moved_quantity": 1,
                    "source_deleted": False,
                    "target_item_id": split_result.item_id,
                    "merged_into_existing": False,
                    "keep_acquisition": None,
                },
                split_source_audit["metadata"],
            )
            self.assertEqual("req-split", split_source_audit["request_id"])

            self.assertIsNone(split_target_audit["before"])
            self.assertEqual(1, split_target_audit["after"]["quantity"])
            self.assertEqual("Binder B", split_target_audit["after"]["location"])
            self.assertEqual(
                {
                    "role": "target",
                    "source_item_id": source_row.item_id,
                    "moved_quantity": 1,
                    "merged_into_existing": False,
                    "keep_acquisition": None,
                },
                split_target_audit["metadata"],
            )
            self.assertEqual("user", split_target_audit["actor_type"])
            self.assertEqual("audit-user", split_target_audit["actor_id"])

            merge_rows(
                db_path,
                inventory_slug="personal",
                source_item_id=split_result.item_id,
                target_item_id=source_row.item_id,
                actor_type="user",
                actor_id="audit-user",
                request_id="req-merge",
            )

            merge_audit_rows = self._load_audit_rows(db_path, action="merge_rows")
            self.assertEqual(2, len(merge_audit_rows))
            merge_source_audit = next(row for row in merge_audit_rows if row["item_id"] == split_result.item_id)
            merge_target_audit = next(row for row in merge_audit_rows if row["item_id"] == source_row.item_id)

            self.assertEqual(1, merge_source_audit["before"]["quantity"])
            self.assertIsNone(merge_source_audit["after"])
            self.assertEqual(
                {
                    "role": "source",
                    "target_item_id": source_row.item_id,
                    "keep_acquisition": None,
                },
                merge_source_audit["metadata"],
            )
            self.assertEqual("req-merge", merge_source_audit["request_id"])

            self.assertEqual(2, merge_target_audit["before"]["quantity"])
            self.assertEqual(3, merge_target_audit["after"]["quantity"])
            self.assertEqual("Binder A", merge_target_audit["after"]["location"])
            self.assertEqual(
                {
                    "role": "target",
                    "source_item_id": split_result.item_id,
                    "keep_acquisition": None,
                },
                merge_target_audit["metadata"],
            )
            self.assertEqual("user", merge_target_audit["actor_type"])
            self.assertEqual("audit-user", merge_target_audit["actor_id"])

    def test_list_inventory_audit_events_returns_typed_decoded_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._seed_card(db_path)
            self._create_personal_inventory(db_path)

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="audit-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes="Audit list demo",
                tags="audit",
                actor_type="user",
                actor_id="audit-reader",
                request_id="req-add",
            )
            set_finish(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                finish="foil",
                actor_type="user",
                actor_id="audit-reader",
                request_id="req-finish",
            )

            # The API route will rely on this helper, so verify it returns typed
            # decoded payloads with item filtering and newest-first ordering.
            events = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual(2, len(events))
            self.assertEqual("set_finish", events[0].action)
            self.assertEqual("add_card", events[1].action)
            self.assertEqual("audit-reader", events[0].actor_id)
            self.assertEqual("req-finish", events[0].request_id)
            self.assertEqual("normal", events[0].before["finish"])
            self.assertEqual("foil", events[0].after["finish"])
            self.assertEqual({"old_finish": "normal", "new_finish": "foil"}, events[0].metadata)

            item_events = list_inventory_audit_events(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                limit=1,
            )
            self.assertEqual(1, len(item_events))
            self.assertEqual("set_finish", item_events[0].action)
            self.assertRegex(events[0].occurred_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertRegex(item_events[0].occurred_at, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
