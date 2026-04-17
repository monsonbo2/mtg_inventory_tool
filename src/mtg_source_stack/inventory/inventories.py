"""Inventory container creation and listing helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import AuthorizationError, ConflictError, ValidationError
from .access import grant_inventory_membership_with_connection, is_global_admin
from .money import coerce_decimal
from .normalize import normalize_currency_code, normalize_inventory_slug, normalize_tag_text, slugify_inventory_name, text_or_none
from .response_models import AccessSummaryResult, DefaultInventoryBootstrapResult, InventoryCreateResult, InventoryListRow


def _inventory_list_rows(rows: list[sqlite3.Row]) -> list[InventoryListRow]:
    return [
        InventoryListRow(
            slug=row["slug"],
            display_name=row["display_name"],
            description=text_or_none(row["description"]),
            default_location=text_or_none(row["default_location"]),
            default_tags=text_or_none(row["default_tags"]),
            notes=text_or_none(row["notes"]),
            acquisition_price=coerce_decimal(row["acquisition_price"]),
            acquisition_currency=text_or_none(row["acquisition_currency"]),
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
        default_location=text_or_none(row["default_location"]),
        default_tags=text_or_none(row["default_tags"]),
        notes=text_or_none(row["notes"]),
        acquisition_price=coerce_decimal(row["acquisition_price"]),
        acquisition_currency=text_or_none(row["acquisition_currency"]),
    )


def _normalize_inventory_metadata(
    *,
    default_location: str | None,
    default_tags: str | None,
    notes: str | None,
    acquisition_price: object | None,
    acquisition_currency: str | None,
) -> tuple[str | None, str | None, str | None, object | None, str | None]:
    normalized_default_location = text_or_none(default_location)
    normalized_default_tags = normalize_tag_text(default_tags)
    normalized_notes = text_or_none(notes)
    normalized_acquisition_price = coerce_decimal(acquisition_price)
    normalized_acquisition_currency = normalize_currency_code(acquisition_currency)

    if normalized_acquisition_price is None and normalized_acquisition_currency is not None:
        raise ValidationError(
            "Cannot store an acquisition currency without an acquisition price. "
            "Use acquisition_price too, or omit acquisition_currency."
        )
    if normalized_acquisition_price is not None and normalized_acquisition_price < 0:
        raise ValidationError("acquisition_price must be zero or greater.")

    return (
        normalized_default_location,
        normalized_default_tags,
        normalized_notes,
        normalized_acquisition_price,
        normalized_acquisition_currency,
    )


def _require_global_editor_or_admin(actor_roles: Iterable[str]) -> None:
    roles = set(actor_roles)
    if "editor" not in roles and "admin" not in roles:
        raise AuthorizationError("Role 'editor' is required to bootstrap a default inventory.")


def _can_bootstrap_default_inventory(actor_roles: Iterable[str]) -> bool:
    roles = set(actor_roles)
    return "editor" in roles or "admin" in roles


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
            COALESCE(i.description, '') AS description,
            COALESCE(i.default_location, '') AS default_location,
            COALESCE(i.default_tags, '') AS default_tags,
            COALESCE(i.notes, '') AS notes,
            i.acquisition_price,
            COALESCE(i.acquisition_currency, '') AS acquisition_currency
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
    default_location: str | None = None,
    default_tags: str | None = None,
    notes: str | None = None,
    acquisition_price: object | None = None,
    acquisition_currency: str | None = None,
    actor_id: str | None = None,
) -> InventoryCreateResult:
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        created = create_inventory_with_connection(
            connection,
            slug=slug,
            display_name=display_name,
            description=description,
            default_location=default_location,
            default_tags=default_tags,
            notes=notes,
            acquisition_price=acquisition_price,
            acquisition_currency=acquisition_currency,
            actor_id=actor_id,
        )
        connection.commit()
        return created


def create_inventory_with_connection(
    connection: sqlite3.Connection,
    *,
    slug: str,
    display_name: str,
    description: str | None,
    default_location: str | None = None,
    default_tags: str | None = None,
    notes: str | None = None,
    acquisition_price: object | None = None,
    acquisition_currency: str | None = None,
    actor_id: str | None = None,
) -> InventoryCreateResult:
    slug = normalize_inventory_slug(slug)
    (
        normalized_default_location,
        normalized_default_tags,
        normalized_notes,
        normalized_acquisition_price,
        normalized_acquisition_currency,
    ) = _normalize_inventory_metadata(
        default_location=default_location,
        default_tags=default_tags,
        notes=notes,
        acquisition_price=acquisition_price,
        acquisition_currency=acquisition_currency,
    )
    try:
        cursor = connection.execute(
            """
            INSERT INTO inventories (
                slug,
                display_name,
                description,
                default_location,
                default_tags,
                notes,
                acquisition_price,
                acquisition_currency
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                slug,
                display_name,
                description,
                normalized_default_location,
                normalized_default_tags,
                normalized_notes,
                normalized_acquisition_price,
                normalized_acquisition_currency,
            ),
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
    return InventoryCreateResult(
        inventory_id=int(cursor.lastrowid),
        slug=slug,
        display_name=display_name,
        description=text_or_none(description),
        default_location=normalized_default_location,
        default_tags=normalized_default_tags,
        notes=normalized_notes,
        acquisition_price=coerce_decimal(normalized_acquisition_price),
        acquisition_currency=normalized_acquisition_currency,
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
                    INSERT INTO inventories (
                        slug,
                        display_name,
                        description,
                        default_location,
                        default_tags,
                        notes,
                        acquisition_price,
                        acquisition_currency
                    )
                    VALUES (?, ?, NULL, NULL, NULL, NULL, NULL, NULL)
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
                    default_location=None,
                    default_tags=None,
                    notes=None,
                    acquisition_price=None,
                    acquisition_currency=None,
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
                COALESCE(i.default_location, '') AS default_location,
                COALESCE(i.default_tags, '') AS default_tags,
                COALESCE(i.notes, '') AS notes,
                i.acquisition_price,
                COALESCE(i.acquisition_currency, '') AS acquisition_currency,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards
            FROM inventories i
            LEFT JOIN inventory_items ii ON ii.inventory_id = i.id
            GROUP BY
                i.id,
                i.slug,
                i.display_name,
                i.description,
                i.default_location,
                i.default_tags,
                i.notes,
                i.acquisition_price,
                i.acquisition_currency
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
                COALESCE(i.default_location, '') AS default_location,
                COALESCE(i.default_tags, '') AS default_tags,
                COALESCE(i.notes, '') AS notes,
                i.acquisition_price,
                COALESCE(i.acquisition_currency, '') AS acquisition_currency,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards
            FROM inventories i
            JOIN inventory_memberships im
                ON im.inventory_id = i.id
            LEFT JOIN inventory_items ii ON ii.inventory_id = i.id
            WHERE im.actor_id = ?
            GROUP BY
                i.id,
                i.slug,
                i.display_name,
                i.description,
                i.default_location,
                i.default_tags,
                i.notes,
                i.acquisition_price,
                i.acquisition_currency
            ORDER BY i.slug
            """,
            (normalized_actor_id,),
        ).fetchall()
    return _inventory_list_rows(rows)


def summarize_actor_access(
    db_path: str | Path,
    *,
    actor_id: str,
    actor_roles: Iterable[str],
) -> AccessSummaryResult:
    normalized_actor_id = _normalized_visible_actor_id(actor_id)
    if normalized_actor_id is None:
        raise ValidationError("actor_id is required.")
    visible_inventories = list_visible_inventories(
        db_path,
        actor_id=normalized_actor_id,
        actor_roles=actor_roles,
    )
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        default_inventory = _default_inventory_row_for_actor(
            connection,
            actor_id=normalized_actor_id,
        )
    return AccessSummaryResult(
        can_bootstrap=_can_bootstrap_default_inventory(actor_roles),
        has_readable_inventory=bool(visible_inventories),
        visible_inventory_count=len(visible_inventories),
        default_inventory_slug=(default_inventory.slug if default_inventory is not None else None),
    )
