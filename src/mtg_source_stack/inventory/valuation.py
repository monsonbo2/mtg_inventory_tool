"""Inventory valuation and price-gap helpers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ValidationError
from .money import coerce_decimal
from .normalize import normalize_inventory_slug, text_or_none
from .query_inventory import add_owned_filters, get_inventory_row
from .query_pricing import build_latest_retail_prices_cte, query_price_gaps
from .response_models import PriceGapRow, ReconcilePricesResult, ValuationRow


def build_price_gap_row(row: dict[str, Any]) -> PriceGapRow:
    return PriceGapRow(
        inventory=row["inventory"],
        card_name=row["card_name"],
        set_code=row["set_code"],
        set_name=row["set_name"],
        collector_number=row["collector_number"],
        scryfall_id=row["scryfall_id"],
        item_id=int(row["item_id"]),
        quantity=int(row["quantity"]),
        finish=row["finish"],
        condition_code=row["condition_code"],
        language_code=row["language_code"],
        location=text_or_none(row["location"]),
        acquisition_price=coerce_decimal(row.get("acquisition_price")),
        acquisition_currency=text_or_none(row.get("acquisition_currency")),
        notes=text_or_none(row.get("notes")),
        tags=list(row.get("tags", [])),
        available_finishes=list(row.get("available_finishes", [])),
        suggested_finish=text_or_none(row.get("suggested_finish")),
        reconcile_status=row["reconcile_status"],
    )


def build_valuation_row(row: dict[str, Any]) -> ValuationRow:
    return ValuationRow(
        provider=text_or_none(row.get("provider")),
        currency=text_or_none(row.get("currency")),
        item_rows=int(row["item_rows"]),
        total_cards=int(row["total_cards"]),
        total_value=coerce_decimal(row.get("total_value")) or Decimal("0"),
    )


def list_price_gaps(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None,
) -> list[PriceGapRow]:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    require_current_schema(db_path)
    with connect(db_path) as connection:
        rows = query_price_gaps(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=limit,
        )
    return [build_price_gap_row(row) for row in rows]


def reconcile_prices(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    apply_changes: bool,
) -> ReconcilePricesResult:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    if apply_changes:
        raise ValidationError(
            "reconcile-prices is suggestion-only and no longer changes inventory finish values. "
            "Review the suggestions, then use set-finish manually if you want to update a row."
        )

    require_current_schema(db_path)
    with connect(db_path) as connection:
        rows = [
            build_price_gap_row(row)
            for row in query_price_gaps(
                connection,
                inventory_slug=inventory_slug,
                provider=provider,
                limit=None,
            )
        ]

        suggested_rows: list[PriceGapRow] = []
        remaining_rows: list[PriceGapRow] = []
        rows_fixable = 0

        for row in rows:
            if row.suggested_finish is None:
                remaining_rows.append(row)
                continue

            rows_fixable += 1
            suggested_rows.append(row)

    return ReconcilePricesResult(
        inventory=inventory_slug,
        provider=provider,
        rows_seen=len(rows),
        rows_fixable=rows_fixable,
        suggested_rows=suggested_rows,
        remaining_rows=remaining_rows,
    )


def valuation(db_path: str | Path, inventory_slug: str, provider: str | None) -> list[ValuationRow]:
    return valuation_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        query=None,
        set_code=None,
        rarity=None,
        finish=None,
        condition_code=None,
        language_code=None,
        location=None,
        tags=None,
    )


def valuation_filtered(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str | None,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
) -> list[ValuationRow]:
    inventory_slug = normalize_inventory_slug(inventory_slug)
    require_current_schema(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)

        if provider:
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
            params: list[Any] = [*latest_price_params, provider, *where_params]
            rows = connection.execute(
                f"""
                WITH {latest_prices_cte}
                SELECT
                    ? AS provider,
                    lp.currency,
                    COUNT(ii.id) AS item_rows,
                    COALESCE(SUM(ii.quantity), 0) AS total_cards,
                    ROUND(COALESCE(SUM(ii.quantity * lp.price_value), 0), 2) AS total_value
                FROM inventory_items ii
                JOIN inventories i ON i.id = ii.inventory_id
                JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
                LEFT JOIN latest_prices lp
                    ON lp.scryfall_id = ii.scryfall_id
                   AND lp.finish = ii.finish
                   AND lp.rn = 1
                WHERE {' AND '.join(where_parts)}
                GROUP BY lp.currency
                ORDER BY lp.currency
                """,
                params,
            ).fetchall()
            return [build_valuation_row(dict(row)) for row in rows]

        latest_prices_cte, latest_price_params = build_latest_retail_prices_cte(provider=None)
        where_params = [inventory_slug]
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
        params = [*latest_price_params, *where_params]
        rows = connection.execute(
            f"""
            WITH {latest_prices_cte}
            SELECT
                lp.provider,
                lp.currency,
                COUNT(ii.id) AS item_rows,
                COALESCE(SUM(ii.quantity), 0) AS total_cards,
                ROUND(COALESCE(SUM(ii.quantity * lp.price_value), 0), 2) AS total_value
            FROM inventory_items ii
            JOIN inventories i ON i.id = ii.inventory_id
            JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
            LEFT JOIN latest_prices lp
                ON lp.scryfall_id = ii.scryfall_id
               AND lp.finish = ii.finish
               AND lp.rn = 1
            WHERE {' AND '.join(where_parts)}
            GROUP BY lp.provider, lp.currency
            ORDER BY lp.provider, lp.currency
            """,
            params,
        ).fetchall()
        return [build_valuation_row(dict(row)) for row in rows]
