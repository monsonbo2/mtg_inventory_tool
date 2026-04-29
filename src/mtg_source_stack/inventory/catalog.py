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
from .catalog_search import (
    _catalog_search_row_kwargs_from_payload,
    _sorted_available_languages,
    search_card_names,
    search_cards,
)
from .normalize import (
    normalize_catalog_search_scope,
    normalize_finish,
    normalize_language_code,
    normalized_catalog_finish_list,
    text_or_none,
    validate_supported_finish,
)
from .query_catalog import catalog_scope_filter_sql
from .response_models import (
    CatalogPrintingLookupRow,
    CatalogPrintingSummaryResult,
)


_PREFERRED_ORACLE_DEFAULT_SET_TYPES = {
    "commander",
    "core",
    "draft_innovation",
    "expansion",
    "masters",
    "starter",
}


def _catalog_printing_lookup_row_from_payload(payload: Mapping[str, Any]) -> CatalogPrintingLookupRow:
    return CatalogPrintingLookupRow(
        **_catalog_search_row_kwargs_from_payload(payload),
        is_default_add_choice=bool(dict(payload).get("is_default_add_choice", False)),
    )


def _catalog_printing_lookup_rows_from_ranked_payloads(
    rows: list[sqlite3.Row],
    *,
    default_choice_id: str | None,
) -> list[CatalogPrintingLookupRow]:
    return [
        _catalog_printing_lookup_row_from_payload(
            {
                **dict(row),
                "is_default_add_choice": str(row["scryfall_id"]) == default_choice_id,
            }
        )
        for row in rows
    ]


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


def _load_oracle_printing_rows(
    connection: sqlite3.Connection,
    *,
    oracle_id_text: str,
    scope_filter_sql: str,
) -> list[sqlite3.Row]:
    return connection.execute(
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
        rows = _load_oracle_printing_rows(
            connection,
            oracle_id_text=oracle_id_text,
            scope_filter_sql=scope_filter_sql,
        )
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

    return _catalog_printing_lookup_rows_from_ranked_payloads(
        ranked_rows,
        default_choice_id=default_choice_id,
    )


def summarize_card_printings_for_oracle(
    db_path: str | Path,
    oracle_id: str,
    *,
    scope: str | None = None,
) -> CatalogPrintingSummaryResult:
    oracle_id_text = text_or_none(oracle_id)
    if oracle_id_text is None:
        raise ValidationError("oracle_id is required.")
    normalized_scope = normalize_catalog_search_scope(scope)
    scope_filter_sql = catalog_scope_filter_sql(normalized_scope)
    require_current_schema(db_path)
    with connect(db_path) as connection:
        rows = _load_oracle_printing_rows(
            connection,
            oracle_id_text=oracle_id_text,
            scope_filter_sql=scope_filter_sql,
        )
    if not rows:
        raise NotFoundError(f"No printings found for oracle_id '{oracle_id_text}'.")

    english_rows = [row for row in rows if normalize_language_code(row["lang"]) == "en"]
    primary_rows = english_rows or rows
    ranked_primary_rows = _rank_oracle_default_printing_rows(
        primary_rows,
        prefer_english=True,
    )
    default_choice = _default_add_choice_row_for_printings(
        primary_rows,
        prefer_english=True,
    )
    default_choice_id = str(default_choice["scryfall_id"]) if default_choice is not None else None
    printings = _catalog_printing_lookup_rows_from_ranked_payloads(
        ranked_primary_rows,
        default_choice_id=default_choice_id,
    )
    default_printing = next((row for row in printings if row.is_default_add_choice), None)

    return CatalogPrintingSummaryResult(
        oracle_id=oracle_id_text,
        default_printing=default_printing,
        available_languages=_sorted_available_languages([row["lang"] for row in rows]),
        printings_count=len(rows),
        has_more_printings=len(rows) > len(primary_rows),
        printings=printings,
    )


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
            SELECT scryfall_id, oracle_id, name, set_code, set_name, collector_number, lang, finishes_json
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
