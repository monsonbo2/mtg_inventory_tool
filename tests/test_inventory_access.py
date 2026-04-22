"""Focused tests for inventory membership helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import ConflictError, NotFoundError, ValidationError
from mtg_source_stack.inventory.service import (
    actor_can_manage_inventory_share,
    actor_can_read_any_inventory,
    actor_can_read_inventory,
    actor_can_write_inventory,
    actor_inventory_role,
    can_manage_inventory_share,
    can_read_inventory,
    can_write_inventory,
    create_inventory,
    ensure_default_inventory,
    grant_inventory_membership,
    list_inventory_audit_events,
    list_inventory_memberships,
    list_visible_inventories,
    normalize_inventory_membership_role,
    remove_inventory_membership,
    revoke_inventory_membership,
    set_inventory_membership_role,
    update_inventory_membership_role,
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
        self.assertFalse(can_manage_inventory_share(inventory_role="viewer", actor_roles={"editor"}))
        self.assertTrue(can_read_inventory(inventory_role="editor", actor_roles={"editor"}))
        self.assertTrue(can_write_inventory(inventory_role="editor", actor_roles={"editor"}))
        self.assertFalse(can_manage_inventory_share(inventory_role="editor", actor_roles={"editor"}))
        self.assertTrue(can_read_inventory(inventory_role="owner", actor_roles={"editor"}))
        self.assertTrue(can_write_inventory(inventory_role="owner", actor_roles={"editor"}))
        self.assertTrue(can_manage_inventory_share(inventory_role="owner", actor_roles={"editor"}))
        self.assertFalse(can_read_inventory(inventory_role=None, actor_roles={"editor"}))
        self.assertFalse(can_write_inventory(inventory_role=None, actor_roles={"editor"}))
        self.assertFalse(can_manage_inventory_share(inventory_role=None, actor_roles={"editor"}))
        self.assertTrue(can_read_inventory(inventory_role=None, actor_roles={"admin"}))
        self.assertTrue(can_write_inventory(inventory_role=None, actor_roles={"admin"}))
        self.assertTrue(can_manage_inventory_share(inventory_role=None, actor_roles={"admin"}))

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

    def test_managed_membership_changes_are_audited_without_duplicate_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner@example.com",
            )

            granted = set_inventory_membership_role(
                db_path,
                inventory_slug="personal",
                member_actor_id="alice@example.com",
                role="viewer",
                actor_id="owner@example.com",
                actor_type="api",
                request_id="req-grant-member",
            )
            self.assertEqual("viewer", granted.role)

            repeated = set_inventory_membership_role(
                db_path,
                inventory_slug="personal",
                member_actor_id="alice@example.com",
                role="viewer",
                actor_id="owner@example.com",
                actor_type="api",
                request_id="req-noop-member",
            )
            self.assertEqual(granted, repeated)

            updated = update_inventory_membership_role(
                db_path,
                inventory_slug="personal",
                member_actor_id="alice@example.com",
                role="editor",
                actor_id="owner@example.com",
                actor_type="api",
                request_id="req-update-member",
            )
            self.assertEqual("editor", updated.role)

            removed = remove_inventory_membership(
                db_path,
                inventory_slug="personal",
                member_actor_id="alice@example.com",
                actor_id="owner@example.com",
                actor_type="api",
                request_id="req-remove-member",
            )
            self.assertEqual("alice@example.com", removed.actor_id)
            self.assertEqual("editor", removed.role)

            memberships = list_inventory_memberships(db_path, inventory_slug="personal")
            self.assertEqual([("owner@example.com", "owner")], [(row.actor_id, row.role) for row in memberships])
            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual(
                [
                    "revoke_inventory_membership",
                    "update_inventory_membership",
                    "grant_inventory_membership",
                ],
                [row.action for row in audit_rows],
            )
            self.assertEqual(["req-remove-member", "req-update-member", "req-grant-member"], [row.request_id for row in audit_rows])
            self.assertTrue(all(row.actor_id == "owner@example.com" for row in audit_rows))
            self.assertEqual("alice@example.com", audit_rows[0].metadata["member_actor_id"])
            self.assertEqual("editor", audit_rows[0].metadata["previous_role"])
            self.assertIsNone(audit_rows[0].metadata["role"])
            self.assertEqual("viewer", audit_rows[1].metadata["previous_role"])
            self.assertEqual("editor", audit_rows[1].metadata["role"])

    def test_managed_membership_update_requires_existing_member(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner@example.com",
            )

            with self.assertRaisesRegex(NotFoundError, "No inventory membership found for actor 'missing@example.com'"):
                update_inventory_membership_role(
                    db_path,
                    inventory_slug="personal",
                    member_actor_id="missing@example.com",
                    role="viewer",
                    actor_id="owner@example.com",
                )

    def test_managed_membership_changes_preserve_at_least_one_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner@example.com",
            )

            with self.assertRaisesRegex(ConflictError, "must retain at least one owner"):
                update_inventory_membership_role(
                    db_path,
                    inventory_slug="personal",
                    member_actor_id="owner@example.com",
                    role="editor",
                    actor_id="admin@example.com",
                    actor_type="api",
                    request_id="req-demote-last-owner",
                )
            with self.assertRaisesRegex(ConflictError, "must retain at least one owner"):
                remove_inventory_membership(
                    db_path,
                    inventory_slug="personal",
                    member_actor_id="owner@example.com",
                    actor_id="admin@example.com",
                    actor_type="api",
                    request_id="req-remove-last-owner",
                )

            set_inventory_membership_role(
                db_path,
                inventory_slug="personal",
                member_actor_id="second-owner@example.com",
                role="owner",
                actor_id="admin@example.com",
                actor_type="api",
                request_id="req-add-second-owner",
            )
            demoted = update_inventory_membership_role(
                db_path,
                inventory_slug="personal",
                member_actor_id="owner@example.com",
                role="editor",
                actor_id="admin@example.com",
                actor_type="api",
                request_id="req-demote-owner",
            )
            self.assertEqual("editor", demoted.role)
            removed = remove_inventory_membership(
                db_path,
                inventory_slug="personal",
                member_actor_id="owner@example.com",
                actor_id="admin@example.com",
                actor_type="api",
                request_id="req-remove-former-owner",
            )
            self.assertEqual("editor", removed.role)

            memberships = list_inventory_memberships(db_path, inventory_slug="personal")
            self.assertEqual([("second-owner@example.com", "owner")], [(row.actor_id, row.role) for row in memberships])

    def test_ensure_default_inventory_creates_owned_collection_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            created = ensure_default_inventory(
                db_path,
                actor_id="alice@example.com",
                actor_roles=frozenset(),
            )
            self.assertTrue(created.created)
            self.assertEqual("Collection", created.inventory.display_name)
            self.assertEqual("alice-collection", created.inventory.slug)
            self.assertIsNone(created.inventory.default_location)
            self.assertIsNone(created.inventory.default_tags)
            self.assertIsNone(created.inventory.notes)
            self.assertIsNone(created.inventory.acquisition_price)
            self.assertIsNone(created.inventory.acquisition_currency)

            repeated = ensure_default_inventory(
                db_path,
                actor_id="alice@example.com",
                actor_roles=frozenset(),
            )
            self.assertFalse(repeated.created)
            self.assertEqual(created.inventory.inventory_id, repeated.inventory.inventory_id)
            self.assertEqual(created.inventory.slug, repeated.inventory.slug)

            self.assertEqual(
                "owner",
                actor_inventory_role(
                    db_path,
                    inventory_slug="alice-collection",
                    actor_id="alice@example.com",
                ),
            )

            with connect(db_path) as connection:
                mapping_rows = connection.execute(
                    """
                    SELECT actor_id, inventory_id
                    FROM actor_default_inventories
                    """
                ).fetchall()
            self.assertEqual(
                [("alice@example.com", created.inventory.inventory_id)],
                [tuple(row) for row in mapping_rows],
            )

    def test_ensure_default_inventory_uses_suffix_when_slug_root_collides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            create_inventory(
                db_path,
                slug="alice-collection",
                display_name="Shared Alice Collection",
                description=None,
            )

            created = ensure_default_inventory(
                db_path,
                actor_id="alice@example.com",
                actor_roles=frozenset(),
            )

            self.assertTrue(created.created)
            self.assertEqual("alice-collection-2", created.inventory.slug)

    def test_ensure_default_inventory_allows_admin_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            created = ensure_default_inventory(
                db_path,
                actor_id="admin@example.com",
                actor_roles={"admin"},
            )

            self.assertTrue(created.created)
            self.assertEqual(
                "owner",
                actor_inventory_role(
                    db_path,
                    inventory_slug=created.inventory.slug,
                    actor_id="admin@example.com",
                ),
            )

    def test_ensure_default_inventory_creates_personal_inventory_even_if_actor_has_shared_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            create_inventory(
                db_path,
                slug="team",
                display_name="Team Collection",
                description=None,
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="team",
                actor_id="alice@example.com",
                role="viewer",
            )

            created = ensure_default_inventory(
                db_path,
                actor_id="alice@example.com",
                actor_roles=frozenset(),
            )

            self.assertTrue(created.created)
            self.assertEqual("alice-collection", created.inventory.slug)
            self.assertEqual(
                ["alice-collection", "team"],
                [
                    row.slug
                    for row in list_visible_inventories(
                        db_path,
                        actor_id="alice@example.com",
                        actor_roles=frozenset(),
                    )
                ],
            )

    def test_ensure_default_inventory_allows_authenticated_actor_without_global_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            created = ensure_default_inventory(
                db_path,
                actor_id="viewer@example.com",
                actor_roles=frozenset(),
            )

            self.assertTrue(created.created)
            self.assertEqual("viewer-collection", created.inventory.slug)
            self.assertEqual(
                "owner",
                actor_inventory_role(
                    db_path,
                    inventory_slug="viewer-collection",
                    actor_id="viewer@example.com",
                ),
            )

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

    def test_actor_write_access_respects_membership_and_admin_bypass(self) -> None:
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
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="editor@example.com",
                role="editor",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="owner@example.com",
                role="owner",
            )

            self.assertFalse(
                actor_can_write_inventory(
                    db_path,
                    inventory_slug="personal",
                    actor_id="viewer@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertTrue(
                actor_can_write_inventory(
                    db_path,
                    inventory_slug="personal",
                    actor_id="editor@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertTrue(
                actor_can_write_inventory(
                    db_path,
                    inventory_slug="personal",
                    actor_id="owner@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertFalse(
                actor_can_write_inventory(
                    db_path,
                    inventory_slug="admin-only",
                    actor_id="editor@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertTrue(
                actor_can_write_inventory(
                    db_path,
                    inventory_slug="admin-only",
                    actor_id="admin@example.com",
                    actor_roles={"admin"},
                )
            )

    def test_actor_share_link_management_requires_owner_or_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

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
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="editor@example.com",
                role="editor",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="owner@example.com",
                role="owner",
            )

            self.assertFalse(
                actor_can_manage_inventory_share(
                    db_path,
                    inventory_slug="personal",
                    actor_id="viewer@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertFalse(
                actor_can_manage_inventory_share(
                    db_path,
                    inventory_slug="personal",
                    actor_id="editor@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertTrue(
                actor_can_manage_inventory_share(
                    db_path,
                    inventory_slug="personal",
                    actor_id="owner@example.com",
                    actor_roles=frozenset(),
                )
            )
            self.assertTrue(
                actor_can_manage_inventory_share(
                    db_path,
                    inventory_slug="personal",
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
