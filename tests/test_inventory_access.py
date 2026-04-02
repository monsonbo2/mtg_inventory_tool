"""Focused tests for inventory membership helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import NotFoundError, ValidationError
from mtg_source_stack.inventory.service import (
    actor_can_read_any_inventory,
    actor_can_read_inventory,
    actor_inventory_role,
    can_read_inventory,
    can_write_inventory,
    create_inventory,
    grant_inventory_membership,
    list_inventory_memberships,
    list_visible_inventories,
    normalize_inventory_membership_role,
    revoke_inventory_membership,
)


class InventoryAccessTest(unittest.TestCase):
    def test_normalize_inventory_membership_role_rejects_unknown_values(self) -> None:
        self.assertEqual("viewer", normalize_inventory_membership_role(" Viewer "))
        self.assertEqual("editor", normalize_inventory_membership_role("editor"))
        self.assertEqual("owner", normalize_inventory_membership_role("OWNER"))

        with self.assertRaisesRegex(ValidationError, "inventory membership role must be one of"):
            normalize_inventory_membership_role("manager")

    def test_can_read_and_write_inventory_roles(self) -> None:
        self.assertTrue(can_read_inventory(inventory_role="viewer", actor_roles={"editor"}))
        self.assertFalse(can_write_inventory(inventory_role="viewer", actor_roles={"editor"}))
        self.assertTrue(can_read_inventory(inventory_role="editor", actor_roles={"editor"}))
        self.assertTrue(can_write_inventory(inventory_role="editor", actor_roles={"editor"}))
        self.assertTrue(can_read_inventory(inventory_role="owner", actor_roles={"editor"}))
        self.assertTrue(can_write_inventory(inventory_role="owner", actor_roles={"editor"}))
        self.assertFalse(can_read_inventory(inventory_role=None, actor_roles={"editor"}))
        self.assertFalse(can_write_inventory(inventory_role=None, actor_roles={"editor"}))
        self.assertTrue(can_read_inventory(inventory_role=None, actor_roles={"admin"}))
        self.assertTrue(can_write_inventory(inventory_role=None, actor_roles={"admin"}))

    def test_grant_list_and_revoke_inventory_memberships(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            granted = grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="alice@example.com",
                role="viewer",
            )
            self.assertEqual("personal", granted.inventory)
            self.assertEqual("alice@example.com", granted.actor_id)
            self.assertEqual("viewer", granted.role)

            updated = grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="alice@example.com",
                role="editor",
            )
            self.assertEqual("editor", updated.role)

            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="bob@example.com",
                role="owner",
            )

            memberships = list_inventory_memberships(db_path, inventory_slug="personal")
            self.assertEqual(
                [
                    ("alice@example.com", "editor"),
                    ("bob@example.com", "owner"),
                ],
                [(row.actor_id, row.role) for row in memberships],
            )

            self.assertEqual(
                "editor",
                actor_inventory_role(
                    db_path,
                    inventory_slug="personal",
                    actor_id="alice@example.com",
                ),
            )
            self.assertIsNone(
                actor_inventory_role(
                    db_path,
                    inventory_slug="personal",
                    actor_id="charlie@example.com",
                )
            )

            removed = revoke_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="alice@example.com",
            )
            self.assertEqual("personal", removed.inventory)
            self.assertEqual("alice@example.com", removed.actor_id)
            self.assertEqual("editor", removed.role)

            memberships_after = list_inventory_memberships(db_path, inventory_slug="personal")
            self.assertEqual([("bob@example.com", "owner")], [(row.actor_id, row.role) for row in memberships_after])

    def test_list_visible_inventories_filters_memberships_with_admin_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            create_inventory(
                db_path,
                slug="admin-only",
                display_name="Admin Only",
                description=None,
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner@example.com",
            )
            create_inventory(
                db_path,
                slug="team",
                display_name="Team Collection",
                description=None,
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer@example.com",
                role="viewer",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="team",
                actor_id="viewer@example.com",
                role="editor",
            )

            viewer_rows = list_visible_inventories(
                db_path,
                actor_id="viewer@example.com",
                actor_roles=frozenset(),
            )
            self.assertEqual(["personal", "team"], [row.slug for row in viewer_rows])

            admin_rows = list_visible_inventories(
                db_path,
                actor_id="admin@example.com",
                actor_roles={"admin"},
            )
            self.assertEqual(["admin-only", "personal", "team"], [row.slug for row in admin_rows])

            self.assertEqual(
                [],
                list_visible_inventories(
                    db_path,
                    actor_id="outsider@example.com",
                    actor_roles=frozenset(),
                ),
            )

    def test_actor_read_access_respects_membership_and_admin_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            create_inventory(
                db_path,
                slug="admin-only",
                display_name="Admin Only",
                description=None,
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer@example.com",
                role="viewer",
            )

            self.assertTrue(
                actor_can_read_inventory(
                    db_path,
                    inventory_slug="personal",
                    actor_id="viewer@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertFalse(
                actor_can_read_inventory(
                    db_path,
                    inventory_slug="admin-only",
                    actor_id="viewer@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertTrue(
                actor_can_read_inventory(
                    db_path,
                    inventory_slug="admin-only",
                    actor_id="admin@example.com",
                    actor_roles={"admin"},
                )
            )
            self.assertTrue(
                actor_can_read_any_inventory(
                    db_path,
                    actor_id="viewer@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertFalse(
                actor_can_read_any_inventory(
                    db_path,
                    actor_id="outsider@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertTrue(
                actor_can_read_any_inventory(
                    db_path,
                    actor_id="admin@example.com",
                    actor_roles={"admin"},
                )
            )

    def test_create_inventory_grants_owner_membership_when_actor_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            result = create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner@example.com",
            )

            self.assertEqual("personal", result.slug)
            self.assertEqual(
                "owner",
                actor_inventory_role(
                    db_path,
                    inventory_slug="personal",
                    actor_id="owner@example.com",
                ),
            )

    def test_membership_commands_fail_cleanly_for_missing_inventory_or_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with self.assertRaisesRegex(NotFoundError, "Inventory 'missing' was not found."):
                list_inventory_memberships(db_path, inventory_slug="missing")

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            with self.assertRaisesRegex(NotFoundError, "No inventory membership found for actor 'alice@example.com'"):
                revoke_inventory_membership(
                    db_path,
                    inventory_slug="personal",
                    actor_id="alice@example.com",
                )
