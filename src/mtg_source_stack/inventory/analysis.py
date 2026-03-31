from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

from ..db.connection import connect, require_database_file
from ..db.schema import initialize_database
from .mutations import set_finish_with_connection
from .normalize import coerce_float, format_finishes, truncate
from .queries import (
    add_owned_filters,
    get_inventory_row,
    query_duplicate_like_groups,
    query_inventory_summary,
    query_merge_note_rows,
    query_missing_location_rows,
    query_missing_tag_rows,
    query_price_gaps,
    query_stale_price_rows,
)
from .report_helpers import build_currency_totals, build_top_value_rows, summarize_filters
from .report_io import flatten_owned_export_rows, write_inventory_export_csv


def list_price_gaps(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None,
) -> list[dict[str, Any]]:
    require_database_file(db_path)
    initialize_database(db_path)
    with connect(db_path) as connection:
        return query_price_gaps(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=limit,
        )


def reconcile_prices(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    apply_changes: bool,
) -> dict[str, Any]:
    initialize_database(db_path)
    with connect(db_path) as connection:
        rows = query_price_gaps(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=None,
        )

        updated_rows: list[dict[str, Any]] = []
        remaining_rows: list[dict[str, Any]] = []
        rows_fixable = 0

        for row in rows:
            suggested_finish = row["suggested_finish"]
            if suggested_finish is None:
                remaining_rows.append(row)
                continue

            rows_fixable += 1
            if not apply_changes:
                updated_rows.append(row)
                continue

            try:
                updated = set_finish_with_connection(
                    connection,
                    inventory_slug=inventory_slug,
                    item_id=row["item_id"],
                    finish=suggested_finish,
                )
            except ValueError as exc:
                row["reconcile_status"] = str(exc)
                remaining_rows.append(row)
                continue

            updated["available_finishes"] = row["available_finishes"]
            updated["suggested_finish"] = suggested_finish
            updated["reconcile_status"] = "updated"
            updated_rows.append(updated)

        if apply_changes:
            connection.commit()

    return {
        "inventory": inventory_slug,
        "provider": provider,
        "applied": apply_changes,
        "rows_seen": len(rows),
        "rows_fixable": rows_fixable,
        "rows_updated": len(updated_rows) if apply_changes else 0,
        "updated_rows": updated_rows,
        "remaining_rows": remaining_rows,
    }


def inventory_health(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    stale_days: int,
    preview_limit: int,
) -> dict[str, Any]:
    if stale_days < 0:
        raise ValueError("--stale-days must be zero or greater.")
    if preview_limit <= 0:
        raise ValueError("--limit must be a positive integer.")

    require_database_file(db_path)
    initialize_database(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)
        current_date = dt.date.today()
        cutoff_date = current_date - dt.timedelta(days=stale_days)

        summary = query_inventory_summary(connection, inventory_slug=inventory_slug)
        missing_price_rows = query_price_gaps(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            limit=None,
        )
        missing_location_rows = query_missing_location_rows(connection, inventory_slug=inventory_slug)
        missing_tag_rows = query_missing_tag_rows(connection, inventory_slug=inventory_slug)
        merge_note_rows = query_merge_note_rows(connection, inventory_slug=inventory_slug)
        stale_price_rows = query_stale_price_rows(
            connection,
            inventory_slug=inventory_slug,
            provider=provider,
            current_date=current_date.isoformat(),
            cutoff_date=cutoff_date.isoformat(),
        )
        duplicate_groups = query_duplicate_like_groups(connection, inventory_slug=inventory_slug)

    formatted_missing_prices = [
        {
            "item_id": row["item_id"],
            "name": truncate(row["card_name"], 28),
            "set": row["set_code"],
            "number": row["collector_number"],
            "finish": row["finish"],
            "priced_finishes": truncate(format_finishes(row["available_finishes"]), 18),
            "status": truncate(row["reconcile_status"], 24),
        }
        for row in missing_price_rows
    ]

    summary.update(
        {
            "missing_price_rows": len(missing_price_rows),
            "missing_location_rows": len(missing_location_rows),
            "missing_tag_rows": len(missing_tag_rows),
            "merge_note_rows": len(merge_note_rows),
            "stale_price_rows": len(stale_price_rows),
            "duplicate_groups": len(duplicate_groups),
        }
    )

    return {
        "inventory": inventory_slug,
        "provider": provider,
        "stale_days": stale_days,
        "current_date": current_date.isoformat(),
        "preview_limit": preview_limit,
        "summary": summary,
        "missing_price_rows": formatted_missing_prices,
        "missing_location_rows": missing_location_rows,
        "missing_tag_rows": missing_tag_rows,
        "merge_note_rows": merge_note_rows,
        "stale_price_rows": stale_price_rows,
        "duplicate_groups": duplicate_groups,
    }


