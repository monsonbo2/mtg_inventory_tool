"""Catalog lookup helpers for local MTG card data."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import NotFoundError, ValidationError
from .normalize import (
    CANONICAL_LANGUAGE_CODES,
    DEFAULT_SEARCH_LIMIT,
    MAX_SEARCH_LIMIT,
    extract_image_uri_fields,
    normalize_catalog_search_scope,
    normalize_finish,
    normalize_language_code,
    normalized_catalog_finish_list,
    text_or_none,
    validate_supported_finish,
    validate_limit_value,
)
from .query_catalog import add_catalog_filters, add_catalog_scope_filter, build_catalog_search_fts_query, catalog_scope_filter_sql
from .response_models import CatalogNameSearchRow, CatalogPrintingLookupRow, CatalogSearchRow


_LANGUAGE_ORDER = {code: index for index, code in enumerate(CANONICAL_LANGUAGE_CODES)}
_PREFERRED_ORACLE_DEFAULT_SET_TYPES = {
    "commander",
    "core",
    "draft_innovation",
    "expansion",
    "masters",
    "starter",
}


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


def _catalog_printing_lookup_row_from_payload(payload: Mapping[str, Any]) -> CatalogPrintingLookupRow:
    return CatalogPrintingLookupRow(
        **_catalog_search_row_kwargs_from_payload(payload),
        is_default_add_choice=bool(dict(payload).get("is_default_add_choice", False)),
    )


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


def _catalog_resolution_rows(
    connection: sqlite3.Connection,
    *,
    filters: list[str],
    params: list[Any],
) -> list[sqlite3.Row]:
    return connection.execute(
        f"""
        SELECT
            scryfall_id,
            oracle_id,
            name,
            set_code,
            set_name,
            collector_number,
            lang,
            finishes_json,
            image_uris_json,
            released_at,
            tcgplayer_product_id,
            set_type,
            booster,
            promo_types_json,
            is_default_add_searchable
        FROM mtg_cards
        WHERE {' AND '.join(filters)}
        ORDER BY
            CASE WHEN LOWER(lang) = 'en' THEN 0 ELSE 1 END,
            COALESCE(released_at, '') DESC,
            set_code,
            collector_number,
            scryfall_id
        """,
        params,
    ).fetchall()


def _candidate_rows_text(rows: list[sqlite3.Row]) -> str:
    return "; ".join(
        f"{row['set_code']} #{row['collector_number']} ({row['lang']}) [{row['scryfall_id']}]"
        for row in rows
    )


def _rows_matching_finish(rows: list[sqlite3.Row], requested_finish: str | None) -> tuple[list[sqlite3.Row], str | None]:
    requested_text = text_or_none(requested_finish)
    if requested_text is None:
        return rows, None
    normalized_finish = normalize_finish(requested_text)
    matched_rows = [
        row for row in rows if normalized_finish in normalized_catalog_finish_list(row["finishes_json"])
    ]
    return matched_rows, normalized_finish


def _row_json_text_list(row: sqlite3.Row, field_name: str) -> list[str]:
    payload = text_or_none(row[field_name])
    if payload is None:
        return []
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [normalized for normalized in (text_or_none(item) for item in value) if normalized is not None]


def _oracle_default_printing_tier(row: sqlite3.Row) -> int:
    promo_types = _row_json_text_list(row, "promo_types_json")
    set_type = text_or_none(row["set_type"])
    normalized_set_type = set_type.lower() if set_type is not None else None
    booster = bool(row["booster"])

    if not promo_types and (booster or normalized_set_type in _PREFERRED_ORACLE_DEFAULT_SET_TYPES):
        return 0
    if not promo_types:
        return 1
    return 2


def _released_at_sort_key(value: Any) -> tuple[int, int]:
    released_at = text_or_none(value)
    if released_at is None:
        return (1, 0)
    try:
        return (0, -date.fromisoformat(released_at).toordinal())
    except ValueError:
        return (0, 0)


def _oracle_default_printing_sort_key(row: sqlite3.Row, *, prefer_english: bool) -> tuple[Any, ...]:
    normalized_lang = normalize_language_code(row["lang"])
    return (
        0 if prefer_english and normalized_lang == "en" else 1,
        _oracle_default_printing_tier(row),
        *_released_at_sort_key(row["released_at"]),
        text_or_none(row["set_code"]) or "",
        text_or_none(row["collector_number"]) or "",
        str(row["scryfall_id"]),
    )


def _rank_oracle_default_printing_rows(
    rows: list[sqlite3.Row],
    *,
    prefer_english: bool,
) -> list[sqlite3.Row]:
    return sorted(
        rows,
        key=lambda row: _oracle_default_printing_sort_key(row, prefer_english=prefer_english),
    )


def _default_add_choice_row_for_printings(
    rows: list[sqlite3.Row],
    *,
    prefer_english: bool,
) -> sqlite3.Row | None:
    normal_rows, _normalized_finish = _rows_matching_finish(rows, "normal")
    if not normal_rows:
        return None
    return _rank_oracle_default_printing_rows(normal_rows, prefer_english=prefer_english)[0]


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
) -> list[CatalogNameSearchRow]:
    if not query.strip():
        raise ValidationError("query is required.")
    normalized_scope = normalize_catalog_search_scope(scope)
    validate_limit_value(limit, maximum=MAX_SEARCH_LIMIT)
    require_current_schema(db_path)
    with connect(db_path) as connection:
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
        where_params: list[Any] = []
        fts_query = build_catalog_search_fts_query(query) if not exact else None
        if exact:
            where_parts.append("LOWER(mtg_cards.name) = LOWER(?)")
            where_params.append(query)
        else:
            where_parts.append("(search_match.scryfall_id IS NOT NULL OR LOWER(mtg_cards.name) LIKE LOWER(?))")
            where_params.append(f"%{query}%")
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

        scope_filter_sql = catalog_scope_filter_sql(normalized_scope)
        add_catalog_scope_filter(where_parts, scope=normalized_scope)

        params: list[Any] = []
        if not exact and fts_query is not None:
            params.append(fts_query)
        params.extend([query, f"{query}%"])
        params.extend(where_params)
        params.append(limit)
        rows = connection.execute(
            f"""
            {search_cte},
            matched_printings AS (
                SELECT
                    mtg_cards.oracle_id,
                    CASE
                        WHEN LOWER(mtg_cards.name) = LOWER(?) THEN 0
                        WHEN LOWER(mtg_cards.name) LIKE LOWER(?) THEN 1
                        WHEN search_match.scryfall_id IS NOT NULL THEN 2
                        ELSE 3
                    END AS match_order,
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
                    MIN(CASE WHEN edhrec_rank IS NULL THEN 1 ELSE 0 END) AS edhrec_rank_missing,
                    MIN(edhrec_rank) AS best_edhrec_rank,
                    MIN(search_rank) AS best_search_rank
                FROM matched_printings
                GROUP BY oracle_id
            ),
            group_counts AS (
                SELECT
                    oracle_id,
                    COUNT(*) AS printings_count
                FROM mtg_cards
                WHERE oracle_id IN (SELECT oracle_id FROM matched_groups)
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
                INNER JOIN matched_groups ON matched_groups.oracle_id = mtg_cards.oracle_id
                WHERE {scope_filter_sql}
            )
            SELECT
                representative_rows.oracle_id,
                representative_rows.name,
                representative_rows.image_uris_json,
                representative_rows.released_at,
                group_counts.printings_count
            FROM matched_groups
            INNER JOIN representative_rows ON representative_rows.oracle_id = matched_groups.oracle_id
            INNER JOIN group_counts ON group_counts.oracle_id = matched_groups.oracle_id
            WHERE representative_rows.row_number = 1
            ORDER BY
                matched_groups.match_order,
                matched_groups.edhrec_rank_missing,
                COALESCE(matched_groups.best_edhrec_rank, 2147483647),
                matched_groups.best_search_rank,
                LOWER(representative_rows.name),
                COALESCE(representative_rows.released_at, '') DESC,
                representative_rows.oracle_id
            LIMIT ?
            """,
            params,
        ).fetchall()
        if not rows:
            return []

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

    results: list[CatalogNameSearchRow] = []
    for row in rows:
        image_uri_small, image_uri_normal = extract_image_uri_fields(row["image_uris_json"])
        results.append(
            CatalogNameSearchRow(
                oracle_id=row["oracle_id"],
                name=row["name"],
                printings_count=row["printings_count"],
                available_languages=_sorted_available_languages(languages_by_oracle.get(row["oracle_id"], [])),
                image_uri_small=image_uri_small,
                image_uri_normal=image_uri_normal,
            )
        )
    return results


def list_card_printings_for_oracle(
    db_path: str | Path,
    oracle_id: str,
    *,
    lang: str | None = None,
    scope: str | None = None,
) -> list[CatalogPrintingLookupRow]:
    oracle_id_text = text_or_none(oracle_id)
    if oracle_id_text is None:
        raise ValidationError("oracle_id is required.")
    requested_lang = text_or_none(lang)
    normalized_scope = normalize_catalog_search_scope(scope)
    scope_filter_sql = catalog_scope_filter_sql(normalized_scope)
    require_current_schema(db_path)
    with connect(db_path) as connection:
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
                tcgplayer_product_id,
                image_uris_json,
                released_at,
                set_type,
                booster,
                promo_types_json
            FROM mtg_cards
            WHERE oracle_id = ?
              AND {scope_filter_sql}
            ORDER BY
                COALESCE(released_at, '') DESC,
                CASE WHEN LOWER(lang) = 'en' THEN 0 ELSE 1 END,
                set_code,
                collector_number,
                scryfall_id
            """,
            (oracle_id_text,),
        ).fetchall()
    if not rows:
        raise NotFoundError(f"No printings found for oracle_id '{oracle_id_text}'.")

    if requested_lang is None:
        english_rows = [row for row in rows if normalize_language_code(row["lang"]) == "en"]
        selected_rows = english_rows or rows
    elif requested_lang.lower() == "all":
        selected_rows = rows
    else:
        normalized_lang = normalize_language_code(requested_lang)
        selected_rows = [row for row in rows if normalize_language_code(row["lang"]) == normalized_lang]
    prefer_english = requested_lang is None or requested_lang.lower() == "all"
    ranked_rows = _rank_oracle_default_printing_rows(
        selected_rows,
        prefer_english=prefer_english,
    )
    default_choice = _default_add_choice_row_for_printings(
        selected_rows,
        prefer_english=prefer_english,
    )
    default_choice_id = str(default_choice["scryfall_id"]) if default_choice is not None else None

    return [
        _catalog_printing_lookup_row_from_payload(
            {
                **dict(row),
                "is_default_add_choice": str(row["scryfall_id"]) == default_choice_id,
            }
        )
        for row in ranked_rows
    ]


