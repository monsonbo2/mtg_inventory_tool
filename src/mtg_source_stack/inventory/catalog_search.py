"""Catalog search and grouped name lookup helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import ValidationError
from .normalize import (
    CANONICAL_LANGUAGE_CODES,
    DEFAULT_SEARCH_LIMIT,
    MAX_SEARCH_LIMIT,
    extract_image_uri_fields,
    normalize_catalog_search_scope,
    normalize_language_code,
    normalized_catalog_finish_list,
    text_or_none,
    validate_limit_value,
)
from .query_catalog import (
    add_catalog_filters,
    add_catalog_scope_filter,
    build_catalog_search_fts_query,
    catalog_scope_filter_sql,
    catalog_search_tokens,
)
from .response_models import (
    CatalogNameSearchResult,
    CatalogNameSearchRow,
    CatalogSearchRow,
)


_LANGUAGE_ORDER = {code: index for index, code in enumerate(CANONICAL_LANGUAGE_CODES)}
_GROUPED_NAME_SUBSTRING_FALLBACK_MIN_QUERY_LENGTH = 5


def _catalog_search_row_kwargs_from_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    item = dict(payload)
    image_uri_small, image_uri_normal = extract_image_uri_fields(item.pop("image_uris_json", None))
    return {
        "scryfall_id": item["scryfall_id"],
        "name": item["name"],
        "set_code": item["set_code"],
        "set_name": item["set_name"],
        "collector_number": item["collector_number"],
        "lang": item["lang"],
        "rarity": item["rarity"],
        "finishes": normalized_catalog_finish_list(item.pop("finishes_json", None)),
        "tcgplayer_product_id": item["tcgplayer_product_id"],
        "image_uri_small": image_uri_small,
        "image_uri_normal": image_uri_normal,
    }


def _catalog_search_row_from_payload(payload: Mapping[str, Any]) -> CatalogSearchRow:
    return CatalogSearchRow(**_catalog_search_row_kwargs_from_payload(payload))


def _language_sort_key(code: str) -> tuple[int, int, str]:
    normalized = normalize_language_code(code)
    return (
        0 if normalized == "en" else 1,
        _LANGUAGE_ORDER.get(normalized, len(_LANGUAGE_ORDER)),
        normalized,
    )


def _sorted_available_languages(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in sorted(
        (normalize_language_code(raw) for raw in values if text_or_none(raw) is not None),
        key=_language_sort_key,
    ):
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def search_cards(
    db_path: str | Path,
    query: str,
    set_code: str | None = None,
    rarity: str | None = None,
    finish: str | None = None,
    lang: str | None = None,
    exact: bool = False,
    limit: int = DEFAULT_SEARCH_LIMIT,
    scope: str | None = None,
) -> list[CatalogSearchRow]:
    if not query.strip():
        raise ValidationError("query is required.")
    normalized_scope = normalize_catalog_search_scope(scope)
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
        add_catalog_scope_filter(where_parts, scope=normalized_scope)

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
                mtg_cards.tcgplayer_product_id,
                mtg_cards.image_uris_json
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

    return [_catalog_search_row_from_payload(row) for row in rows]


def search_card_names(
    db_path: str | Path,
    query: str,
    *,
    exact: bool = False,
    limit: int = DEFAULT_SEARCH_LIMIT,
    scope: str | None = None,
) -> CatalogNameSearchResult:
    trimmed_query = query.strip()
    query_tokens = catalog_search_tokens(query)

    def _can_use_substring_fallback() -> bool:
        if exact:
            return False
        if len(query_tokens) != 1:
            return False
        return len(query_tokens[0]) >= _GROUPED_NAME_SUBSTRING_FALLBACK_MIN_QUERY_LENGTH

    def _load_grouped_rows(*, include_substring_fallback: bool) -> list[sqlite3.Row]:
        search_cte = """
        WITH search_match AS (
            SELECT
                NULL AS scryfall_id,
                NULL AS search_rank
            WHERE 0
        )
        """
        search_join = "LEFT JOIN search_match ON 1 = 0"
        where_parts: list[str] = []
        match_params: list[Any] = []
        fts_query = build_catalog_search_fts_query(query) if not exact else None

        if exact:
            where_parts.append("LOWER(mtg_cards.name) = LOWER(?)")
            match_params.append(trimmed_query)
        elif include_substring_fallback:
            where_parts.append("LOWER(mtg_cards.name) LIKE LOWER(?)")
            match_params.append(f"%{trimmed_query}%")
        else:
            if fts_query is None:
                return []
            search_cte = """
            WITH search_match AS (
                SELECT
                    scryfall_id,
                    rank AS search_rank
                FROM mtg_cards_fts
                WHERE mtg_cards_fts MATCH ?
            )
            """
            search_join = "LEFT JOIN search_match ON search_match.scryfall_id = mtg_cards.scryfall_id"
            where_parts.append("search_match.scryfall_id IS NOT NULL")

        add_catalog_scope_filter(where_parts, scope=normalized_scope)

        params: list[Any] = []
        if not exact and not include_substring_fallback and fts_query is not None:
            params.append(fts_query)
        params.extend(
            [
                trimmed_query,
                f"{trimmed_query}%",
                trimmed_query,
                trimmed_query,
                trimmed_query,
                trimmed_query,
                trimmed_query,
                f"{trimmed_query}%",
            ]
        )
        params.extend(match_params)
        params.append(limit)

        return connection.execute(
            f"""
            {search_cte},
            matched_printings AS (
                SELECT
                    mtg_cards.oracle_id,
                    LOWER(mtg_cards.name) AS name_sort,
                    COALESCE(mtg_cards.released_at, '') AS release_sort,
                    CASE
                        WHEN LOWER(mtg_cards.name) = LOWER(?) THEN 0
                        WHEN LOWER(mtg_cards.name) LIKE LOWER(?) THEN 1
                        WHEN search_match.scryfall_id IS NOT NULL THEN 2
                        ELSE 3
                    END AS match_order,
                    CASE
                        WHEN LOWER(mtg_cards.name) = LOWER(?) THEN 0
                        WHEN LOWER(SUBSTR(mtg_cards.name, 1, LENGTH(?))) = LOWER(?)
                             AND LENGTH(mtg_cards.name) > LENGTH(?)
                             AND SUBSTR(mtg_cards.name, LENGTH(?) + 1, 1) IN (
                                 ',', ':', ';', '!', '?', '.', '-', '/', '(', '['
                             ) THEN 1
                        WHEN LOWER(mtg_cards.name) LIKE LOWER(?) THEN 2
                        WHEN search_match.scryfall_id IS NOT NULL THEN 3
                        ELSE 4
                    END AS name_relevance_order,
                    COALESCE(search_match.search_rank, 0) AS search_rank,
                    mtg_cards.edhrec_rank
                FROM mtg_cards
                {search_join}
                WHERE {' AND '.join(where_parts)}
            ),
            matched_groups AS (
                SELECT
                    oracle_id,
                    MIN(match_order) AS match_order,
                    MIN(name_relevance_order) AS name_relevance_order,
                    MIN(CASE WHEN edhrec_rank IS NULL THEN 1 ELSE 0 END) AS edhrec_rank_missing,
                    MIN(edhrec_rank) AS best_edhrec_rank,
                    MIN(search_rank) AS best_search_rank,
                    MIN(name_sort) AS best_name_sort,
                    MAX(release_sort) AS newest_release_sort
                FROM matched_printings
                GROUP BY oracle_id
            ),
            ordered_groups AS (
                SELECT
                    oracle_id,
                    match_order,
                    name_relevance_order,
                    edhrec_rank_missing,
                    best_edhrec_rank,
                    best_search_rank,
                    total_count,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            match_order,
                            name_relevance_order,
                            edhrec_rank_missing,
                            COALESCE(best_edhrec_rank, 2147483647),
                            best_search_rank,
                            best_name_sort,
                            newest_release_sort DESC,
                            oracle_id
                    ) AS group_order
                FROM (
                    SELECT
                        oracle_id,
                        match_order,
                        name_relevance_order,
                        edhrec_rank_missing,
                        best_edhrec_rank,
                        best_search_rank,
                        best_name_sort,
                        newest_release_sort,
                        COUNT(*) OVER () AS total_count
                    FROM matched_groups
                )
            ),
            limited_groups AS (
                SELECT
                    oracle_id,
                    match_order,
                    name_relevance_order,
                    edhrec_rank_missing,
                    best_edhrec_rank,
                    best_search_rank,
                    total_count,
                    group_order
                FROM ordered_groups
                WHERE group_order <= ?
            ),
            group_counts AS (
                SELECT
                    oracle_id,
                    COUNT(*) AS printings_count
                FROM mtg_cards
                WHERE oracle_id IN (SELECT oracle_id FROM limited_groups)
                  AND {scope_filter_sql}
                GROUP BY oracle_id
            ),
            representative_rows AS (
                SELECT
                    mtg_cards.oracle_id,
                    mtg_cards.name,
                    mtg_cards.image_uris_json,
                    mtg_cards.released_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY mtg_cards.oracle_id
                        ORDER BY
                            CASE
                                WHEN LOWER(mtg_cards.lang) = 'en'
                                     AND COALESCE(mtg_cards.image_uris_json, '') <> '' THEN 0
                                WHEN LOWER(mtg_cards.lang) = 'en' THEN 1
                                WHEN COALESCE(mtg_cards.image_uris_json, '') <> '' THEN 2
                                ELSE 3
                            END,
                            COALESCE(mtg_cards.released_at, '') DESC,
                            LOWER(mtg_cards.name),
                            mtg_cards.set_code,
                            mtg_cards.collector_number,
                            mtg_cards.scryfall_id
                    ) AS row_number
                FROM mtg_cards
                INNER JOIN limited_groups ON limited_groups.oracle_id = mtg_cards.oracle_id
                WHERE {scope_filter_sql}
            )
            SELECT
                representative_rows.oracle_id,
                representative_rows.name,
                representative_rows.image_uris_json,
                representative_rows.released_at,
                group_counts.printings_count,
                limited_groups.total_count
            FROM limited_groups
            INNER JOIN representative_rows ON representative_rows.oracle_id = limited_groups.oracle_id
            INNER JOIN group_counts ON group_counts.oracle_id = limited_groups.oracle_id
            WHERE representative_rows.row_number = 1
            ORDER BY limited_groups.group_order
            """,
            params,
        ).fetchall()

    if not trimmed_query:
        raise ValidationError("query is required.")
    normalized_scope = normalize_catalog_search_scope(scope)
    scope_filter_sql = catalog_scope_filter_sql(normalized_scope)
    validate_limit_value(limit, maximum=MAX_SEARCH_LIMIT)
    require_current_schema(db_path)
    with connect(db_path) as connection:
        rows = _load_grouped_rows(include_substring_fallback=False)
        if not rows and _can_use_substring_fallback():
            # Keep infix rescue available without paying for it on ordinary
            # token/prefix searches that already produced grouped matches.
            rows = _load_grouped_rows(include_substring_fallback=True)
        if not rows:
            return CatalogNameSearchResult(items=[], total_count=0, has_more=False)

        oracle_ids = [row["oracle_id"] for row in rows]
        placeholders = ", ".join("?" for _ in oracle_ids)
        language_rows = connection.execute(
            f"""
            SELECT oracle_id, lang
            FROM mtg_cards
            WHERE oracle_id IN ({placeholders})
              AND {scope_filter_sql}
            ORDER BY
                CASE WHEN LOWER(lang) = 'en' THEN 0 ELSE 1 END,
                LOWER(lang),
                COALESCE(released_at, '') DESC,
                scryfall_id
            """,
            oracle_ids,
        ).fetchall()

    languages_by_oracle: dict[str, list[str]] = {}
    for row in language_rows:
        languages_by_oracle.setdefault(row["oracle_id"], []).append(row["lang"])

    items: list[CatalogNameSearchRow] = []
    for row in rows:
        image_uri_small, image_uri_normal = extract_image_uri_fields(row["image_uris_json"])
        items.append(
            CatalogNameSearchRow(
                oracle_id=row["oracle_id"],
                name=row["name"],
                printings_count=row["printings_count"],
                available_languages=_sorted_available_languages(languages_by_oracle.get(row["oracle_id"], [])),
                image_uri_small=image_uri_small,
                image_uri_normal=image_uri_normal,
            )
        )
    total_count = int(rows[0]["total_count"])
    return CatalogNameSearchResult(
        items=items,
        total_count=total_count,
        has_more=total_count > len(items),
    )
