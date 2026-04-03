"""Inventory container creation and listing helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import AuthorizationError, ConflictError, ValidationError
from .access import grant_inventory_membership_with_connection, is_global_admin
from .normalize import slugify_inventory_name, text_or_none
from .response_models import DefaultInventoryBootstrapResult, InventoryCreateResult, InventoryListRow


def _inventory_list_rows(rows: list[sqlite3.Row]) -> list[InventoryListRow]:
    return [
        InventoryListRow(
            slug=row["slug"],
            display_name=row["display_name"],
            description=text_or_none(row["description"]),
            item_rows=int(row["item_rows"]),
            total_cards=int(row["total_cards"]),
        )
        for row in rows
    ]


def _normalized_visible_actor_id(actor_id: str | None) -> str | None:
    if actor_id is None:
        return None
    normalized = actor_id.strip()
    if not normalized:
        raise ValidationError("actor_id is required.")
    return normalized


def _inventory_create_result_from_row(row: sqlite3.Row) -> InventoryCreateResult:
    return InventoryCreateResult(
        inventory_id=int(row["inventory_id"]),
        slug=row["slug"],
        display_name=row["display_name"],
        description=text_or_none(row["description"]),
    )


def _require_global_editor_or_admin(actor_roles: Iterable[str]) -> None:
    roles = set(actor_roles)
    if "editor" not in roles and "admin" not in roles:
        raise AuthorizationError("Role 'editor' is required to bootstrap a default inventory.")


def _default_inventory_slug_root(actor_id: str) -> str:
    local_part, _, _domain = actor_id.partition("@")
    slug_seed = slugify_inventory_name(local_part or actor_id)
    if slug_seed in {"collection", "inventory"}:
        slug_seed = "user"
    if slug_seed.endswith("-collection"):
        return slug_seed
    return f"{slug_seed}-collection"


def _default_inventory_slug_candidate(actor_id: str, attempt: int) -> str:
    root = _default_inventory_slug_root(actor_id)
    if attempt == 0:
        return root
    return f"{root}-{attempt + 1}"


def _default_inventory_row_for_actor(
    connection: sqlite3.Connection,
    *,
    actor_id: str,
) -> InventoryCreateResult | None:
    row = connection.execute(
        """
        SELECT
            i.id AS inventory_id,
            i.slug,
            i.display_name,
            COALESCE(i.description, '') AS description
        FROM actor_default_inventories adi
        JOIN inventories i ON i.id = adi.inventory_id
        WHERE adi.actor_id = ?
        """,
        (actor_id,),
    ).fetchone()
    if row is None:
        return None
    return _inventory_create_result_from_row(row)


def create_inventory(
    db_path: str | Path,
    slug: str,
    display_name: str,
    description: str | None,
    actor_id: str | None = None,
) -> InventoryCreateResult:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        try:
            cursor = connection.execute(
                """
                INSERT INTO inventories (slug, display_name, description)
                VALUES (?, ?, ?)
                """,
                (slug, display_name, description),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError(f"Inventory '{slug}' already exists.") from exc
        if actor_id is not None:
            grant_inventory_membership_with_connection(
                connection,
                inventory_id=int(cursor.lastrowid),
                actor_id=actor_id,
                role="owner",
            )
        connection.commit()
        return InventoryCreateResult(
            inventory_id=int(cursor.lastrowid),
            slug=slug,
            display_name=display_name,
            description=text_or_none(description),
        )


def ensure_default_inventory(
    db_path: str | Path,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
    display_name: str = "Collection",
) -> DefaultInventoryBootstrapResult:
    normalized_actor_id = _normalized_visible_actor_id(actor_id)
    if normalized_actor_id is None:
        raise ValidationError("actor_id is required.")
    _require_global_editor_or_admin(actor_roles)

    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        existing = _default_inventory_row_for_actor(
            connection,
            actor_id=normalized_actor_id,
        )
        if existing is not None:
            return DefaultInventoryBootstrapResult(created=False, inventory=existing)

        for attempt in range(1000):
            candidate_slug = _default_inventory_slug_candidate(normalized_actor_id, attempt)
            try:
                cursor = connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name, description)
                    VALUES (?, ?, NULL)
                    """,
                    (candidate_slug, display_name),
                )
            except sqlite3.IntegrityError:
                continue

            try:
                inventory_id = int(cursor.lastrowid)
                grant_inventory_membership_with_connection(
                    connection,
                    inventory_id=inventory_id,
                    actor_id=normalized_actor_id,
                    role="owner",
                )
                connection.execute(
                    """
                    INSERT INTO actor_default_inventories (actor_id, inventory_id)
                    VALUES (?, ?)
                    """,
                    (normalized_actor_id, inventory_id),
                )
            except sqlite3.IntegrityError:
                connection.rollback()
                existing = _default_inventory_row_for_actor(
                    connection,
                    actor_id=normalized_actor_id,
                )
                if existing is not None:
                    return DefaultInventoryBootstrapResult(created=False, inventory=existing)
                raise

            connection.commit()
            return DefaultInventoryBootstrapResult(
                created=True,
                inventory=InventoryCreateResult(
                    inventory_id=inventory_id,
                    slug=candidate_slug,
                    display_name=display_name,
                    description=None,
                ),
            )

    raise ConflictError(f"Could not generate a unique default inventory slug for actor '{normalized_actor_id}'.")


def list_inventories(db_path: str | Path) -> list[InventoryListRow]:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        rows = connection.execute(
            """
            SELECT
                i.slug,
                i.display_name,
                COALESCE(i.description, '') AS description,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards
            FROM inventories i
            LEFT JOIN inventory_items ii ON ii.inventory_id = i.id
            GROUP BY i.id, i.slug, i.display_name, i.description
            ORDER BY i.slug
            """
        ).fetchall()
    return _inventory_list_rows(rows)


def list_visible_inventories(
    db_path: str | Path,
    *,
    actor_id: str | None,
    actor_roles: Iterable[str],
) -> list[InventoryListRow]:
    if is_global_admin(actor_roles):
        return list_inventories(db_path)
    normalized_actor_id = _normalized_visible_actor_id(actor_id)
    if normalized_actor_id is None:
        return []
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        rows = connection.execute(
            """
            SELECT
                i.slug,
                i.display_name,
                COALESCE(i.description, '') AS description,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards
            FROM inventories i
            JOIN inventory_memberships im
                ON im.inventory_id = i.id
            LEFT JOIN inventory_items ii ON ii.inventory_id = i.id
            WHERE im.actor_id = ?
            GROUP BY i.id, i.slug, i.display_name, i.description
            ORDER BY i.slug
            """,
            (normalized_actor_id,),
        ).fetchall()
    return _inventory_list_rows(rows)