def list_default_card_name_candidate_rows(
    connection: sqlite3.Connection,
    *,
    name: str,
    lang: str | None = None,
    finish: str | None = None,
) -> list[sqlite3.Row]:
    name_text = text_or_none(name)
    if name_text is None:
        raise ValidationError("name is required.")

    normalized_lang = normalize_language_code(lang) if text_or_none(lang) is not None else None
    filters = ["LOWER(name) = LOWER(?)", "COALESCE(is_default_add_searchable, 1) = 1"]
    params: list[Any] = [name_text]
    if normalized_lang is not None:
        filters.append("LOWER(lang) = LOWER(?)")
        params.append(normalized_lang)

    rows = _catalog_resolution_rows(connection, filters=filters, params=params)
    if not rows:
        raise NotFoundError(
            "No matching default-add card found. Try an exact printing import with set code and collector number."
        )

    rows, normalized_finish = _rows_matching_finish(rows, finish)
    if normalized_finish is not None and not rows:
        raise ValidationError(
            f"No matching default-add card found for name '{name_text}' with finish '{normalized_finish}'."
        )
    return rows


def list_printing_candidate_rows(
    connection: sqlite3.Connection,
    *,
    name: str,
    set_code: str | None,
    set_name: str | None = None,
    collector_number: str | None,
    lang: str | None,
    finish: str | None = None,
) -> list[sqlite3.Row]:
    name_text = text_or_none(name)
    if name_text is None:
        raise ValidationError("name is required.")

    normalized_lang = normalize_language_code(lang) if text_or_none(lang) is not None else None
    params: list[Any] = [name_text]
    filters = ["LOWER(name) = LOWER(?)"]
    if set_code:
        filters.append("LOWER(set_code) = LOWER(?)")
        params.append(set_code)
    if set_name:
        filters.append("LOWER(set_name) = LOWER(?)")
        params.append(set_name)
    if collector_number:
        filters.append("collector_number = ?")
        params.append(collector_number)
    if normalized_lang:
        filters.append("LOWER(lang) = LOWER(?)")
        params.append(normalized_lang)

    rows = _catalog_resolution_rows(connection, filters=filters, params=params)
    if not rows:
        raise NotFoundError("No matching printing found. Try search-cards first to find the exact printing.")

    rows, normalized_finish = _rows_matching_finish(rows, finish)
    if normalized_finish is not None and not rows:
        raise ValidationError(
            f"No matching printing found for name '{name_text}' with finish '{normalized_finish}'."
        )
    return rows


