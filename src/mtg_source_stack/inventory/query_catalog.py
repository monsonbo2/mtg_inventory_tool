"""Catalog-focused SQL filter helpers."""

from __future__ import annotations

import re
from typing import Any

from .normalize import normalize_finish

FTS_TOKEN_RE = re.compile(r"[0-9A-Za-z]+")


def build_catalog_finish_filter(normalized_finish: str) -> tuple[str, ...]:
    if normalized_finish == "normal":
        return ("normal", "nonfoil")
    return (normalized_finish,)


def add_catalog_filters(
    where_parts: list[str],
    params: list[Any],
    *,
    set_code: str | None,
    rarity: str | None,
    finish: str | None,
    lang: str | None,
) -> None:
    if set_code:
        where_parts.append("LOWER(set_code) = LOWER(?)")
        params.append(set_code)

    if rarity:
        where_parts.append("LOWER(COALESCE(rarity, '')) = LOWER(?)")
        params.append(rarity)

    if lang:
        where_parts.append("LOWER(lang) = LOWER(?)")
        params.append(lang)

    if finish:
        tokens = build_catalog_finish_filter(normalize_finish(finish))
        finish_parts = []
        for token in tokens:
            finish_parts.append(
                """
                EXISTS (
                    SELECT 1
                    FROM json_each(COALESCE(finishes_json, '[]')) finish_value
                    WHERE LOWER(finish_value.value) = LOWER(?)
                )
                """.strip()
            )
            params.append(token)
        where_parts.append("(" + " OR ".join(finish_parts) + ")")


def catalog_scope_filter_sql(scope: str, *, table_name: str = "mtg_cards") -> str:
    if scope == "default":
        return f"COALESCE({table_name}.is_default_add_searchable, 1) = 1"
    if scope == "all":
        return "1 = 1"
    raise ValueError(f"Unsupported catalog scope: {scope}")


def add_catalog_scope_filter(where_parts: list[str], *, scope: str, table_name: str = "mtg_cards") -> None:
    where_parts.append(catalog_scope_filter_sql(scope, table_name=table_name))


def build_catalog_search_fts_query(query: str) -> str | None:
    tokens = [token.lower() for token in FTS_TOKEN_RE.findall(query)]
    if not tokens:
        return None
    return " AND ".join(f"{token}*" for token in tokens)
