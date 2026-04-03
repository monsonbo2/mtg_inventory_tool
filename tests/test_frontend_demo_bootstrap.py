"""Regression coverage for the backend-owned frontend demo bootstrap."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.inventory.service import list_inventories, list_inventory_audit_events, list_owned_filtered
from tests.common import REPO_ROOT, fixture_path


class FrontendDemoBootstrapTest(unittest.TestCase):
    def assert_richer_demo_dataset(self, db_path: Path) -> None:
        inventories = list_inventories(db_path)
        self.assertEqual(["personal", "trade-binder"], [row.slug for row in inventories])

        personal = inventories[0]
        trade_binder = inventories[1]
        self.assertEqual(4, personal.item_rows)
        self.assertEqual(7, personal.total_cards)
        self.assertEqual(0, trade_binder.item_rows)
        self.assertEqual(0, trade_binder.total_cards)

        owned_rows = list_owned_filtered(
            db_path,
            inventory_slug="personal",
            provider="tcgplayer",
            limit=None,
            query=None,
            set_code=None,
            rarity=None,
            finish=None,
            condition_code=None,
            language_code=None,
            location=None,
            tags=None,
        )

        self.assertEqual(4, len(owned_rows))
        self.assertTrue({"foil", "normal", "etched"}.issubset({row.finish for row in owned_rows}))
        self.assertIn("LP", {row.condition_code for row in owned_rows})
        self.assertIn("ja", {row.language_code for row in owned_rows})
        self.assertTrue(any(row.notes is not None for row in owned_rows))
        self.assertTrue(any(row.notes is None for row in owned_rows))
        self.assertTrue(any(row.tags for row in owned_rows))
        self.assertTrue(any(not row.tags for row in owned_rows))
        self.assertTrue(any(row.acquisition_price is not None for row in owned_rows))
        self.assertTrue(any(row.acquisition_price is None for row in owned_rows))

        audit_rows = list_inventory_audit_events(
            db_path,
            inventory_slug="personal",
            limit=50,
        )
        actions = {row.action for row in audit_rows}
        self.assertTrue(
            {
                "add_card",
                "set_finish",
                "set_notes",
                "set_tags",
                "set_location",
                "set_quantity",
                "set_condition",
                "set_acquisition",
                "remove_card",
            }.issubset(actions)
        )

    def test_bootstrap_creates_richer_demo_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo.db"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/bootstrap_frontend_demo.py",
                    "--db",
                    str(db_path),
                    "--force",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertIn("Inventories seeded: personal, trade-binder", result.stdout)
            self.assertIn("Catalog mode: small", result.stdout)
            self.assert_richer_demo_dataset(db_path)

    def test_bootstrap_full_catalog_mode_imports_real_cards_without_demo_catalog_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo_full.db"
            scryfall_json = fixture_path("frontend_demo_full_catalog", "scryfall.json")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/bootstrap_frontend_demo.py",
                    "--db",
                    str(db_path),
                    "--force",
                    "--full-catalog",
                    "--scryfall-json",
                    str(scryfall_json),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertIn("Catalog mode: full", result.stdout)
            self.assertIn("Inventories seeded: personal, trade-binder", result.stdout)
            self.assertIn("Scryfall cards imported: 12", result.stdout)
            self.assertIn("Curated owned-item demo rows resolved from imported catalog printings.", result.stdout)
            self.assert_richer_demo_dataset(db_path)

            owned_rows = list_owned_filtered(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=None,
                query=None,
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
            )
            owned_by_name = {row.name: row for row in owned_rows}
            self.assertEqual(
                {
                    "Lightning Bolt": "fixture-bolt-mainstream-en",
                    "Counterspell": "fixture-counterspell-modern-en",
                    "Swords to Plowshares": "fixture-swords-ja-modern",
                    "Sol Ring": "fixture-sol-ring-mainstream-en",
                },
                {name: row.scryfall_id for name, row in owned_by_name.items()},
            )

            with connect(db_path) as connection:
                mtg_card_rows = connection.execute("SELECT COUNT(*) FROM mtg_cards").fetchone()[0]
                demo_card_rows = connection.execute(
                    "SELECT COUNT(*) FROM mtg_cards WHERE scryfall_id LIKE 'demo-%'"
                ).fetchone()[0]
                price_rows = connection.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]
                brainstorm_rows = connection.execute(
                    "SELECT COUNT(*) FROM mtg_cards WHERE name = 'Brainstorm'"
                ).fetchone()[0]
                owned_demo_rows = connection.execute(
                    "SELECT COUNT(*) FROM inventory_items WHERE scryfall_id LIKE 'demo-%'"
                ).fetchone()[0]

            self.assertEqual(12, mtg_card_rows)
            self.assertEqual(0, demo_card_rows)
            self.assertEqual(7, price_rows)
            self.assertEqual(1, brainstorm_rows)
            self.assertEqual(0, owned_demo_rows)

    def test_bootstrap_full_catalog_mode_requires_scryfall_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo_missing_fixture.db"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/bootstrap_frontend_demo.py",
                    "--db",
                    str(db_path),
                    "--force",
                    "--full-catalog",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("--scryfall-json is required with --full-catalog", result.stderr)

    def test_bootstrap_full_catalog_mode_fails_fast_when_demo_finish_constraints_cannot_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo_invalid_fixture.db"
            scryfall_json = fixture_path("frontend_demo_full_catalog_missing_finish", "scryfall.json")
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/bootstrap_frontend_demo.py",
                    "--db",
                    str(db_path),
                    "--force",
                    "--full-catalog",
                    "--scryfall-json",
                    str(scryfall_json),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("Could not seed full-catalog demo row for 'Lightning Bolt'", result.stderr)
            self.assertIn("finish 'foil'", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