def list_owned(db_path: str | Path, inventory_slug: str, provider: str, limit: int | None) -> list[dict[str, Any]]:
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
) -> list[dict[str, Any]]:
    require_database_file(db_path)
    initialize_database(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)
        params: list[Any] = [provider, inventory_slug]
        where_parts = ["i.slug = ?"]
        add_owned_filters(
            where_parts,
            params,
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
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(limit)

        rows = connection.execute(
            f"""
            WITH latest_prices AS (
                SELECT
                    scryfall_id,
                    provider,
                    finish,
                    currency,
                    price_value,
                    snapshot_date,
                    ROW_NUMBER() OVER (
                        PARTITION BY scryfall_id, provider, finish, currency
                        ORDER BY snapshot_date DESC, id DESC
                    ) AS rn
                FROM price_snapshots
                WHERE price_kind = 'retail'
                  AND provider = ?
            )
            SELECT
                ii.id AS item_id,
                ii.scryfall_id,
                c.name,
                c.set_code,
                c.set_name,
                COALESCE(c.rarity, '') AS rarity,
                c.collector_number,
                ii.quantity,
                ii.condition_code,
                ii.finish,
                ii.language_code,
                ii.location,
                COALESCE(ii.tags_json, '[]') AS tags_json,
                ii.acquisition_price,
                COALESCE(ii.acquisition_currency, '') AS acquisition_currency,
                COALESCE(lp.currency, '') AS currency,
                COALESCE(lp.price_value, '') AS unit_price,
                COALESCE(ROUND(ii.quantity * lp.price_value, 2), '') AS est_value,
                COALESCE(lp.snapshot_date, '') AS price_date,
                COALESCE(ii.notes, '') AS notes
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
    return [dict(row) for row in rows]


def export_inventory_csv(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    output_path: str | Path,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
    limit: int | None,
) -> dict[str, Any]:
    rows = list_owned_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        limit=limit,
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )
    output = write_inventory_export_csv(
        output_path,
        rows,
        inventory_slug=inventory_slug,
        provider=provider,
    )
    return {
        "inventory": inventory_slug,
        "provider": provider,
        "output_path": str(output),
        "rows_exported": len(rows),
        "filters_text": summarize_filters(
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        ),
        "rows": rows,
    }


def valuation(db_path: str | Path, inventory_slug: str, provider: str | None) -> list[dict[str, Any]]:
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
) -> list[dict[str, Any]]:
    require_database_file(db_path)
    initialize_database(db_path)
    with connect(db_path) as connection:
        get_inventory_row(connection, inventory_slug)

        if provider:
            params: list[Any] = [provider, provider, inventory_slug]
            where_parts = ["i.slug = ?"]
            add_owned_filters(
                where_parts,
                params,
                query=query,
                set_code=set_code,
                rarity=rarity,
                finish=finish,
                condition_code=condition_code,
                language_code=language_code,
                location=location,
                tags=tags,
            )
            rows = connection.execute(
                f"""
                WITH latest_prices AS (
                    SELECT
                        scryfall_id,
                        provider,
                        finish,
                        currency,
                        price_value,
                        ROW_NUMBER() OVER (
                            PARTITION BY scryfall_id, provider, finish, currency
                            ORDER BY snapshot_date DESC, id DESC
                        ) AS rn
                    FROM price_snapshots
                    WHERE price_kind = 'retail'
                      AND provider = ?
                )
                SELECT
                    ? AS provider,
                    COALESCE(lp.currency, '') AS currency,
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
            return [dict(row) for row in rows]

        params = [inventory_slug]
        where_parts = ["i.slug = ?"]
        add_owned_filters(
            where_parts,
            params,
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        )
        rows = connection.execute(
            f"""
            WITH latest_prices AS (
                SELECT
                    scryfall_id,
                    provider,
                    finish,
                    currency,
                    price_value,
                    ROW_NUMBER() OVER (
                        PARTITION BY scryfall_id, provider, finish, currency
                        ORDER BY snapshot_date DESC, id DESC
                    ) AS rn
                FROM price_snapshots
                WHERE price_kind = 'retail'
            )
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
        return [dict(row) for row in rows]


def inventory_report(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    query: str | None,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    condition_code: str | None,
    language_code: str | None,
    location: str | None,
    tags: list[str] | None,
    limit: int,
    stale_days: int,
) -> dict[str, Any]:
    rows = list_owned_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        limit=None,
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )
    valuation_rows = valuation_filtered(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )
    health = inventory_health(
        db_path,
        inventory_slug=inventory_slug,
        provider=provider,
        stale_days=stale_days,
        preview_limit=limit,
    )
    filtered_health_summary = {
        "item_rows": len(rows),
        "total_cards": sum(int(row["quantity"]) for row in rows),
        "missing_price_rows": 0,
        "missing_location_rows": 0,
        "missing_tag_rows": 0,
        "merge_note_rows": 0,
        "stale_price_rows": 0,
        "duplicate_groups": 0,
    }

    filters_text = summarize_filters(
        query=query,
        set_code=set_code,
        rarity=rarity,
        finish=finish,
        condition_code=condition_code,
        language_code=language_code,
        location=location,
        tags=tags,
    )

    summary = {
        "item_rows": len(rows),
        "total_cards": sum(int(row["quantity"]) for row in rows),
        "unique_printings": len({row["scryfall_id"] for row in rows}),
        "unique_card_names": len({row["name"] for row in rows}),
        "valued_rows": sum(1 for row in rows if coerce_float(row.get("unit_price")) is not None),
        "unpriced_rows": sum(1 for row in rows if coerce_float(row.get("unit_price")) is None),
    }

    acquisition_totals = build_currency_totals(
        rows,
        value_key="acquisition_price",
        currency_key="acquisition_currency",
        quantity_key="quantity",
    )
    top_rows = build_top_value_rows(rows, limit=limit)

    if filters_text == "(none)":
        filtered_health_summary = health["summary"]
    else:
        filtered_ids = {row["item_id"] for row in rows}
        filtered_duplicate_keys = {
            (row["scryfall_id"], row["condition_code"], row["finish"], row["language_code"])
            for row in rows
        }
        filtered_health = {
            **health,
            "missing_price_rows": [row for row in health["missing_price_rows"] if row["item_id"] in filtered_ids],
            "missing_location_rows": [row for row in health["missing_location_rows"] if row["item_id"] in filtered_ids],
            "missing_tag_rows": [row for row in health["missing_tag_rows"] if row["item_id"] in filtered_ids],
            "merge_note_rows": [row for row in health["merge_note_rows"] if row["item_id"] in filtered_ids],
            "stale_price_rows": [row for row in health["stale_price_rows"] if row["item_id"] in filtered_ids],
            "duplicate_groups": [
                row
                for row in health["duplicate_groups"]
                if (
                    row["scryfall_id"],
                    row["condition_code"],
                    row["finish"],
                    row["language_code"],
                )
                in filtered_duplicate_keys
            ],
        }
        filtered_health_summary.update(
            {
                "missing_price_rows": len(filtered_health["missing_price_rows"]),
                "missing_location_rows": len(filtered_health["missing_location_rows"]),
                "missing_tag_rows": len(filtered_health["missing_tag_rows"]),
                "merge_note_rows": len(filtered_health["merge_note_rows"]),
                "stale_price_rows": len(filtered_health["stale_price_rows"]),
                "duplicate_groups": len(filtered_health["duplicate_groups"]),
            }
        )
        health = {**filtered_health, "summary": filtered_health_summary}

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "inventory": inventory_slug,
        "provider": provider,
        "filters_text": filters_text,
        "summary": summary,
        "valuation_rows": valuation_rows,
        "acquisition_totals": acquisition_totals,
        "top_rows": top_rows,
        "health": health,
        "rows": flatten_owned_export_rows(rows, inventory_slug=inventory_slug, provider=provider),
    }