def list_tcgplayer_product_candidate_rows(
    connection: sqlite3.Connection,
    *,
    tcgplayer_product_id: str,
    finish: str | None = None,
) -> list[sqlite3.Row]:
    product_id = text_or_none(tcgplayer_product_id)
    if product_id is None:
        raise ValidationError("tcgplayer_product_id is required.")

    rows = _catalog_resolution_rows(
        connection,
        filters=["tcgplayer_product_id = ?"],
        params=[product_id],
    )
    if not rows:
        raise NotFoundError(f"No card found for tcgplayer_product_id '{product_id}'.")

    rows, normalized_finish = _rows_matching_finish(rows, finish)
    if normalized_finish is not None and not rows:
        raise ValidationError(
            f"No card found for tcgplayer_product_id '{product_id}' with finish '{normalized_finish}'."
        )
    return rows


def resolve_default_card_row_for_name(
    connection: sqlite3.Connection,
    *,
    name: str,
    lang: str | None = None,
    finish: str | None = None,
) -> sqlite3.Row:
    name_text = text_or_none(name)
    if name_text is None:
        raise ValidationError("name is required.")

    normalized_lang = normalize_language_code(lang) if text_or_none(lang) is not None else None
    rows = list_default_card_name_candidate_rows(
        connection,
        name=name_text,
        lang=normalized_lang,
        finish=finish,
    )

    oracle_ids = {str(row["oracle_id"]) for row in rows}
    if len(oracle_ids) != 1:
        raise ValidationError(
            "Multiple cards matched that exact name. "
            "Narrow it with set code and collector number. "
            f"Candidates: {_candidate_rows_text(rows)}"
        )

    return resolve_card_row(
        connection,
        scryfall_id=None,
        oracle_id=next(iter(oracle_ids)),
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=normalized_lang,
        finish=finish,
    )


