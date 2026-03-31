"""Inventory queries, valuation, and report assembly helpers."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ValidationError
from .money import coerce_decimal
from .normalize import format_finishes, load_tags_json, text_or_none, truncate
from .query_inventory import add_owned_filters, get_inventory_row
from .query_pricing import build_latest_retail_prices_cte, query_price_gaps, query_stale_price_rows
from .query_reporting import (
    query_duplicate_like_groups,
    query_inventory_summary,
    query_merge_note_rows,
    query_missing_location_rows,
    query_missing_tag_rows,
)
from .reports import (
    build_currency_totals,
    build_top_value_rows,
    summarize_filters,
    write_inventory_export_csv,
)
from .response_models import (
    CurrencyTotalRow,
    DuplicateGroupRow,
    ExportInventoryCsvResult,
    HealthItemPreviewRow,
    InventoryHealthResult,
    InventoryHealthSummary,
    InventoryReportResult,
    InventoryReportSummary,
    MissingPricePreviewRow,
    OwnedInventoryRow,
    PriceGapRow,
    ReconcilePricesResult,
    StalePricePreviewRow,
    TopValueRow,
    ValuationRow,
    serialize_response,
)


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


def build_owned_inventory_row(row: dict[str, Any]) -> OwnedInventoryRow:
    unit_price = coerce_decimal(row.get("unit_price"))
    quantity = int(row["quantity"])
    return OwnedInventoryRow(
        item_id=int(row["item_id"]),
        scryfall_id=row["scryfall_id"],
        name=row["name"],
        set_code=row["set_code"],
        set_name=row["set_name"],
        rarity=text_or_none(row.get("rarity")),
        collector_number=row["collector_number"],
        quantity=quantity,
        condition_code=row["condition_code"],
        finish=row["finish"],
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
    )


def build_valuation_row(row: dict[str, Any]) -> ValuationRow:
    return ValuationRow(
        provider=text_or_none(row.get("provider")),
        currency=text_or_none(row.get("currency")),
        item_rows=int(row["item_rows"]),
        total_cards=int(row["total_cards"]),
        total_value=coerce_decimal(row.get("total_value")) or Decimal("0"),
    )


def build_missing_price_preview_row(row: dict[str, Any]) -> MissingPricePreviewRow:
    return MissingPricePreviewRow(
        item_id=int(row["item_id"]),
        name=row["name"],
        set=row["set"],
        number=row["number"],
        finish=row["finish"],
        priced_finishes=row["priced_finishes"],
        status=row["status"],
    )


def build_health_item_preview_row(row: dict[str, Any]) -> HealthItemPreviewRow:
    return HealthItemPreviewRow(
        item_id=int(row["item_id"]),
        name=row["name"],
        set=row["set"],
        number=row["number"],
        qty=int(row["qty"]),
        cond=row["cond"],
        finish=row["finish"],
        location=row["location"],
        tags=row["tags"],
        note=row["note"],
    )


def build_stale_price_preview_row(row: dict[str, Any]) -> StalePricePreviewRow:
    return StalePricePreviewRow(
        item_id=int(row["item_id"]),
        name=row["name"],
        set=row["set"],
        number=row["number"],
        finish=row["finish"],
        price_date=row["price_date"],
        age_days=int(row["age_days"]),
    )


def build_duplicate_group_row(row: dict[str, Any]) -> DuplicateGroupRow:
    return DuplicateGroupRow(
        scryfall_id=row["scryfall_id"],
        condition_code=row["condition_code"],
        language_code=row["language_code"],
        name=row["name"],
        set=row["set"],
        number=row["number"],
        cond=row["cond"],
        finish=row["finish"],
        rows=int(row["rows"]),
        qty=int(row["qty"]),
        locations=row["locations"],
    )


def list_price_gaps(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    limit: int | None,
) -> list[PriceGapRow]:
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


def inventory_health(
    db_path: str | Path,
    *,
    inventory_slug: str,
    provider: str,
    stale_days: int,
    preview_limit: int,
) -> InventoryHealthResult:
    if stale_days < 0:
        raise ValidationError("--stale-days must be zero or greater.")
    if preview_limit <= 0:
        raise ValidationError("--limit must be a positive integer.")

    require_current_schema(db_path)
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
        MissingPricePreviewRow(
            item_id=int(row["item_id"]),
            name=truncate(row["card_name"], 28),
            set=row["set_code"],
            number=row["collector_number"],
            finish=row["finish"],
            priced_finishes=truncate(format_finishes(row["available_finishes"]), 18),
            status=truncate(row["reconcile_status"], 24),
        )
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

    return InventoryHealthResult(
        inventory=inventory_slug,
        provider=provider,
        stale_days=stale_days,
        current_date=current_date.isoformat(),
        preview_limit=preview_limit,
        summary=InventoryHealthSummary(
            item_rows=int(summary["item_rows"]),
            total_cards=int(summary["total_cards"]),
            missing_price_rows=int(summary["missing_price_rows"]),
            missing_location_rows=int(summary["missing_location_rows"]),
            missing_tag_rows=int(summary["missing_tag_rows"]),
            merge_note_rows=int(summary["merge_note_rows"]),
            stale_price_rows=int(summary["stale_price_rows"]),
            duplicate_groups=int(summary["duplicate_groups"]),
        ),
        missing_price_rows=formatted_missing_prices,
        missing_location_rows=[build_health_item_preview_row(row) for row in missing_location_rows],
        missing_tag_rows=[build_health_item_preview_row(row) for row in missing_tag_rows],
        merge_note_rows=[build_health_item_preview_row(row) for row in merge_note_rows],
        stale_price_rows=[build_stale_price_preview_row(row) for row in stale_price_rows],
        duplicate_groups=[build_duplicate_group_row(row) for row in duplicate_groups],
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
                c.name,
                c.set_code,
                c.set_name,
                c.rarity,
                c.collector_number,
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
                ii.notes
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
) -> ExportInventoryCsvResult:
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
        serialize_response(rows),
        inventory_slug=inventory_slug,
        provider=provider,
    )
    return ExportInventoryCsvResult(
        inventory=inventory_slug,
        provider=provider,
        output_path=str(output),
        rows_exported=len(rows),
        filters_text=summarize_filters(
            query=query,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            condition_code=condition_code,
            language_code=language_code,
            location=location,
            tags=tags,
        ),
        rows=rows,
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


def build_duplicate_groups_from_owned_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            row["scryfall_id"],
            row["condition_code"],
            row["finish"],
            row["language_code"],
        )
        group = grouped.setdefault(
            key,
            {
                "scryfall_id": row["scryfall_id"],
                "condition_code": row["condition_code"],
                "language_code": row["language_code"],
                "name": truncate(row["name"], 28),
                "set": row["set_code"],
                "number": row["collector_number"],
                "cond": row["condition_code"],
                "finish": row["finish"],
                "rows": 0,
                "qty": 0,
                "_locations": set(),
            },
        )
        group["rows"] += 1
        group["qty"] += int(row["quantity"])
        group["_locations"].add(text_or_none(row.get("location")) or "(none)")

    duplicate_groups: list[dict[str, Any]] = []
    for group in grouped.values():
        if group["rows"] <= 1:
            continue
        locations = ", ".join(sorted(group["_locations"]))
        duplicate_groups.append(
            {
                "scryfall_id": group["scryfall_id"],
                "condition_code": group["condition_code"],
                "language_code": group["language_code"],
                "name": group["name"],
                "set": group["set"],
                "number": group["number"],
                "cond": group["cond"],
                "finish": group["finish"],
                "rows": group["rows"],
                "qty": group["qty"],
                "locations": truncate(locations, 32),
            }
        )

    duplicate_groups.sort(
        key=lambda row: (-int(row["rows"]), -int(row["qty"]), row["name"], row["set"], row["number"])
    )
    return duplicate_groups


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
) -> InventoryReportResult:
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
        "total_cards": sum(row.quantity for row in rows),
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

    summary = InventoryReportSummary(
        item_rows=len(rows),
        total_cards=sum(row.quantity for row in rows),
        unique_printings=len({row.scryfall_id for row in rows}),
        unique_card_names=len({row.name for row in rows}),
        valued_rows=sum(1 for row in rows if row.unit_price is not None),
        unpriced_rows=sum(1 for row in rows if row.unit_price is None),
    )

    rows_payload = serialize_response(rows)
    acquisition_totals = [
        CurrencyTotalRow(
            currency=row["currency"],
            item_rows=int(row["item_rows"]),
            total_cards=int(row["total_cards"]),
            total_amount=coerce_decimal(row.get("total_amount")) or Decimal("0"),
        )
        for row in build_currency_totals(
            rows_payload,
            value_key="acquisition_price",
            currency_key="acquisition_currency",
            quantity_key="quantity",
        )
    ]
    top_rows = [
        TopValueRow(
            item_id=int(row["item_id"]),
            name=row["name"],
            set=row["set"],
            number=row["number"],
            qty=int(row["qty"]),
            finish=row["finish"],
            location=row["location"],
            est_value=coerce_decimal(row.get("est_value")),
            currency=text_or_none(row.get("currency")),
        )
        for row in build_top_value_rows(rows_payload, limit=limit)
    ]

    health_result = health
    if filters_text == "(none)":
        filtered_health_summary = serialize_response(health.summary)
    else:
        # Row-level health buckets can be filtered by item id, but duplicate
        # groups need to be recomputed from the report rows themselves so a
        # slice containing only one side of a duplicate pair does not inherit
        # the full-inventory group.
        filtered_ids = {row.item_id for row in rows}
        filtered_duplicate_groups = [
            build_duplicate_group_row(row)
            for row in build_duplicate_groups_from_owned_rows(rows_payload)
        ]
        health_result = InventoryHealthResult(
            inventory=health.inventory,
            provider=health.provider,
            stale_days=health.stale_days,
            current_date=health.current_date,
            preview_limit=health.preview_limit,
            summary=health.summary,
            missing_price_rows=[row for row in health.missing_price_rows if row.item_id in filtered_ids],
            missing_location_rows=[row for row in health.missing_location_rows if row.item_id in filtered_ids],
            missing_tag_rows=[row for row in health.missing_tag_rows if row.item_id in filtered_ids],
            merge_note_rows=[row for row in health.merge_note_rows if row.item_id in filtered_ids],
            stale_price_rows=[row for row in health.stale_price_rows if row.item_id in filtered_ids],
            duplicate_groups=filtered_duplicate_groups,
        )
        filtered_health_summary.update(
            {
                "missing_price_rows": len(health_result.missing_price_rows),
                "missing_location_rows": len(health_result.missing_location_rows),
                "missing_tag_rows": len(health_result.missing_tag_rows),
                "merge_note_rows": len(health_result.merge_note_rows),
                "stale_price_rows": len(health_result.stale_price_rows),
                "duplicate_groups": len(health_result.duplicate_groups),
            }
        )
        health_result = InventoryHealthResult(
            inventory=health_result.inventory,
            provider=health_result.provider,
            stale_days=health_result.stale_days,
            current_date=health_result.current_date,
            preview_limit=health_result.preview_limit,
            summary=InventoryHealthSummary(
                item_rows=int(filtered_health_summary["item_rows"]),
                total_cards=int(filtered_health_summary["total_cards"]),
                missing_price_rows=int(filtered_health_summary["missing_price_rows"]),
                missing_location_rows=int(filtered_health_summary["missing_location_rows"]),
                missing_tag_rows=int(filtered_health_summary["missing_tag_rows"]),
                merge_note_rows=int(filtered_health_summary["merge_note_rows"]),
                stale_price_rows=int(filtered_health_summary["stale_price_rows"]),
                duplicate_groups=int(filtered_health_summary["duplicate_groups"]),
            ),
            missing_price_rows=health_result.missing_price_rows,
            missing_location_rows=health_result.missing_location_rows,
            missing_tag_rows=health_result.missing_tag_rows,
            merge_note_rows=health_result.merge_note_rows,
            stale_price_rows=health_result.stale_price_rows,
            duplicate_groups=health_result.duplicate_groups,
        )

    return InventoryReportResult(
        generated_at=dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        inventory=inventory_slug,
        provider=provider,
        filters_text=filters_text,
        summary=summary,
        valuation_rows=valuation_rows,
        acquisition_totals=acquisition_totals,
        top_rows=top_rows,
        health=health_result,
        rows=rows,
    )
