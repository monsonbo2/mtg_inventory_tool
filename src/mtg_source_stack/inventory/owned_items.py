"""Owned inventory row reads and paging helpers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ValidationError
from .money import coerce_decimal
from .normalize import (
    DEFAULT_OWNED_ROWS_PAGE_LIMIT,
    extract_image_uri_fields,
    MAX_OWNED_ROWS_LIMIT,
    load_tags_json,
    normalize_inventory_slug,
    normalized_catalog_finish_list,
    text_or_none,
    validate_limit_value,
)
from .query_inventory import add_owned_filters, get_inventory_row
from .query_pricing import build_latest_retail_prices_cte
from .response_models import OwnedInventoryPageResult, OwnedInventoryRow


OWNED_INVENTORY_PAGE_SORT_KEYS = (
    "name",
    "set",
    "quantity",
    "finish",
    "condition_code",
    "language_code",
    "location",
    "tags",
    "est_value",
    "item_id",
)
OWNED_INVENTORY_PAGE_SORT_DIRECTIONS = ("asc", "desc")
_OWNED_INVENTORY_PAGE_SORT_EXPRESSIONS = {
    "name": ("LOWER(c.name)",),
    "set": ("LOWER(c.set_name)", "LOWER(c.set_code)"),
    "quantity": ("ii.quantity",),
    "finish": (
        """
        CASE ii.finish
            WHEN 'normal' THEN 0
            WHEN 'foil' THEN 1
            WHEN 'etched' THEN 2
            ELSE 99
        END
        """,
        "LOWER(ii.finish)",
    ),
    "condition_code": (
        """
        CASE ii.condition_code
            WHEN 'M' THEN 0
            WHEN 'NM' THEN 1
            WHEN 'LP' THEN 2
            WHEN 'MP' THEN 3
            WHEN 'HP' THEN 4
            WHEN 'DMG' THEN 5
            ELSE 99
        END
        """,
        "LOWER(ii.condition_code)",
    ),
    "language_code": ("LOWER(ii.language_code)",),
    "location": ("LOWER(COALESCE(ii.location, ''))",),
    "tags": ("COALESCE(ii.tags_json, '[]')",),
    "est_value": ("COALESCE(ii.quantity * lp.price_value, 0)",),
    "item_id": ("ii.id",),
}


def normalize_owned_inventory_page_sort_key(sort_key: str | None) -> str:
    normalized = (text_or_none(sort_key) or "name").lower()
    if normalized not in OWNED_INVENTORY_PAGE_SORT_KEYS:
        accepted = ", ".join(OWNED_INVENTORY_PAGE_SORT_KEYS)
        raise ValidationError(f"sort_key must be one of: {accepted}.")
    return normalized


def normalize_sort_direction(sort_direction: str | None) -> str:
    normalized = (text_or_none(sort_direction) or "asc").lower()
    if normalized not in OWNED_INVENTORY_PAGE_SORT_DIRECTIONS:
        accepted = ", ".join(OWNED_INVENTORY_PAGE_SORT_DIRECTIONS)
        raise ValidationError(f"sort_direction must be one of: {accepted}.")
    return normalized


def validate_offset_value(offset: int, *, field_name: str = "--offset") -> int:
    if offset < 0:
        raise ValidationError(f"{field_name} must be zero or a positive integer.")
    return offset


def _owned_inventory_page_order_by_clause(*, sort_key: str, sort_direction: str) -> str:
    direction_sql = sort_direction.upper()
    sort_parts = [
        f"{expression.strip()} {direction_sql}"
        for expression in _OWNED_INVENTORY_PAGE_SORT_EXPRESSIONS[sort_key]
    ]
    if sort_key != "item_id":
        sort_parts.append("ii.id ASC")
    return ", ".join(sort_parts)


def build_owned_inventory_row(row: dict[str, Any]) -> OwnedInventoryRow:
    unit_price = coerce_decimal(row.get("unit_price"))
    quantity = int(row["quantity"])
    image_uri_small, image_uri_normal = extract_image_uri_fields(row.get("image_uris_json"))
    return OwnedInventoryRow(
        item_id=int(row["item_id"]),
        scryfall_id=row["scryfall_id"],
        oracle_id=row["oracle_id"],
        name=row["name"],
        set_code=row["set_code"],
        set_name=row["set_name"],
        rarity=text_or_none(row.get("rarity")),
        collector_number=row["collector_number"],
        image_uri_small=image_uri_small,
        image_uri_normal=image_uri_normal,
        quantity=quantity,
        condition_code=row["condition_code"],
        finish=row["finish"],
        allowed_finishes=normalized_catalog_finish_list(row.get("finishes_json")),
        language_code=row["language_code"],
        location=text_or_none(row.get("location")),
        tags=load_tags_json(row.get("tags_json")),
        acquisition_price=coerce_decimal(row.get("acquisition_price")),
        acquisition_currency=text_or_none(row.get("acquisition_currency")),
        currency=text_or_none(row.get("currency")),
        unit_price=unit_price,
        est_value=(unit_price * Decimal(quantity) if unit_price is not None else None),
        price_date=text_or_none(row.get("price_date")),
        notes=text_or_none(row.get("notes")),
        printing_selection_mode=row["printing_selection_mode"],
    )


def list_owned(db_path: str | Path, inventory_slug: str, provider: str, limit: int | None) -> list[OwnedInventoryRow]:
    return list_owned_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        limit=limit,
        query=None,
        set_code=None,
        rarity=None,
        finish=None,
        condition_code=None,
        language_code=None,
        location=None,
        tags=None,
    )


def list_owned_filtered(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
) -> list[OwnedInventoryRow]:
    validate_limit_value(limit, maximum=MAX_OWNED_ROWS_LIMIT, allow_none=True)
    inventory_slug = normalize_inventory_slug(inventory_slug)
    require_current_schema(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)
        latest_prices_cte, latest_price_params = build_latest_retail_prices_cte(provider=provider)
        where_params: list[Any] = [inventory_slug]
        where_parts = ["i.slug = ?"]
        add_owned_filters(
            where_parts,
            where_params,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        )
        limit_sql = ""
        params: list[Any] = [*latest_price_params, *where_params]
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        rows = connection.execute(
            f"""
            WITH {latest_prices_cte}
            SELECT
                ii.id AS item_id,
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
                ii.language_code,
                ii.location,
                COALESCE(ii.tags_json, '[]') AS tags_json,
                ii.acquisition_price,
                ii.acquisition_currency,
                lp.currency,
                lp.price_value AS unit_price,
                ROUND(ii.quantity * lp.price_value, 2) AS est_value,
                lp.snapshot_date AS price_date,
                ii.notes,
                ii.printing_selection_mode
            FROM inventory_items ii
            JOIN inventories i ON i.id = ii.inventory_id
            JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
            LEFT JOIN latest_prices lp
                ON lp.scryfall_id = ii.scryfall_id
               AND lp.finish = ii.finish
               AND lp.rn = 1
            WHERE {' AND '.join(where_parts)}
            ORDER BY c.name, c.set_code, c.collector_number, ii.condition_code, ii.finish
            {limit_sql}
            """,
            params,
        ).fetchall()
    return [build_owned_inventory_row(dict(row)) for row in rows]


def list_owned_filtered_page(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    limit: int = DEFAULT_OWNED_ROWS_PAGE_LIMIT,
    offset: int = 0,
    sort_key: str | None = None,
    sort_direction: str | None = None,
    query: str | None = None,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: str | None = None,
    condition_code: str | None = None,
    language_code: str | None = None,
    location: str | None = None,
    tags: list[str] | None = None,
) -> OwnedInventoryPageResult:
    normalized_limit = validate_limit_value(limit, maximum=MAX_OWNED_ROWS_LIMIT)
    normalized_offset = validate_offset_value(offset)
    normalized_sort_key = normalize_owned_inventory_page_sort_key(sort_key)
    normalized_sort_direction = normalize_sort_direction(sort_direction)
    inventory_slug = normalize_inventory_slug(inventory_slug)
    require_current_schema(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)
        where_params: list[Any] = [inventory_slug]
        where_parts = ["i.slug = ?"]
        add_owned_filters(
            where_parts,
            where_params,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        )
        where_sql = " AND ".join(where_parts)
        total_count = int(
            connection.execute(
                f"""
                SELECT COUNT(*) AS total_count
                FROM inventory_items ii
                JOIN inventories i ON i.id = ii.inventory_id
                JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
                WHERE {where_sql}
                """,
                where_params,
            ).fetchone()["total_count"]
        )

        latest_prices_cte, latest_price_params = build_latest_retail_prices_cte(provider=provider)
        order_by_sql = _owned_inventory_page_order_by_clause(
            sort_key=normalized_sort_key,
            sort_direction=normalized_sort_direction,
        )
        rows = connection.execute(
            f"""
            WITH {latest_prices_cte}
            SELECT
                ii.id AS item_id,
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
                ii.language_code,
                ii.location,
                COALESCE(ii.tags_json, '[]') AS tags_json,
                ii.acquisition_price,
                ii.acquisition_currency,
                lp.currency,
                lp.price_value AS unit_price,
                ROUND(ii.quantity * lp.price_value, 2) AS est_value,
                lp.snapshot_date AS price_date,
                ii.notes,
                ii.printing_selection_mode
            FROM inventory_items ii
            JOIN inventories i ON i.id = ii.inventory_id
            JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
            LEFT JOIN latest_prices lp
                ON lp.scryfall_id = ii.scryfall_id
               AND lp.finish = ii.finish
               AND lp.rn = 1
            WHERE {where_sql}
            ORDER BY {order_by_sql}
            LIMIT ? OFFSET ?
            """,
            [*latest_price_params, *where_params, normalized_limit, normalized_offset],
        ).fetchall()

    items = [build_owned_inventory_row(dict(row)) for row in rows]
    return OwnedInventoryPageResult(
        inventory=inventory_slug,
        items=items,
        total_count=total_count,
        limit=normalized_limit,
        offset=normalized_offset,
        has_more=normalized_offset + len(items) < total_count,
        sort_key=normalized_sort_key,
        sort_direction=normalized_sort_direction,
    )