def determine_printing_selection_mode(
    connection: sqlite3.Connection,
    *,
    scryfall_id: str | None,
    oracle_id: str | None = None,
    tcgplayer_product_id: str | None = None,
    name: str | None,
    set_code: str | None,
    set_name: str | None = None,
    collector_number: str | None,
    lang: str | None,
    finish: str | None = None,
) -> str:
    if text_or_none(scryfall_id) is not None:
        return "explicit"
    if text_or_none(tcgplayer_product_id) is not None:
        return "explicit"

    normalized_lang = normalize_language_code(lang) if text_or_none(lang) is not None else None

    if text_or_none(oracle_id) is not None:
        filters = ["oracle_id = ?", "COALESCE(is_default_add_searchable, 1) = 1"]
        params: list[Any] = [oracle_id]
        if set_code:
            filters.append("LOWER(set_code) = LOWER(?)")
            params.append(set_code)
        if set_name:
            filters.append("LOWER(set_name) = LOWER(?)")
            params.append(set_name)
        if collector_number:
            filters.append("collector_number = ?")
            params.append(collector_number)
        if normalized_lang:
            filters.append("LOWER(lang) = LOWER(?)")
            params.append(normalized_lang)

        rows = _catalog_resolution_rows(connection, filters=filters, params=params)
        if not rows:
            raise NotFoundError(f"No printing found for oracle_id '{oracle_id}'.")

        rows, normalized_finish = _rows_matching_finish(rows, finish)
        if normalized_finish is not None and not rows:
            raise ValidationError(
                f"No printing found for oracle_id '{oracle_id}' with finish '{normalized_finish}'."
            )
        return "explicit" if len(rows) == 1 else "defaulted"

    name_text = text_or_none(name)
    if name_text is None:
        raise ValidationError("Provide either --scryfall-id, --oracle-id, --tcgplayer-product-id, or --name.")

    if set_code or set_name or collector_number:
        list_printing_candidate_rows(
            connection,
            name=name_text,
            set_code=set_code,
            set_name=set_name,
            collector_number=collector_number,
            lang=normalized_lang,
            finish=finish,
        )
        return "explicit"

    rows = list_default_card_name_candidate_rows(
        connection,
        name=name_text,
        lang=normalized_lang,
        finish=finish,
    )
    oracle_ids = {str(row["oracle_id"]) for row in rows}
    if len(oracle_ids) != 1:
        raise ValidationError(
            "Multiple cards matched that exact name. "
            "Narrow it with set code and collector number. "
            f"Candidates: {_candidate_rows_text(rows)}"
        )
    return "explicit" if len(rows) == 1 else "defaulted"


