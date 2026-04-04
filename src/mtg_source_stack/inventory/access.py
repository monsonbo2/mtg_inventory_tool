"""Inventory membership helpers and access predicates."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import NotFoundError, ValidationError
from .access_models import InventoryMembershipRemovalResult, InventoryMembershipRow
from .normalize import normalize_inventory_slug


INVENTORY_MEMBERSHIP_ROLES = frozenset({"viewer", "editor", "owner"})
INVENTORY_READ_ROLES = frozenset({"viewer", "editor", "owner"})
INVENTORY_WRITE_ROLES = frozenset({"editor", "owner"})


def normalize_inventory_membership_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized not in INVENTORY_MEMBERSHIP_ROLES:
        accepted = ", ".join(sorted(INVENTORY_MEMBERSHIP_ROLES))
        raise ValidationError(f"inventory membership role must be one of: {accepted}.")
    return normalized


def _normalize_actor_id(actor_id: str) -> str:
    normalized = actor_id.strip()
    if not normalized:
        raise ValidationError("actor_id is required.")
    return normalized


def _inventory_row_from_slug(connection: sqlite3.Connection, inventory_slug: str) -> sqlite3.Row:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    row = connection.execute(
        """
        SELECT id, slug
        FROM inventories
        WHERE slug = ?
        """,
        (inventory_slug,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Inventory '{inventory_slug}' was not found.")
    return row


def _membership_row_from_identity(
    connection: sqlite3.Connection,
    *,
    inventory_id: int,
    actor_id: str,
) -> InventoryMembershipRow:
    row = connection.execute(
        """
        SELECT
            i.slug AS inventory,
            im.actor_id,
            im.role,
            im.created_at,
            im.updated_at
        FROM inventory_memberships im
        JOIN inventories i ON i.id = im.inventory_id
        WHERE im.inventory_id = ? AND im.actor_id = ?
        """,
        (inventory_id, actor_id),
    ).fetchone()
    if row is None:
        raise NotFoundError("Inventory membership row was not found after write.")
    return InventoryMembershipRow(
        inventory=row["inventory"],
        actor_id=row["actor_id"],
        role=row["role"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def grant_inventory_membership_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_id: int,
    actor_id: str,
    role: str,
) -> InventoryMembershipRow:
    normalized_actor_id = _normalize_actor_id(actor_id)
    normalized_role = normalize_inventory_membership_role(role)
    connection.execute(
        """
        INSERT INTO inventory_memberships (inventory_id, actor_id, role)
        VALUES (?, ?, ?)
        ON CONFLICT (inventory_id, actor_id)
        DO UPDATE SET
            role = excluded.role,
            updated_at = CURRENT_TIMESTAMP
        """,
        (inventory_id, normalized_actor_id, normalized_role),
    )
    return _membership_row_from_identity(
        connection,
        inventory_id=inventory_id,
        actor_id=normalized_actor_id,
    )


def grant_inventory_membership(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str,
    role: str,
) -> InventoryMembershipRow:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory = _inventory_row_from_slug(connection, inventory_slug)
        membership = grant_inventory_membership_with_connection(
            connection,
            inventory_id=int(inventory["id"]),
            actor_id=actor_id,
            role=role,
        )
        connection.commit()
        return membership


def list_inventory_memberships(
    db_path: str | Path,
    *,
    inventory_slug: str,
) -> list[InventoryMembershipRow]:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory = _inventory_row_from_slug(connection, inventory_slug)
        rows = connection.execute(
            """
            SELECT
                i.slug AS inventory,
                im.actor_id,
                im.role,
                im.created_at,
                im.updated_at
            FROM inventory_memberships im
            JOIN inventories i ON i.id = im.inventory_id
            WHERE im.inventory_id = ?
            ORDER BY im.actor_id
            """,
            (inventory["id"],),
        ).fetchall()
    return [
        InventoryMembershipRow(
            inventory=row["inventory"],
            actor_id=row["actor_id"],
            role=row["role"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


def revoke_inventory_membership(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str,
) -> InventoryMembershipRemovalResult:
    normalized_actor_id = _normalize_actor_id(actor_id)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory = _inventory_row_from_slug(connection, inventory_slug)
        row = connection.execute(
            """
            SELECT role
            FROM inventory_memberships
            WHERE inventory_id = ? AND actor_id = ?
            """,
            (inventory["id"], normalized_actor_id),
        ).fetchone()
        if row is None:
            raise NotFoundError(
                f"No inventory membership found for actor '{normalized_actor_id}' in inventory '{inventory['slug']}'."
            )
        connection.execute(
            """
            DELETE FROM inventory_memberships
            WHERE inventory_id = ? AND actor_id = ?
            """,
            (inventory["id"], normalized_actor_id),
        )
        connection.commit()
        return InventoryMembershipRemovalResult(
            inventory=inventory["slug"],
            actor_id=normalized_actor_id,
            role=row["role"],
        )


def actor_inventory_role_with_connection(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    actor_id: str | None,
) -> str | None:
    if actor_id is None:
        return None
    normalized_actor_id = _normalize_actor_id(actor_id)
    inventory = _inventory_row_from_slug(connection, inventory_slug)
    row = connection.execute(
        """
        SELECT role
        FROM inventory_memberships
        WHERE inventory_id = ? AND actor_id = ?
        """,
        (inventory["id"], normalized_actor_id),
    ).fetchone()
    if row is None:
        return None
    return row["role"]


def actor_inventory_role(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str | None,
) -> str | None:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        return actor_inventory_role_with_connection(
            connection,
            inventory_slug=inventory_slug,
            actor_id=actor_id,
        )


def is_global_admin(actor_roles: Iterable[str]) -> bool:
    return "admin" in set(actor_roles)


def actor_can_read_inventory(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str | None,
    actor_roles: Iterable[str],
) -> bool:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory_role = actor_inventory_role_with_connection(
            connection,
            inventory_slug=inventory_slug,
            actor_id=actor_id,
        )
    return can_read_inventory(inventory_role=inventory_role, actor_roles=actor_roles)


def actor_can_write_inventory(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str | None,
    actor_roles: Iterable[str],
) -> bool:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory_role = actor_inventory_role_with_connection(
            connection,
            inventory_slug=inventory_slug,
            actor_id=actor_id,
        )
    return can_write_inventory(inventory_role=inventory_role, actor_roles=actor_roles)


def actor_can_read_any_inventory(
    db_path: str | Path,
    *,
    actor_id: str | None,
    actor_roles: Iterable[str],
) -> bool:
    if is_global_admin(actor_roles):
        return True
    if actor_id is None:
        return False
    normalized_actor_id = _normalize_actor_id(actor_id)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM inventory_memberships
            WHERE actor_id = ?
            LIMIT 1
            """,
            (normalized_actor_id,),
        ).fetchone()
    return row is not None


def can_read_inventory(*, inventory_role: str | None, actor_roles: Iterable[str]) -> bool:
    if is_global_admin(actor_roles):
        return True
    return inventory_role in INVENTORY_READ_ROLES


def can_write_inventory(*, inventory_role: str | None, actor_roles: Iterable[str]) -> bool:
    if is_global_admin(actor_roles):
        return True
    return inventory_role in INVENTORY_WRITE_ROLES
