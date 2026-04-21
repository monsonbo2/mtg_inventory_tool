"""Owner-managed read-only inventory share links."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets
import sqlite3
from pathlib import Path

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ConflictError, NotFoundError, ValidationError
from .audit import write_inventory_audit_event
from .normalize import extract_image_uri_fields, normalize_inventory_slug, normalized_catalog_finish_list, text_or_none
from .query_inventory import get_inventory_row
from .response_models import (
    InventoryShareLinkStatusResult,
    InventoryShareLinkTokenResult,
    PublicInventoryItem,
    PublicInventoryShareResult,
    PublicInventorySummary,
)


SHARE_TOKEN_NONCE_BYTES = 24
SHARE_TOKEN_VERSION = "v1"
PUBLIC_SHARE_PATH_PREFIX = "/shared/inventories"


def _normalize_actor_id(actor_id: str | None) -> str:
    normalized = (actor_id or "").strip()
    if not normalized:
        raise ValidationError("actor_id is required to manage inventory share links.")
    return normalized


def _normalize_token_secret(token_secret: str | None) -> bytes:
    normalized = (token_secret or "").strip()
    if not normalized:
        raise ValidationError("A share token signing secret is required to manage public inventory links.")
    return normalized.encode("utf-8")


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _base64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise NotFoundError("Shared inventory link was not found.") from exc


def _sign_share_token_payload(*, share_link_id: int, token_nonce: str, token_secret: str | None) -> str:
    secret = _normalize_token_secret(token_secret)
    payload = f"{SHARE_TOKEN_VERSION}.{share_link_id}.{token_nonce}".encode("utf-8")
    return _base64url_encode(hmac.new(secret, payload, hashlib.sha256).digest())


def generate_share_token_nonce() -> str:
    return secrets.token_urlsafe(SHARE_TOKEN_NONCE_BYTES)


def build_share_token(*, share_link_id: int, token_nonce: str, token_secret: str | None) -> str:
    signature = _sign_share_token_payload(
        share_link_id=share_link_id,
        token_nonce=token_nonce,
        token_secret=token_secret,
    )
    return f"{SHARE_TOKEN_VERSION}.{share_link_id}.{token_nonce}.{signature}"


def _parse_share_token(token: str, *, token_secret: str | None) -> tuple[int, str]:
    normalized = token.strip()
    if not normalized:
        raise NotFoundError("Shared inventory link was not found.")
    parts = normalized.split(".")
    if len(parts) != 4 or parts[0] != SHARE_TOKEN_VERSION:
        raise NotFoundError("Shared inventory link was not found.")
    _version, share_link_id_text, token_nonce, signature = parts
    if not token_nonce or not signature:
        raise NotFoundError("Shared inventory link was not found.")
    try:
        share_link_id = int(share_link_id_text)
    except ValueError as exc:
        raise NotFoundError("Shared inventory link was not found.") from exc
    if share_link_id < 1:
        raise NotFoundError("Shared inventory link was not found.")
    expected_signature = _sign_share_token_payload(
        share_link_id=share_link_id,
        token_nonce=token_nonce,
        token_secret=token_secret,
    )
    # Decode first so malformed base64 cannot compare equal as text.
    if not hmac.compare_digest(_base64url_decode(signature), _base64url_decode(expected_signature)):
        raise NotFoundError("Shared inventory link was not found.")
    return share_link_id, token_nonce


def _public_path(token: str) -> str:
    return f"{PUBLIC_SHARE_PATH_PREFIX}/{token}"


def _status_from_row(
    inventory_slug: str,
    row: sqlite3.Row | None,
    *,
    token_secret: str | None,
) -> InventoryShareLinkStatusResult:
    if row is None:
        return InventoryShareLinkStatusResult(
            inventory=inventory_slug,
            active=False,
            public_path=None,
            created_at=None,
            updated_at=None,
            revoked_at=None,
        )
    revoked_at = text_or_none(row["revoked_at"])
    token = (
        build_share_token(
            share_link_id=int(row["id"]),
            token_nonce=row["token_nonce"],
            token_secret=token_secret,
        )
        if revoked_at is None
        else None
    )
    return InventoryShareLinkStatusResult(
        inventory=inventory_slug,
        active=revoked_at is None,
        public_path=_public_path(token) if token is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revoked_at=revoked_at,
    )


def _token_result_from_row(
    *,
    inventory_slug: str,
    row: sqlite3.Row,
    token_secret: str | None,
) -> InventoryShareLinkTokenResult:
    token = build_share_token(
        share_link_id=int(row["id"]),
        token_nonce=row["token_nonce"],
        token_secret=token_secret,
    )
    return InventoryShareLinkTokenResult(
        inventory=inventory_slug,
        token=token,
        public_path=_public_path(token),
        active=row["revoked_at"] is None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        revoked_at=text_or_none(row["revoked_at"]),
    )


def _share_link_row_for_inventory(
    connection: sqlite3.Connection,
    *,
    inventory_id: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            id,
            token_nonce,
            issued_by_actor_id,
            created_at,
            updated_at,
            revoked_at,
            revoked_by_actor_id
        FROM inventory_share_links
        WHERE inventory_id = ?
        """,
        (inventory_id,),
    ).fetchone()


