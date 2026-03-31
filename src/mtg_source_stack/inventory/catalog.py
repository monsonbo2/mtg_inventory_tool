"""Catalog lookup helpers for local MTG card data."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import require_current_schema
from .normalize import normalize_catalog_finishes
from .query_catalog import add_catalog_filters


def search_cards(
    db_path: str | Path,
    query: str,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: str | None = None,
    lang: str | None = None,
    exact: bool = False,
    limit: int = 10,
) -> list[dict[str, Any]]:
    require_current_schema(db_path)
    with connect(db_path) as connection:
        where_parts: list[str] = []
        params: list[Any] = []
        if exact:
            where_parts.append("LOWER(name) = LOWER(?)")
            params.append(query)
        else:
            where_parts.append("LOWER(name) LIKE LOWER(?)")
            params.append(f"%{query}%")

        add_catalog_filters(
            where_parts,
            params,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            lang=lang,
        )

        params.extend([query, limit])
        rows = connection.execute(
            f"""
            SELECT
                scryfall_id,
                name,
                set_code,
                set_name,
                collector_number,
                lang,
                rarity,
                finishes_json,
                tcgplayer_product_id
            FROM mtg_cards
            WHERE {' AND '.join(where_parts)}
            ORDER BY
                CASE WHEN LOWER(name) = LOWER(?) THEN 0 ELSE 1 END,
                name,
                released_at DESC,
                set_code,
                collector_number
            LIMIT ?
            """,
            params,
        ).fetchall()

    results = []
    for row in rows:
        item = dict(row)
        item["finishes"] = normalize_catalog_finishes(item.pop("finishes_json", None))
        results.append(item)
    return results


def resolve_card_row(
    connection: sqlite3.Connection,
    *,
    scryfall_id: str | None,
    tcgplayer_product_id: str | None,
    name: str | None,
    set_code: str | None,
    collector_number: str | None,
    lang: str | None,
) -> sqlite3.Row:
    # Resolve by the most specific identifiers first so CLI commands stay
    # predictable even when names or external product ids are ambiguous.
    if scryfall_id:
        row = connection.execute(
            """
            SELECT scryfall_id, name, set_code, set_name, collector_number, lang, finishes_json
            FROM mtg_cards
            WHERE scryfall_id = ?
            """,
            (scryfall_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No card found for scryfall_id '{scryfall_id}'.")
        return row

    if tcgplayer_product_id:
        row = connection.execute(
            """
            SELECT scryfall_id, name, set_code, set_name, collector_number, lang, finishes_json
            FROM mtg_cards
            WHERE tcgplayer_product_id = ?
            ORDER BY released_at DESC, set_code, collector_number
            LIMIT 2
            """,
            (tcgplayer_product_id,),
        ).fetchall()
        if not row:
            raise ValueError(f"No card found for tcgplayer_product_id '{tcgplayer_product_id}'.")
        if len(row) > 1:
            raise ValueError(
                "Multiple printings matched that TCGplayer product id. "
                "Narrow it with --scryfall-id or provide name/set details."
            )
        return row[0]

    if not name:
        raise ValueError("Provide either --scryfall-id, --tcgplayer-product-id, or --name.")

    params: list[Any] = [name]
    filters = ["LOWER(name) = LOWER(?)"]

    if set_code:
        filters.append("LOWER(set_code) = LOWER(?)")
        params.append(set_code)
    if collector_number:
        filters.append("collector_number = ?")
        params.append(collector_number)
    if lang:
        filters.append("LOWER(lang) = LOWER(?)")
        params.append(lang)

    rows = connection.execute(
        f"""
        SELECT scryfall_id, name, set_code, set_name, collector_number, lang, finishes_json
        FROM mtg_cards
        WHERE {' AND '.join(filters)}
        ORDER BY released_at DESC, set_code, collector_number
        LIMIT 10
        """,
        params,
    ).fetchall()

    if not rows:
        raise ValueError("No matching printing found. Try search-cards first to find the exact printing.")
    if len(rows) > 1:
        candidates = "; ".join(
            f"{row['set_code']} #{row['collector_number']} ({row['lang']}) [{row['scryfall_id']}]"
            for row in rows
        )
        raise ValueError(
            "Multiple printings matched that name. Narrow it with --set-code, --collector-number, or --scryfall-id. "
            f"Candidates: {candidates}"
        )
    return rows[0]
