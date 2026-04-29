"""Catalog printing lookup and summary helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from ..db.connection import connect
from ..db.schema import require_current_schema
from ..errors import NotFoundError, ValidationError
from .catalog_search import _catalog_search_row_kwargs_from_payload, _sorted_available_languages
from .normalize import (
    normalize_catalog_search_scope,
    normalize_language_code,
    normalized_catalog_finish_list,
    text_or_none,
)
from .query_catalog import catalog_scope_filter_sql
from .response_models import CatalogPrintingLookupRow, CatalogPrintingSummaryResult


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
    normal_rows = [row for row in rows if "normal" in normalized_catalog_finish_list(row["finishes_json"])]
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