def _share_link_row_by_id(connection: sqlite3.Connection, share_link_id: int) -> sqlite3.Row:
    row = connection.execute(
        """
        SELECT
            id,
            token_nonce,
            issued_by_actor_id,
            created_at,
            updated_at,
            revoked_at,
            revoked_by_actor_id
        FROM inventory_share_links
        WHERE id = ?
        """,
        (share_link_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("Inventory share link was not found after write.")
    return row


def _new_unique_token_nonce(connection: sqlite3.Connection) -> str:
    for _attempt in range(16):
        token_nonce = generate_share_token_nonce()
        existing = connection.execute(
            """
            SELECT 1
            FROM inventory_share_links
            WHERE token_nonce = ?
            """,
            (token_nonce,),
        ).fetchone()
        if existing is None:
            return token_nonce
    raise ConflictError("Could not generate a unique inventory share token nonce.")


def _write_share_link_audit(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    action: str,
    share_link_id: int,
    actor_type: str,
    actor_id: str | None,
    request_id: str | None,
    metadata: dict[str, object] | None = None,
) -> None:
    write_inventory_audit_event(
        connection,
        inventory_slug=inventory_slug,
        action=action,
        metadata={
            "share_link_id": share_link_id,
            **(metadata or {}),
        },
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )


def get_inventory_share_link_status(
    db_path: str | Path,
    *,
    inventory_slug: str,
    token_secret: str | None,
) -> InventoryShareLinkStatusResult:
    normalized_slug = normalize_inventory_slug(inventory_slug)
    _normalize_token_secret(token_secret)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory = get_inventory_row(connection, normalized_slug)
        row = _share_link_row_for_inventory(connection, inventory_id=int(inventory["id"]))
    return _status_from_row(normalized_slug, row, token_secret=token_secret)


def create_inventory_share_link(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str | None,
    token_secret: str | None,
    actor_type: str = "cli",
    request_id: str | None = None,
) -> InventoryShareLinkTokenResult:
    normalized_slug = normalize_inventory_slug(inventory_slug)
    normalized_actor_id = _normalize_actor_id(actor_id)
    _normalize_token_secret(token_secret)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory = get_inventory_row(connection, normalized_slug)
        inventory_id = int(inventory["id"])
        existing = _share_link_row_for_inventory(connection, inventory_id=inventory_id)
        if existing is not None and existing["revoked_at"] is None:
            raise ConflictError(
                f"Inventory '{normalized_slug}' already has an active share link. Rotate it to issue a new token."
            )

        token_nonce = _new_unique_token_nonce(connection)
        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO inventory_share_links (
                    inventory_id,
                    token_nonce,
                    issued_by_actor_id
                )
                VALUES (?, ?, ?)
                """,
                (inventory_id, token_nonce, normalized_actor_id),
            )
            share_link_id = int(cursor.lastrowid)
            audit_action = "create_share_link"
            audit_metadata = {"recreated": False}
        else:
            share_link_id = int(existing["id"])
            connection.execute(
                """
                UPDATE inventory_share_links
                SET
                    token_nonce = ?,
                    issued_by_actor_id = ?,
                    created_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP,
                    revoked_at = NULL,
                    revoked_by_actor_id = NULL
                WHERE id = ?
                """,
                (token_nonce, normalized_actor_id, share_link_id),
            )
            audit_action = "create_share_link"
            audit_metadata = {"recreated": True}
        row = _share_link_row_by_id(connection, share_link_id)
        _write_share_link_audit(
            connection,
            inventory_slug=normalized_slug,
            action=audit_action,
            share_link_id=share_link_id,
            actor_type=actor_type,
            actor_id=normalized_actor_id,
            request_id=request_id,
            metadata=audit_metadata,
        )
        connection.commit()
    return _token_result_from_row(inventory_slug=normalized_slug, row=row, token_secret=token_secret)


def rotate_inventory_share_link(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str | None,
    token_secret: str | None,
    actor_type: str = "cli",
    request_id: str | None = None,
) -> InventoryShareLinkTokenResult:
    normalized_slug = normalize_inventory_slug(inventory_slug)
    normalized_actor_id = _normalize_actor_id(actor_id)
    _normalize_token_secret(token_secret)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory = get_inventory_row(connection, normalized_slug)
        existing = _share_link_row_for_inventory(connection, inventory_id=int(inventory["id"]))
        if existing is None or existing["revoked_at"] is not None:
            raise NotFoundError(f"Inventory '{normalized_slug}' does not have an active share link.")

        token_nonce = _new_unique_token_nonce(connection)
        connection.execute(
            """
            UPDATE inventory_share_links
            SET
                token_nonce = ?,
                issued_by_actor_id = ?,
                created_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP,
                revoked_at = NULL,
                revoked_by_actor_id = NULL
            WHERE id = ?
            """,
            (token_nonce, normalized_actor_id, int(existing["id"])),
        )
        row = _share_link_row_by_id(connection, int(existing["id"]))
        _write_share_link_audit(
            connection,
            inventory_slug=normalized_slug,
            action="rotate_share_link",
            share_link_id=int(existing["id"]),
            actor_type=actor_type,
            actor_id=normalized_actor_id,
            request_id=request_id,
        )
        connection.commit()
    return _token_result_from_row(inventory_slug=normalized_slug, row=row, token_secret=token_secret)


def revoke_inventory_share_link(
    db_path: str | Path,
    *,
    inventory_slug: str,
    actor_id: str | None,
    actor_type: str = "cli",
    request_id: str | None = None,
) -> InventoryShareLinkStatusResult:
    normalized_slug = normalize_inventory_slug(inventory_slug)
    normalized_actor_id = _normalize_actor_id(actor_id)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        inventory = get_inventory_row(connection, normalized_slug)
        existing = _share_link_row_for_inventory(connection, inventory_id=int(inventory["id"]))
        if existing is None:
            return _status_from_row(normalized_slug, None, token_secret=None)
        if existing["revoked_at"] is not None:
            return _status_from_row(normalized_slug, existing, token_secret=None)
        connection.execute(
            """
            UPDATE inventory_share_links
            SET
                updated_at = CURRENT_TIMESTAMP,
                revoked_at = CURRENT_TIMESTAMP,
                revoked_by_actor_id = ?
            WHERE id = ?
            """,
            (normalized_actor_id, int(existing["id"])),
        )
        row = _share_link_row_by_id(connection, int(existing["id"]))
        _write_share_link_audit(
            connection,
            inventory_slug=normalized_slug,
            action="revoke_share_link",
            share_link_id=int(existing["id"]),
            actor_type=actor_type,
            actor_id=normalized_actor_id,
            request_id=request_id,
        )
        connection.commit()
    return _status_from_row(normalized_slug, row, token_secret=None)


def _public_item_from_row(row: sqlite3.Row) -> PublicInventoryItem:
    image_uri_small, image_uri_normal = extract_image_uri_fields(row["image_uris_json"])
    return PublicInventoryItem(
        scryfall_id=row["scryfall_id"],
        oracle_id=row["oracle_id"],
        name=row["name"],
        set_code=row["set_code"],
        set_name=row["set_name"],
        rarity=text_or_none(row["rarity"]),
        collector_number=row["collector_number"],
        image_uri_small=image_uri_small,
        image_uri_normal=image_uri_normal,
        quantity=int(row["quantity"]),
        condition_code=row["condition_code"],
        finish=row["finish"],
        allowed_finishes=normalized_catalog_finish_list(row["finishes_json"]),
        language_code=row["language_code"],
    )


def _public_summary_from_row(row: sqlite3.Row) -> PublicInventorySummary:
    return PublicInventorySummary(
        display_name=row["display_name"],
        description=text_or_none(row["description"]),
        item_rows=int(row["item_rows"]),
        total_cards=int(row["total_cards"]),
    )


def get_public_inventory_share(
    db_path: str | Path,
    *,
    token: str,
    token_secret: str | None,
) -> PublicInventoryShareResult:
    share_link_id, token_nonce = _parse_share_token(token, token_secret=token_secret)
    db_file = require_current_schema(db_path)
    with connect(db_file) as connection:
        share = connection.execute(
            """
            SELECT
                isl.inventory_id,
                i.display_name,
                i.description
            FROM inventory_share_links isl
            JOIN inventories i ON i.id = isl.inventory_id
            WHERE isl.id = ?
              AND isl.token_nonce = ?
              AND isl.revoked_at IS NULL
            """,
            (share_link_id, token_nonce),
        ).fetchone()
        if share is None:
            raise NotFoundError("Shared inventory link was not found.")

        inventory_id = int(share["inventory_id"])
        summary_row = connection.execute(
            """
            SELECT
                i.display_name,
                COALESCE(i.description, '') AS description,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards
            FROM inventories i
            LEFT JOIN inventory_items ii ON ii.inventory_id = i.id
            WHERE i.id = ?
            GROUP BY i.id, i.display_name, i.description
            """,
            (inventory_id,),
        ).fetchone()
        if summary_row is None:
            raise NotFoundError("Shared inventory link was not found.")

        item_rows = connection.execute(
            """
            SELECT
                ii.scryfall_id,
                c.oracle_id,
                c.name,
                c.set_code,
                c.set_name,
                c.rarity,
                c.collector_number,
                c.image_uris_json,
                c.finishes_json,
                ii.quantity,
                ii.condition_code,
                ii.finish,
                ii.language_code
            FROM inventory_items ii
            JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
            WHERE ii.inventory_id = ?
            ORDER BY c.name, c.set_code, c.collector_number, ii.condition_code, ii.finish
            """,
            (inventory_id,),
        ).fetchall()

    return PublicInventoryShareResult(
        inventory=_public_summary_from_row(summary_row),
        items=[_public_item_from_row(row) for row in item_rows],
    )
