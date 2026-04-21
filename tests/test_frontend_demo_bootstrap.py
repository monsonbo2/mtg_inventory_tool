"""Regression coverage for the backend-owned frontend demo bootstrap."""

from __future__ import annotations

from decimal import Decimal
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.inventory.service import (
    actor_inventory_role,
    list_inventories,
    list_inventory_audit_events,
    list_owned_filtered,
    summarize_actor_access,
)
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
            self.assertIn("npm run backend:demo -- --db", result.stdout)
            self.assert_richer_demo_dataset(db_path)

    def test_bootstrap_can_seed_shared_service_validation_fixtures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo_shared.db"
            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/bootstrap_frontend_demo.py",
                    "--db",
                    str(db_path),
                    "--force",
                    "--shared-service-fixtures",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertIn("Shared-service validation fixtures: enabled", result.stdout)
            self.assertIn("new-user@example.com", result.stdout)
            self.assertIn("bootstrapped@example.com", result.stdout)
            self.assertIn("viewer@example.com", result.stdout)
            self.assertIn("writer@example.com", result.stdout)
            self.assertIn("admin@example.com", result.stdout)
            inventories = list_inventories(db_path)
            self.assertEqual(
                ["bootstrapped-collection", "personal", "trade-binder"],
                [row.slug for row in inventories],
            )
            personal = next(row for row in inventories if row.slug == "personal")
            trade_binder = next(row for row in inventories if row.slug == "trade-binder")
            bootstrapped = next(row for row in inventories if row.slug == "bootstrapped-collection")
            self.assertEqual(4, personal.item_rows)
            self.assertEqual(7, personal.total_cards)
            self.assertEqual(0, trade_binder.item_rows)
            self.assertEqual(0, trade_binder.total_cards)
            self.assertEqual(0, bootstrapped.item_rows)
            self.assertEqual(0, bootstrapped.total_cards)
            self.assertEqual(
                "viewer",
                actor_inventory_role(
                    db_path,
                    inventory_slug="personal",
                    actor_id="viewer@example.com",
                ),
            )
            self.assertEqual(
                "editor",
                actor_inventory_role(
                    db_path,
                    inventory_slug="trade-binder",
                    actor_id="writer@example.com",
                ),
            )

            new_user_summary = summarize_actor_access(
                db_path,
                actor_id="new-user@example.com",
                actor_roles=frozenset(),
            )
            self.assertTrue(new_user_summary.can_bootstrap)
            self.assertFalse(new_user_summary.has_readable_inventory)
            self.assertEqual(0, new_user_summary.visible_inventory_count)
            self.assertIsNone(new_user_summary.default_inventory_slug)

            no_access_summary = summarize_actor_access(
                db_path,
                actor_id="no-access@example.com",
                actor_roles=frozenset(),
            )
            self.assertTrue(no_access_summary.can_bootstrap)
            self.assertFalse(no_access_summary.has_readable_inventory)
            self.assertEqual(0, no_access_summary.visible_inventory_count)
            self.assertIsNone(no_access_summary.default_inventory_slug)

            bootstrapped_summary = summarize_actor_access(
                db_path,
                actor_id="bootstrapped@example.com",
                actor_roles=frozenset(),
            )
            self.assertTrue(bootstrapped_summary.can_bootstrap)
            self.assertTrue(bootstrapped_summary.has_readable_inventory)
            self.assertEqual(1, bootstrapped_summary.visible_inventory_count)
            self.assertEqual("bootstrapped-collection", bootstrapped_summary.default_inventory_slug)

            viewer_summary = summarize_actor_access(
                db_path,
                actor_id="viewer@example.com",
                actor_roles=frozenset(),
            )
            self.assertTrue(viewer_summary.can_bootstrap)
            self.assertTrue(viewer_summary.has_readable_inventory)
            self.assertEqual(1, viewer_summary.visible_inventory_count)
            self.assertIsNone(viewer_summary.default_inventory_slug)

            writer_summary = summarize_actor_access(
                db_path,
                actor_id="writer@example.com",
                actor_roles=frozenset(),
            )
            self.assertTrue(writer_summary.can_bootstrap)
            self.assertTrue(writer_summary.has_readable_inventory)
            self.assertEqual(1, writer_summary.visible_inventory_count)
            self.assertIsNone(writer_summary.default_inventory_slug)

            admin_summary = summarize_actor_access(
                db_path,
                actor_id="admin@example.com",
                actor_roles={"admin"},
            )
            self.assertTrue(admin_summary.can_bootstrap)
            self.assertTrue(admin_summary.has_readable_inventory)
            self.assertEqual(3, admin_summary.visible_inventory_count)
            self.assertIsNone(admin_summary.default_inventory_slug)

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
            self.assertIn("Price mode: curated demo seed pricing.", result.stdout)
            self.assertIn("Curated owned-item demo rows resolved from imported catalog printings.", result.stdout)
            self.assertIn("npm run backend:demo -- --db", result.stdout)
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

    def test_bootstrap_full_catalog_mode_can_import_real_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo_full_real_prices.db"
            scryfall_json = fixture_path("frontend_demo_full_catalog", "scryfall.json")
            identifiers_json = fixture_path("frontend_demo_full_catalog", "identifiers.json")
            prices_json = fixture_path("frontend_demo_full_catalog", "prices.json")
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
                    "--identifiers-json",
                    str(identifiers_json),
                    "--prices-json",
                    str(prices_json),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )

            self.assertIn("Catalog mode: full", result.stdout)
            self.assertIn("MTGJSON identifier links imported: 6", result.stdout)
            self.assertIn("MTGJSON price snapshots imported: 8", result.stdout)
            self.assertIn("Price mode: imported MTGJSON pricing.", result.stdout)
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
            self.assertEqual(Decimal("7.10"), owned_by_name["Lightning Bolt"].unit_price)
            self.assertEqual(Decimal("1.99"), owned_by_name["Counterspell"].unit_price)
            self.assertEqual(Decimal("4.44"), owned_by_name["Swords to Plowshares"].unit_price)
            self.assertEqual(Decimal("5.40"), owned_by_name["Sol Ring"].unit_price)

            with connect(db_path) as connection:
                mtgjson_price_rows = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM price_snapshots
                    WHERE source_name = 'mtgjson_all_prices_today'
                    """
                ).fetchone()[0]
                demo_seed_price_rows = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM price_snapshots
                    WHERE source_name = 'demo-seed'
                    """
                ).fetchone()[0]
                brainstorm_price_rows = connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM price_snapshots
                    WHERE scryfall_id = 'fixture-brainstorm-en'
                    """
                ).fetchone()[0]

            self.assertEqual(8, mtgjson_price_rows)
            self.assertEqual(0, demo_seed_price_rows)
            self.assertEqual(1, brainstorm_price_rows)

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

    def test_bootstrap_full_catalog_mode_requires_identifiers_and_prices_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo_missing_prices.db"
            scryfall_json = fixture_path("frontend_demo_full_catalog", "scryfall.json")
            identifiers_json = fixture_path("frontend_demo_full_catalog", "identifiers.json")
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
                    "--identifiers-json",
                    str(identifiers_json),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn(
                "--identifiers-json and --prices-json must be provided together with --full-catalog.",
                result.stderr,
            )

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

    def test_bootstrap_full_catalog_mode_handles_sol_ring_when_default_etched_printing_lacks_normal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "frontend_demo_sol_ring_etched.db"
            source_rows = json.loads(
                fixture_path("frontend_demo_full_catalog", "scryfall.json").read_text(encoding="utf-8")
            )
            for row in source_rows:
                if row["id"] == "fixture-sol-ring-mainstream-en":
                    row["finishes"] = ["etched"]
                    row["released_at"] = "2024-08-02"

            scryfall_json = Path(tmp_dir) / "sol_ring_etched_only.json"
            scryfall_json.write_text(json.dumps(source_rows), encoding="utf-8")

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
            self.assertEqual("fixture-sol-ring-mainstream-en", owned_by_name["Sol Ring"].scryfall_id)
            self.assertEqual("etched", owned_by_name["Sol Ring"].finish)
