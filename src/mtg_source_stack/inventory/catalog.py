"""Catalog lookup helpers for local MTG card data."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import NotFoundError, ValidationError
from .normalize import DEFAULT_SEARCH_LIMIT, MAX_SEARCH_LIMIT, normalized_catalog_finish_list, validate_limit_value
from .query_catalog import add_catalog_filters, build_catalog_search_fts_query
from .response_models import CatalogSearchRow


def search_cards(
    db_path: str | Path,
    query: str,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: str | None = None,
    lang: str | None = None,
    exact: bool = False,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> list[CatalogSearchRow]:
    validate_limit_value(limit, maximum=MAX_SEARCH_LIMIT)
    require_current_schema(db_path)
    with connect(db_path) as connection:
        where_parts: list[str] = []
        params: list[Any] = []
        search_cte = """
        WITH search_match AS (
            SELECT
                NULL AS scryfall_id,
                NULL AS search_rank
            WHERE 0
        )
        """
        search_join = "LEFT JOIN search_match ON 1 = 0"
        fts_query = build_catalog_search_fts_query(query) if not exact else None
        if exact:
            where_parts.append("LOWER(name) = LOWER(?)")
            params.append(query)
        else:
            where_parts.append("(search_match.scryfall_id IS NOT NULL OR LOWER(name) LIKE LOWER(?))")
            params.append(f"%{query}%")
            if fts_query is not None:
                search_cte = """
                WITH search_match AS (
                    SELECT
                        scryfall_id,
                        bm25(mtg_cards_fts) AS search_rank
                    FROM mtg_cards_fts
                    WHERE mtg_cards_fts MATCH ?
                )
                """
                search_join = "LEFT JOIN search_match ON search_match.scryfall_id = mtg_cards.scryfall_id"

        add_catalog_filters(
            where_parts,
            params,
            set_code=set_code,
            rarity=rarity,
            finish=finish,
            lang=lang,
        )

        if not exact and fts_query is not None:
            params = [fts_query, *params]
        params.extend([query, f"{query}%", limit])
        rows = connection.execute(
            f"""
            {search_cte}
            SELECT
                mtg_cards.scryfall_id,
                mtg_cards.name,
                mtg_cards.set_code,
                mtg_cards.set_name,
                mtg_cards.collector_number,
                mtg_cards.lang,
                mtg_cards.rarity,
                mtg_cards.finishes_json,
                mtg_cards.tcgplayer_product_id
            FROM mtg_cards
            {search_join}
            WHERE {' AND '.join(where_parts)}
            ORDER BY
                CASE
                    WHEN LOWER(mtg_cards.name) = LOWER(?) THEN 0
                    WHEN LOWER(mtg_cards.name) LIKE LOWER(?) THEN 1
                    WHEN search_match.scryfall_id IS NOT NULL THEN 2
                    ELSE 3
                END,
                COALESCE(search_match.search_rank, 0),
                mtg_cards.name,
                mtg_cards.released_at DESC,
                mtg_cards.set_code,
                mtg_cards.collector_number
            LIMIT ?
            """,
            params,
        ).fetchall()

    results: list[CatalogSearchRow] = []
    for row in rows:
        item = dict(row)
        results.append(
            CatalogSearchRow(
                scryfall_id=item["scryfall_id"],
                name=item["name"],
                set_code=item["set_code"],
                set_name=item["set_name"],
                collector_number=item["collector_number"],
                lang=item["lang"],
                rarity=item["rarity"],
                finishes=normalized_catalog_finish_list(item.pop("finishes_json", None)),
                tcgplayer_product_id=item["tcgplayer_product_id"],
            )
        )
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
            raise NotFoundError(f"No card found for scryfall_id '{scryfall_id}'.")
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
            raise NotFoundError(f"No card found for tcgplayer_product_id '{tcgplayer_product_id}'.")
        if len(row) > 1:
            raise ValidationError(
                "Multiple printings matched that TCGplayer product id. "
                "Narrow it with --scryfall-id or provide name/set details."
            )
        return row[0]

    if not name:
        raise ValidationError("Provide either --scryfall-id, --tcgplayer-product-id, or --name.")

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
        raise NotFoundError("No matching printing found. Try search-cards first to find the exact printing.")
    if len(rows) > 1:
        candidates = "; ".join(
            f"{row['set_code']} #{row['collector_number']} ({row['lang']}) [{row['scryfall_id']}]"
            for row in rows
        )
        raise ValidationError(
            "Multiple printings matched that name. Narrow it with --set-code, --collector-number, or --scryfall-id. "
            f"Candidates: {candidates}"
        )
    return rows[0]
