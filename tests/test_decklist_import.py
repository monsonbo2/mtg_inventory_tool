"""Focused tests for pasted decklist parsing and default-printing resolution."""

from __future__ import annotations

import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import NotFoundError, ValidationError
from mtg_source_stack.inventory.catalog import resolve_default_card_row_for_name
from mtg_source_stack.inventory.decklist_import import (
    ParsedDecklistEntry,
    ParsedDecklistText,
    PlannedDecklistImport,
    import_decklist_text,
    parse_decklist_text,
    parse_decklist_text_with_metadata,
    resolve_decklist_entry_card_row,
)
from mtg_source_stack.inventory.service import create_inventory


class DecklistImportTest(unittest.TestCase):
    def test_import_decklist_text_defaults_to_initialize_if_needed_schema_policy(self) -> None:
        parsed_decklist = ParsedDecklistText(
            deck_name=None,
            entries=[ParsedDecklistEntry(line_number=1, quantity=1, name="Test Card")],
        )
        plan = PlannedDecklistImport(
            deck_name=None,
            rows_seen=1,
            requested_card_quantity=1,
            pending_rows=[],
            resolution_issues=[],
        )
        prepared_db_path = Path("/tmp/prepared_decklist_import.db")

        with (
            patch(
                "mtg_source_stack.inventory.decklist_import.parse_decklist_text_with_metadata",
                return_value=parsed_decklist,
            ),
            patch(
                "mtg_source_stack.inventory.decklist_import.prepare_database",
                return_value=prepared_db_path,
            ) as prepare_database,
            patch(
                "mtg_source_stack.inventory.decklist_import._resolve_decklist_import_plan",
                return_value=plan,
            ) as resolve_decklist_import_plan,
            patch(
                "mtg_source_stack.inventory.decklist_import._import_pending_rows",
                return_value=[],
            ) as import_pending_rows,
        ):
            result = import_decklist_text(
                "collection.db",
                deck_text="1 Test Card",
                default_inventory="personal",
            )

        prepare_database.assert_called_once_with(
            "collection.db",
            schema_policy="initialize_if_needed",
        )
        self.assertEqual(prepared_db_path, resolve_decklist_import_plan.call_args.args[0])
        self.assertEqual(prepared_db_path, import_pending_rows.call_args.args[0])
        self.assertEqual(1, result["rows_seen"])

    def test_import_decklist_text_accepts_require_current_schema_policy(self) -> None:
        parsed_decklist = ParsedDecklistText(
            deck_name=None,
            entries=[ParsedDecklistEntry(line_number=1, quantity=1, name="Test Card")],
        )
        plan = PlannedDecklistImport(
            deck_name=None,
            rows_seen=1,
            requested_card_quantity=1,
            pending_rows=[],
            resolution_issues=[],
        )
        prepared_db_path = Path("/tmp/prepared_decklist_import.db")

        with (
            patch(
                "mtg_source_stack.inventory.decklist_import.parse_decklist_text_with_metadata",
                return_value=parsed_decklist,
            ),
            patch(
                "mtg_source_stack.inventory.decklist_import.prepare_database",
                return_value=prepared_db_path,
            ) as prepare_database,
            patch(
                "mtg_source_stack.inventory.decklist_import._resolve_decklist_import_plan",
                return_value=plan,
            ),
            patch(
                "mtg_source_stack.inventory.decklist_import._import_pending_rows",
                return_value=[],
            ),
        ):
            import_decklist_text(
                "collection.db",
                deck_text="1 Test Card",
                default_inventory="personal",
                schema_policy="require_current",
            )

        prepare_database.assert_called_once_with(
            "collection.db",
            schema_policy="require_current",
        )

    def _insert_card(
        self,
        db_path: Path,
        *,
        scryfall_id: str,
        oracle_id: str,
        name: str,
        set_code: str,
        collector_number: str,
        lang: str = "en",
        released_at: str = "2024-01-01",
        finishes_json: str = '["normal","foil"]',
        set_type: str | None = "expansion",
        booster: int = 1,
        promo_types_json: str = "[]",
        is_default_add_searchable: int = 1,
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
                    lang,
                    released_at,
                    finishes_json,
                    image_uris_json,
                    set_type,
                    booster,
                    promo_types_json,
                    is_default_add_searchable
                )
                VALUES (?, ?, ?, ?, 'Test Set', ?, ?, ?, ?, '{"small":"https://example.test/card-small.jpg"}', ?, ?, ?, ?)
                """,
                (
                    scryfall_id,
                    oracle_id,
                    name,
                    set_code,
                    collector_number,
                    lang,
                    released_at,
                    finishes_json,
                    set_type,
                    booster,
                    promo_types_json,
                    is_default_add_searchable,
                ),
            )
            connection.commit()

    def test_parse_decklist_text_accepts_common_quantity_formats(self) -> None:
        entries = parse_decklist_text(
            "\n".join(
                [
                    "4 Lightning Bolt",
                    "4x Counterspell",
                    "4 x Brainstorm",
                ]
            )
        )

        self.assertEqual(
            [
                (1, 4, "Lightning Bolt", "mainboard"),
                (2, 4, "Counterspell", "mainboard"),
                (3, 4, "Brainstorm", "mainboard"),
            ],
            [(entry.line_number, entry.quantity, entry.name, entry.section) for entry in entries],
        )

    def test_parse_decklist_text_tracks_sections_and_printing_hints(self) -> None:
        entries = parse_decklist_text(
            "\n".join(
                [
                    "Commander",
                    "1 Atraxa, Praetors' Voice",
                    "Sideboard (15)",
                    "SB: 2 Pyroblast",
                    "3 Verdant Catacombs (MH2) 260",
                    "Companion: Jegantha, the Wellspring",
                ]
            )
        )

        self.assertEqual(
            [
                (2, 1, "Atraxa, Praetors' Voice", "commander", None, None),
                (4, 2, "Pyroblast", "sideboard", None, None),
                (5, 3, "Verdant Catacombs", "sideboard", "MH2", "260"),
                (6, 1, "Jegantha, the Wellspring", "companion", None, None),
            ],
            [
                (
                    entry.line_number,
                    entry.quantity,
                    entry.name,
                    entry.section,
                    entry.set_code,
                    entry.collector_number,
                )
                for entry in entries
            ],
        )

    def test_parse_decklist_text_accepts_moxfield_style_export_preamble(self) -> None:
        parsed = parse_decklist_text_with_metadata(
            "\n".join(
                [
                    "About",
                    "Name Esper Legends",
                    "",
                    "Commander",
                    "1 Raffine, Scheming Seer",
                    "",
                    "Deck",
                    "4 Consider",
                    "2 Go for the Throat",
                    "",
                    "Sideboard",
                    "2 Disdainful Stroke",
                ]
            )
        )

        self.assertEqual("Esper Legends", parsed.deck_name)
        self.assertEqual(
            [
                (5, 1, "Raffine, Scheming Seer", "commander"),
                (8, 4, "Consider", "mainboard"),
                (9, 2, "Go for the Throat", "mainboard"),
                (12, 2, "Disdainful Stroke", "sideboard"),
            ],
            [(entry.line_number, entry.quantity, entry.name, entry.section) for entry in parsed.entries],
        )

    def test_parse_decklist_text_rejects_unsupported_lines_with_line_numbers(self) -> None:
        with self.assertRaisesRegex(
            ValidationError,
            "Decklist line 2: expected '<qty> <card name>' or a supported section header.",
        ):
            parse_decklist_text(
                "\n".join(
                    [
                        "Mainboard",
                        "Lightning Bolt",
                    ]
                )
            )

    def test_resolve_default_card_row_for_name_prefers_mainstream_english_default_printing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="deck-mainstream-en",
                oracle_id="deck-oracle-1",
                name="Deck Policy Card",
                set_code="bro",
                collector_number="81",
                lang="en",
                released_at="2023-11-18",
                set_type="expansion",
                booster=1,
            )
            self._insert_card(
                db_path,
                scryfall_id="deck-newer-ja",
                oracle_id="deck-oracle-1",
                name="Deck Policy Card",
                set_code="mkm",
                collector_number="82",
                lang="ja",
                released_at="2024-02-09",
                set_type="expansion",
                booster=1,
            )
            self._insert_card(
                db_path,
                scryfall_id="deck-promo-en",
                oracle_id="deck-oracle-1",
                name="Deck Policy Card",
                set_code="pneo",
                collector_number="83",
                lang="en",
                released_at="2024-03-01",
                set_type="expansion",
                booster=0,
                promo_types_json='["promo_pack"]',
            )

            with connect(db_path) as connection:
                resolved = resolve_default_card_row_for_name(connection, name="Deck Policy Card")

            self.assertEqual("deck-mainstream-en", resolved["scryfall_id"])
            self.assertEqual("en", resolved["lang"])

    def test_resolve_default_card_row_for_name_rejects_multiple_oracle_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="ambiguous-a",
                oracle_id="ambiguous-oracle-a",
                name="Ambiguous Bolt",
                set_code="lea",
                collector_number="161",
            )
            self._insert_card(
                db_path,
                scryfall_id="ambiguous-b",
                oracle_id="ambiguous-oracle-b",
                name="Ambiguous Bolt",
                set_code="2ed",
                collector_number="162",
            )

            with connect(db_path) as connection:
                with self.assertRaisesRegex(
                    ValidationError,
                    "Multiple cards matched that exact name.",
                ):
                    resolve_default_card_row_for_name(connection, name="Ambiguous Bolt")

    def test_resolve_decklist_entry_card_row_uses_exact_printing_hints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="verdant-zen",
                oracle_id="verdant-oracle",
                name="Verdant Catacombs",
                set_code="zen",
                collector_number="229",
            )
            self._insert_card(
                db_path,
                scryfall_id="verdant-mh2",
                oracle_id="verdant-oracle",
                name="Verdant Catacombs",
                set_code="mh2",
                collector_number="260",
            )

            entry = parse_decklist_text("3 Verdant Catacombs (MH2) 260")[0]
            with connect(db_path) as connection:
                resolved = resolve_decklist_entry_card_row(connection, entry=entry)

            self.assertEqual("verdant-mh2", resolved["scryfall_id"])

    def test_resolve_default_card_row_for_name_rejects_missing_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                with self.assertRaises(NotFoundError):
                    resolve_default_card_row_for_name(connection, name="Missing Card")

    def test_import_decklist_text_supports_preview_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="deck-bolt",
                oracle_id="deck-bolt-oracle",
                name="Lightning Bolt",
                set_code="lea",
                collector_number="161",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            preview = import_decklist_text(
                db_path,
                deck_text="About\nName Burn Test\n\nDeck\n4 Lightning Bolt",
                default_inventory="personal",
                dry_run=True,
            )
            self.assertTrue(preview["dry_run"])
            self.assertEqual("Burn Test", preview["deck_name"])
            self.assertEqual(1, preview["rows_seen"])
            self.assertEqual(1, preview["rows_written"])
            self.assertTrue(preview["ready_to_commit"])
            self.assertEqual([], preview["resolution_issues"])
            self.assertEqual(4, preview["summary"]["requested_card_quantity"])
            self.assertEqual(5, preview["imported_rows"][0]["decklist_line"])
            self.assertEqual("mainboard", preview["imported_rows"][0]["section"])
            self.assertEqual(4, preview["imported_rows"][0]["quantity"])
            self.assertEqual("explicit", preview["imported_rows"][0]["printing_selection_mode"])
            self.assertEqual(0, preview["summary"]["unresolved_card_quantity"])

            with connect(db_path) as connection:
                self.assertEqual(0, connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0])

            committed = import_decklist_text(
                db_path,
                deck_text="4 Lightning Bolt",
                default_inventory="personal",
                dry_run=False,
            )
            self.assertFalse(committed["dry_run"])
            self.assertIsNone(committed["deck_name"])
            self.assertEqual(1, committed["rows_written"])
            self.assertTrue(committed["ready_to_commit"])
            self.assertEqual([], committed["resolution_issues"])
            self.assertEqual(4, committed["summary"]["requested_card_quantity"])
            self.assertEqual(0, committed["summary"]["unresolved_card_quantity"])
            self.assertEqual("explicit", committed["imported_rows"][0]["printing_selection_mode"])

            with connect(db_path) as connection:
                item_row = connection.execute(
                    "SELECT quantity, finish, printing_selection_mode FROM inventory_items"
                ).fetchone()
            self.assertEqual(4, item_row["quantity"])
            self.assertEqual("normal", item_row["finish"])
            self.assertEqual("explicit", item_row["printing_selection_mode"])

    def test_import_decklist_text_marks_name_only_default_rows_as_defaulted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="deck-default-mainstream-en",
                oracle_id="deck-default-oracle",
                name="Deck Defaulted Card",
                set_code="bro",
                collector_number="81",
                released_at="2023-11-18",
                finishes_json='["normal"]',
                set_type="expansion",
                booster=1,
            )
            self._insert_card(
                db_path,
                scryfall_id="deck-default-promo-en",
                oracle_id="deck-default-oracle",
                name="Deck Defaulted Card",
                set_code="pneo",
                collector_number="82",
                released_at="2024-03-01",
                finishes_json='["normal"]',
                set_type="expansion",
                booster=0,
                promo_types_json='["promo_pack"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            committed = import_decklist_text(
                db_path,
                deck_text="2 Deck Defaulted Card",
                default_inventory="personal",
                dry_run=False,
            )

            self.assertEqual("deck-default-mainstream-en", committed["imported_rows"][0]["scryfall_id"])
            self.assertEqual("defaulted", committed["imported_rows"][0]["printing_selection_mode"])

            with connect(db_path) as connection:
                item_row = connection.execute(
                    "SELECT scryfall_id, printing_selection_mode FROM inventory_items"
                ).fetchone()

            self.assertEqual("deck-default-mainstream-en", item_row["scryfall_id"])
            self.assertEqual("defaulted", item_row["printing_selection_mode"])

    def test_import_decklist_text_returns_structured_ambiguity_preview_and_accepts_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="ambiguous-main",
                oracle_id="ambiguous-oracle-main",
                name="Ambiguous Bolt",
                set_code="lea",
                collector_number="161",
                finishes_json='["normal"]',
            )
            self._insert_card(
                db_path,
                scryfall_id="ambiguous-other",
                oracle_id="ambiguous-oracle-other",
                name="Ambiguous Bolt",
                set_code="2ed",
                collector_number="162",
                finishes_json='["normal"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            preview = import_decklist_text(
                db_path,
                deck_text="4 Ambiguous Bolt",
                default_inventory="personal",
                dry_run=True,
            )
            self.assertFalse(preview["ready_to_commit"])
            self.assertEqual(0, preview["rows_written"])
            self.assertEqual(4, preview["summary"]["requested_card_quantity"])
            self.assertEqual(4, preview["summary"]["unresolved_card_quantity"])
            self.assertEqual(1, len(preview["resolution_issues"]))
            issue = preview["resolution_issues"][0]
            self.assertEqual("ambiguous_card_name", issue["kind"])
            self.assertEqual(1, issue["decklist_line"])
            self.assertEqual("Ambiguous Bolt", issue["requested"]["name"])
            self.assertEqual(
                {("ambiguous-main", "normal"), ("ambiguous-other", "normal")},
                {(option["scryfall_id"], option["finish"]) for option in issue["options"]},
            )

            with self.assertRaisesRegex(ValidationError, "Unresolved decklist import ambiguities remain."):
                import_decklist_text(
                    db_path,
                    deck_text="4 Ambiguous Bolt",
                    default_inventory="personal",
                    dry_run=False,
                )

            committed = import_decklist_text(
                db_path,
                deck_text="4 Ambiguous Bolt",
                default_inventory="personal",
                dry_run=False,
                resolutions=[
                    {
                        "decklist_line": 1,
                        "scryfall_id": "ambiguous-other",
                        "finish": "normal",
                    }
                ],
            )
            self.assertTrue(committed["ready_to_commit"])
            self.assertEqual([], committed["resolution_issues"])
            self.assertEqual("ambiguous-other", committed["imported_rows"][0]["scryfall_id"])

    def test_import_decklist_text_returns_finish_required_issue_without_normal_option(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="finish-choice-card",
                oracle_id="finish-choice-oracle",
                name="Finish Choice Card",
                set_code="tst",
                collector_number="201",
                finishes_json='["foil","etched"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            preview = import_decklist_text(
                db_path,
                deck_text="1 Finish Choice Card",
                default_inventory="personal",
                dry_run=True,
            )
            self.assertFalse(preview["ready_to_commit"])
            self.assertEqual("finish_required", preview["resolution_issues"][0]["kind"])
            self.assertEqual(
                {("finish-choice-card", "foil"), ("finish-choice-card", "etched")},
                {
                    (option["scryfall_id"], option["finish"])
                    for option in preview["resolution_issues"][0]["options"]
                },
            )

            committed = import_decklist_text(
                db_path,
                deck_text="1 Finish Choice Card",
                default_inventory="personal",
                dry_run=False,
                resolutions=[
                    {
                        "decklist_line": 1,
                        "scryfall_id": "finish-choice-card",
                        "finish": "foil",
                    }
                ],
            )
            self.assertEqual("foil", committed["imported_rows"][0]["finish"])

    def test_import_decklist_text_requires_default_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_card(
                db_path,
                scryfall_id="deck-bolt",
                oracle_id="deck-bolt-oracle",
                name="Lightning Bolt",
                set_code="lea",
                collector_number="161",
                finishes_json='["normal"]',
            )

            with self.assertRaisesRegex(ValidationError, "default_inventory is required for decklist imports."):
                import_decklist_text(
                    db_path,
                    deck_text="4 Lightning Bolt",
                    default_inventory=None,
                )


if __name__ == "__main__":
    unittest.main()
