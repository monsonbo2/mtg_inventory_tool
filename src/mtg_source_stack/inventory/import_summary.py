"""Helpers for additive import summary metadata."""

from __future__ import annotations

from typing import Any, Mapping

from .normalize import text_or_none


def build_import_summary(imported_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    total_card_quantity = 0
    distinct_card_names: set[str] = set()
    distinct_printings: set[str] = set()
    section_card_quantities: dict[str, int] = {}

    for row in imported_rows:
        quantity = int(row.get("quantity") or 0)
        total_card_quantity += quantity

        card_name = text_or_none(row.get("card_name"))
        if card_name is not None:
            distinct_card_names.add(card_name.casefold())

        scryfall_id = text_or_none(row.get("scryfall_id"))
        if scryfall_id is not None:
            distinct_printings.add(scryfall_id)

        section = text_or_none(row.get("section"))
        if section is not None:
            section_card_quantities[section] = section_card_quantities.get(section, 0) + quantity

    summary: dict[str, Any] = {
        "total_card_quantity": total_card_quantity,
        "distinct_card_names": len(distinct_card_names),
        "distinct_printings": len(distinct_printings),
    }
    if section_card_quantities:
        summary["section_card_quantities"] = section_card_quantities
    return summary


def build_resolvable_import_summary(
    imported_rows: list[Mapping[str, Any]],
    *,
    requested_card_quantity: int,
) -> dict[str, Any]:
    summary = build_import_summary(imported_rows)
    imported_quantity = int(summary["total_card_quantity"])
    summary["requested_card_quantity"] = requested_card_quantity
    summary["unresolved_card_quantity"] = max(requested_card_quantity - imported_quantity, 0)
    return summary


def build_resolvable_deck_import_summary(
    imported_rows: list[Mapping[str, Any]],
    *,
    requested_card_quantity: int,
) -> dict[str, Any]:
    summary = build_resolvable_import_summary(
        imported_rows,
        requested_card_quantity=requested_card_quantity,
    )
    summary.setdefault("section_card_quantities", {})
    return summary
