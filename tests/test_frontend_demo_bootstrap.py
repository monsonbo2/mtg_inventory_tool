"""Regression coverage for the backend-owned frontend demo bootstrap."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mtg_source_stack.inventory.service import list_inventories, list_inventory_audit_events, list_owned_filtered
from tests.common import REPO_ROOT


class FrontendDemoBootstrapTest(unittest.TestCase):
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
