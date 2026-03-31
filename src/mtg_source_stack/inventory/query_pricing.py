"""Pricing snapshot query helpers."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..pricing import DEFAULT_PRICE_CURRENCY
from .normalize import parse_finish_list, truncate
from .query_inventory import get_inventory_row, inventory_item_result_from_row


def normalized_finish_sql(column: str) -> str:
    return f"""
        CASE
            WHEN LOWER(TRIM({column})) IN ('normal', 'nonfoil') THEN 'normal'
            WHEN LOWER(TRIM({column})) = 'foil' THEN 'foil'
            WHEN LOWER(TRIM({column})) IN ('etched', 'etched foil') THEN 'etched'
            ELSE LOWER(TRIM({column}))
        END
    """.strip()


def build_latest_retail_prices_cte(*, provider: str | None, cte_name: str = "latest_prices") -> tuple[str, list[Any]]:
    where_parts = [
        "price_kind = 'retail'",
        "currency = ?",
    ]
    params: list[Any] = [DEFAULT_PRICE_CURRENCY]
    if provider is not None:
        where_parts.append("provider = ?")
        params.append(provider)
    finish_expr = normalized_finish_sql("finish")

    return (
        f"""
        {cte_name} AS (
            SELECT
                scryfall_id,
                provider,
                {finish_expr} AS finish,
                currency,
                price_value,
                snapshot_date,
                ROW_NUMBER() OVER (
                    PARTITION BY scryfall_id, provider, {finish_expr}
                    ORDER BY snapshot_date DESC, id DESC
                ) AS rn
            FROM price_snapshots
            WHERE {' AND '.join(where_parts)}
        )
        """,
        params,
    )


def build_current_retail_prices_cte(*, provider: str, cte_name: str = "current_prices") -> tuple[str, list[Any]]:
    finish_expr = normalized_finish_sql("finish")
    return (
        f"""
        {cte_name} AS (
            WITH provider_prices AS (
                SELECT
                    scryfall_id,
                    provider,
                    {finish_expr} AS finish,
                    currency,
                    snapshot_date,
                    price_value,
                    MAX(snapshot_date) OVER (
                        PARTITION BY scryfall_id, provider
                    ) AS current_snapshot_date
                FROM price_snapshots
                WHERE price_kind = 'retail'
                  AND currency = ?
                  AND provider = ?
            )
            SELECT
                scryfall_id,
                provider,
                finish,
                currency,
                snapshot_date,
                price_value
            FROM provider_prices
            WHERE snapshot_date = current_snapshot_date
        )
        """,
        [DEFAULT_PRICE_CURRENCY, provider],
    )


def build_price_gap_result(row: sqlite3.Row) -> dict[str, Any]:
    result = inventory_item_result_from_row(row)
    available_finishes = parse_finish_list(row["available_finishes"])
    result["available_finishes"] = available_finishes
    if not available_finishes:
        result["suggested_finish"] = None
        result["reconcile_status"] = "no priced finishes"
    elif len(available_finishes) == 1:
        result["suggested_finish"] = available_finishes[0]
        result["reconcile_status"] = "single priced finish"
    else:
        result["suggested_finish"] = None
        result["reconcile_status"] = "multiple priced finishes"
    return result


def query_price_gaps(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    get_inventory_row(connection, inventory_slug)
    current_prices_cte, current_price_params = build_current_retail_prices_cte(provider=provider)
    sql = """
    WITH
    """
    sql += current_prices_cte
    sql += """
    SELECT
        ii.id AS item_id,
        ii.inventory_id,
        i.slug AS inventory,
        ii.scryfall_id,
        c.name AS card_name,
        c.set_code,
        c.set_name,
        c.collector_number,
        ii.quantity,
        ii.condition_code,
        ii.finish,
        ii.language_code,
        ii.location,
        ii.acquisition_price,
        ii.acquisition_currency,
        ii.notes,
        COALESCE(ii.tags_json, '[]') AS tags_json,
        GROUP_CONCAT(DISTINCT cp.finish) AS available_finishes
    FROM inventory_items ii
    JOIN inventories i ON i.id = ii.inventory_id
    JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
    LEFT JOIN current_prices cp
      ON cp.scryfall_id = ii.scryfall_id
    WHERE i.slug = ?
    GROUP BY
        ii.id,
        ii.inventory_id,
        i.slug,
        ii.scryfall_id,
        c.name,
        c.set_code,
        c.set_name,
        c.collector_number,
        ii.quantity,
        ii.condition_code,
        ii.finish,
        ii.language_code,
        ii.location,
        ii.acquisition_price,
        ii.acquisition_currency,
        ii.notes,
        ii.tags_json
    HAVING SUM(CASE WHEN LOWER(COALESCE(cp.finish, '')) = LOWER(ii.finish) THEN 1 ELSE 0 END) = 0
    ORDER BY c.name, c.set_code, c.collector_number
    """
    params: list[Any] = [*current_price_params, inventory_slug]
    if limit is not None:
        sql += "\nLIMIT ?"
        params.append(limit)

    rows = connection.execute(sql, params).fetchall()
    return [build_price_gap_result(row) for row in rows]


def query_stale_price_rows(
    connection: sqlite3.Connection,
    *,
    inventory_slug: str,
    provider: str,
    current_date: str,
    cutoff_date: str,
) -> list[dict[str, Any]]:
    latest_prices_cte, latest_price_params = build_latest_retail_prices_cte(provider=provider)
    rows = connection.execute(
        """
        WITH
        """
        + latest_prices_cte
        + """
        SELECT
            ii.id AS item_id,
            c.name AS card_name,
            c.set_code,
            c.collector_number,
            ii.finish,
            lp.snapshot_date AS price_date,
            CAST(julianday(?) - julianday(lp.snapshot_date) AS INTEGER) AS age_days
        FROM inventory_items ii
        JOIN inventories i ON i.id = ii.inventory_id
        JOIN mtg_cards c ON c.scryfall_id = ii.scryfall_id
        JOIN latest_prices lp
            ON lp.scryfall_id = ii.scryfall_id
           AND lp.finish = ii.finish
           AND lp.rn = 1
        WHERE i.slug = ?
          AND lp.snapshot_date < ?
        ORDER BY age_days DESC, c.name, c.set_code, c.collector_number, ii.id
        """,
        [*latest_price_params, current_date, inventory_slug, cutoff_date],
    ).fetchall()
    return [
        {
            "item_id": row["item_id"],
            "name": truncate(row["card_name"], 28),
            "set": row["set_code"],
            "number": row["collector_number"],
            "finish": row["finish"],
            "price_date": row["price_date"],
            "age_days": row["age_days"],
        }
        for row in rows
    ]