def resolve_card_row(
    connection: sqlite3.Connection,
    *,
    scryfall_id: str | None,
    oracle_id: str | None = None,
    tcgplayer_product_id: str | None,
    name: str | None,
    set_code: str | None,
    set_name: str | None = None,
    collector_number: str | None,
    lang: str | None,
    finish: str | None = None,
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
        if text_or_none(finish) is not None:
            validate_supported_finish(row["finishes_json"], normalize_finish(finish))
        return row

    if tcgplayer_product_id:
        rows = _catalog_resolution_rows(
            connection,
            filters=["tcgplayer_product_id = ?"],
            params=[tcgplayer_product_id],
        )
        if not rows:
            raise NotFoundError(f"No card found for tcgplayer_product_id '{tcgplayer_product_id}'.")
        rows, normalized_finish = _rows_matching_finish(rows, finish)
        if normalized_finish is not None and not rows:
            raise ValidationError(
                f"No card found for tcgplayer_product_id '{tcgplayer_product_id}' with finish '{normalized_finish}'."
            )
        if len(rows) > 1:
            raise ValidationError(
                "Multiple printings matched that TCGplayer product id. "
                "Narrow it with --scryfall-id or provide name/set details."
            )
        return rows[0]

    normalized_lang = normalize_language_code(lang) if text_or_none(lang) is not None else None

    if oracle_id:
        filters = ["oracle_id = ?"]
        params: list[Any] = [oracle_id]
        filters.append("COALESCE(is_default_add_searchable, 1) = 1")
        if set_code:
            filters.append("LOWER(set_code) = LOWER(?)")
            params.append(set_code)
        if set_name:
            filters.append("LOWER(set_name) = LOWER(?)")
            params.append(set_name)
        if collector_number:
            filters.append("collector_number = ?")
            params.append(collector_number)
        if normalized_lang:
            filters.append("LOWER(lang) = LOWER(?)")
            params.append(normalized_lang)

        rows = _catalog_resolution_rows(connection, filters=filters, params=params)
        if not rows:
            raise NotFoundError(
                f"No printing found for oracle_id '{oracle_id}'."
            )
        rows, normalized_finish = _rows_matching_finish(rows, finish)
        if normalized_finish is not None and not rows:
            raise ValidationError(
                f"No printing found for oracle_id '{oracle_id}' with finish '{normalized_finish}'."
            )
        ranked_rows = _rank_oracle_default_printing_rows(
            rows,
            prefer_english=normalized_lang is None,
        )
        return ranked_rows[0]

    if not name:
        raise ValidationError("Provide either --scryfall-id, --oracle-id, --tcgplayer-product-id, or --name.")

    rows = list_printing_candidate_rows(
        connection,
        name=name,
        set_code=set_code,
        set_name=set_name,
        collector_number=collector_number,
        lang=normalized_lang,
        finish=finish,
    )
    if len(rows) > 1:
        raise ValidationError(
            "Multiple printings matched that name. Narrow it with --set-code, --collector-number, or --scryfall-id. "
            f"Candidates: {_candidate_rows_text(rows)}"
        )
    return rows[0]
