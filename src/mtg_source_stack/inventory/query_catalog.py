"""Catalog-focused SQL filter helpers."""

from __future__ import annotations

from typing import Any

from .normalize import normalize_finish


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
            finish_parts.append("LOWER(finishes_json) LIKE ?")
            params.append(f'%"{token.lower()}"%')
        where_parts.append("(" + " OR ".join(finish_parts) + ")")
