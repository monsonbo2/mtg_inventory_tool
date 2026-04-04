"""CSV export profile registry for inventory exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..errors import ValidationError
from .normalize import format_tags, text_or_none


OwnedExportRowBuilder = Callable[[list[dict[str, Any]], str, str], list[dict[str, Any]]]


DEFAULT_EXPORT_CSV_FIELDNAMES = (
    "inventory",
    "provider",
    "item_id",
    "scryfall_id",
    "card_name",
    "set_code",
    "set_name",
    "collector_number",
    "rarity",
    "quantity",
    "condition_code",
    "finish",
    "language_code",
    "location",
    "tags",
    "notes",
    "acquisition_price",
    "acquisition_currency",
    "unit_price",
    "price_currency",
    "est_value",
    "price_date",
)


@dataclass(frozen=True, slots=True)
class CsvExportProfile:
    key: str
    filename_suffix: str
    fieldnames: tuple[str, ...]
    build_rows: OwnedExportRowBuilder


def _build_default_export_rows(
    rows: list[dict[str, Any]],
    inventory_slug: str,
    provider: str,
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for row in rows:
        flattened.append(
            {
                "inventory": inventory_slug,
                "provider": provider,
                "item_id": row["item_id"],
                "scryfall_id": row["scryfall_id"],
                "card_name": row["name"],
                "set_code": row["set_code"],
                "set_name": row["set_name"],
                "collector_number": row["collector_number"],
                "rarity": row["rarity"],
                "quantity": row["quantity"],
                "condition_code": row["condition_code"],
                "finish": row["finish"],
                "language_code": row["language_code"],
                "location": text_or_none(row["location"]) or "",
                "tags": format_tags(row.get("tags", [])),
                "notes": text_or_none(row["notes"]) or "",
                "acquisition_price": row["acquisition_price"] if row["acquisition_price"] is not None else "",
                "acquisition_currency": text_or_none(row["acquisition_currency"]) or "",
                "unit_price": row["unit_price"] if row["unit_price"] is not None else "",
                "price_currency": text_or_none(row["currency"]) or "",
                "est_value": row["est_value"] if row["est_value"] is not None else "",
                "price_date": text_or_none(row["price_date"]) or "",
            }
        )
    return flattened


CSV_EXPORT_PROFILES: dict[str, CsvExportProfile] = {
    "default": CsvExportProfile(
        key="default",
        filename_suffix="default",
        fieldnames=DEFAULT_EXPORT_CSV_FIELDNAMES,
        build_rows=_build_default_export_rows,
    ),
}


def supported_csv_export_profiles() -> list[str]:
    return list(CSV_EXPORT_PROFILES)


def get_csv_export_profile(profile: str | None) -> CsvExportProfile:
    normalized = (profile or "default").strip().lower()
    if not normalized:
        normalized = "default"
    resolved = CSV_EXPORT_PROFILES.get(normalized)
    if resolved is None:
        accepted = ", ".join(supported_csv_export_profiles())
        raise ValidationError(f"csv export profile must be one of: {accepted}.")
    return resolved


def build_inventory_export_filename(inventory_slug: str, profile: str | None) -> str:
    resolved = get_csv_export_profile(profile)
    return f"{inventory_slug}-{resolved.filename_suffix}-export.csv"
