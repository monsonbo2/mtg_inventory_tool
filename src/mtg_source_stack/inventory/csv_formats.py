"""CSV source-format detection and row normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .normalize import text_or_none

GENERIC_CSV_FORMAT = "generic_csv"
TCGPLAYER_LEGACY_COLLECTION_CSV_FORMAT = "tcgplayer_legacy_collection_csv"
TCGPLAYER_APP_COLLECTION_CSV_FORMAT = "tcgplayer_app_collection_csv"

CsvRow = dict[str, str | None]
CsvRowNormalizer = Callable[[CsvRow], CsvRow]


@dataclass(frozen=True, slots=True)
class CsvImportFormatAdapter:
    key: str
    matches: Callable[[set[str]], bool]
    normalize_row: CsvRowNormalizer


def _identity_row(row: CsvRow) -> CsvRow:
    return dict(row)


def _normalize_tcgplayer_finish(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None

    normalized = " ".join(text.strip().lower().replace("-", " ").split())
    mapping = {
        "normal": "normal",
        "non foil": "nonfoil",
        "nonfoil": "nonfoil",
        "standard": "normal",
        "foil": "foil",
        "traditional foil": "foil",
        "etched": "etched",
        "etched foil": "etched",
    }
    return mapping.get(normalized, normalized.replace(" ", ""))


def _normalize_tcgplayer_collection_row(row: CsvRow) -> CsvRow:
    normalized = dict(row)

    if text_or_none(normalized.get("collector_number")) is None:
        for source_key in ("card_number", "number_in_set"):
            source_value = text_or_none(normalized.get(source_key))
            if source_value is not None:
                normalized["collector_number"] = source_value
                break

    if text_or_none(normalized.get("finish")) is None:
        normalized_finish = _normalize_tcgplayer_finish(normalized.get("printing"))
        if normalized_finish is not None:
            normalized["finish"] = normalized_finish

    return normalized


def _matches_tcgplayer_legacy_collection(headers: set[str]) -> bool:
    return {
        "inventory_name",
        "tcgplayer_product_id",
        "condition",
        "language_code",
        "variant",
        "quantity",
    }.issubset(headers)


def _matches_tcgplayer_app_collection(headers: set[str]) -> bool:
    if not {"tcgplayer_product_id", "quantity", "printing"}.issubset(headers):
        return False
    return bool(
        {
            "name",
            "condition",
            "language_code",
            "inventory_name",
            "list_name",
            "set_code",
            "card_number",
            "collector_number",
        }
        & headers
    )


_CSV_IMPORT_FORMAT_ADAPTERS = (
    CsvImportFormatAdapter(
        key=TCGPLAYER_LEGACY_COLLECTION_CSV_FORMAT,
        matches=_matches_tcgplayer_legacy_collection,
        normalize_row=_normalize_tcgplayer_collection_row,
    ),
    CsvImportFormatAdapter(
        key=TCGPLAYER_APP_COLLECTION_CSV_FORMAT,
        matches=_matches_tcgplayer_app_collection,
        normalize_row=_normalize_tcgplayer_collection_row,
    ),
)


def detect_csv_import_format(normalized_headers: set[str]) -> CsvImportFormatAdapter | None:
    for adapter in _CSV_IMPORT_FORMAT_ADAPTERS:
        if adapter.matches(normalized_headers):
            return adapter
    return None
