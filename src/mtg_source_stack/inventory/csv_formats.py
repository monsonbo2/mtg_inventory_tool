"""CSV source-format detection and row normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .normalize import text_or_none

GENERIC_CSV_FORMAT = "generic_csv"
TCGPLAYER_LEGACY_COLLECTION_CSV_FORMAT = "tcgplayer_legacy_collection_csv"
TCGPLAYER_APP_COLLECTION_CSV_FORMAT = "tcgplayer_app_collection_csv"
MANABOX_COLLECTION_CSV_FORMAT = "manabox_collection_csv"
MTGGOLDFISH_COLLECTION_CSV_FORMAT = "mtggoldfish_collection_csv"

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


def _normalize_manabox_finish(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None

    normalized = " ".join(text.strip().lower().replace("-", " ").split())
    mapping = {
        "foil": "foil",
        "true": "foil",
        "yes": "foil",
        "y": "foil",
        "1": "foil",
        "etched": "etched",
        "etched foil": "etched",
        "nonfoil": "normal",
        "non foil": "normal",
        "normal": "normal",
        "false": "normal",
        "no": "normal",
        "n": "normal",
        "0": "normal",
    }
    return mapping.get(normalized)


def _csv_flag_enabled(value: str | None) -> bool:
    text = text_or_none(value)
    if text is None:
        return False
    normalized = " ".join(text.strip().lower().replace("-", " ").split())
    return normalized in {"true", "yes", "y", "1", "foil", "etched", "etched foil"}


def _merge_csv_tags(existing_tags: str | None, *new_tags: str) -> str | None:
    normalized_tags: list[str] = []
    for raw_value in (existing_tags, *new_tags):
        text = text_or_none(raw_value)
        if text is None:
            continue
        for piece in text.split(","):
            normalized = text_or_none(piece)
            if normalized is None:
                continue
            tag = normalized.lower()
            if tag not in normalized_tags:
                normalized_tags.append(tag)
    if not normalized_tags:
        return None
    return ", ".join(normalized_tags)


def _normalize_manabox_collection_row(row: CsvRow) -> CsvRow:
    normalized = dict(row)

    if text_or_none(normalized.get("collector_number")) is None:
        for source_key in ("card_number", "number_in_set"):
            source_value = text_or_none(normalized.get(source_key))
            if source_value is not None:
                normalized["collector_number"] = source_value
                break

    if text_or_none(normalized.get("finish")) is None:
        normalized_finish = _normalize_manabox_finish(normalized.get("foil"))
        if normalized_finish is not None:
            normalized["finish"] = normalized_finish

    if text_or_none(normalized.get("acquisition_price")) is not None:
        purchase_currency = text_or_none(normalized.get("purchase_currency"))
        if (
            purchase_currency is not None
            and text_or_none(normalized.get("acquisition_currency")) is None
        ):
            normalized["acquisition_currency"] = purchase_currency

    derived_tags: list[str] = []
    if _csv_flag_enabled(normalized.get("misprint")):
        derived_tags.append("misprint")
    if _csv_flag_enabled(normalized.get("altered")):
        derived_tags.append("altered")
    if derived_tags:
        normalized["tags"] = _merge_csv_tags(normalized.get("tags"), *derived_tags)

    return normalized


def _normalize_mtggoldfish_finish(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return "normal"

    normalized = " ".join(text.strip().lower().replace("-", " ").replace("_", " ").split())
    mapping = {
        "": "normal",
        "regular": "normal",
        "nonfoil": "normal",
        "non foil": "normal",
        "foil": "foil",
        "foil etched": "etched",
        "etched foil": "etched",
    }
    return mapping.get(normalized)


def _normalize_mtggoldfish_collection_row(row: CsvRow) -> CsvRow:
    normalized = dict(row)

    if text_or_none(normalized.get("name")) is None:
        card_name = text_or_none(normalized.get("card"))
        if card_name is not None:
            normalized["name"] = card_name

    if text_or_none(normalized.get("set_name")) is None:
        edition_name = text_or_none(normalized.get("edition"))
        if edition_name is not None:
            normalized["set_name"] = edition_name

    if text_or_none(normalized.get("collector_number")) is None:
        for source_key in ("card_number", "number_in_set"):
            source_value = text_or_none(normalized.get(source_key))
            if source_value is not None:
                normalized["collector_number"] = source_value
                break

    if text_or_none(normalized.get("finish")) is None:
        normalized_finish = _normalize_mtggoldfish_finish(normalized.get("foil"))
        if normalized_finish is not None:
            normalized["finish"] = normalized_finish

    # MTGGoldfish documents that Set ID uses MTGO-specific set codes which can
    # differ from broader ecosystem codes. Prefer Set Name for resolution when
    # present so direct uploads do not fail on those mismatches.
    if text_or_none(normalized.get("set_name")) is None and text_or_none(normalized.get("set_code")) is None:
        set_id = text_or_none(normalized.get("set_id"))
        if set_id is not None:
            normalized["set_code"] = set_id

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


def _matches_manabox_collection(headers: set[str]) -> bool:
    if "quantity" not in headers or "foil" not in headers:
        return False
    if not {"name", "scryfall_id"} & headers:
        return False
    if not {"set_code", "set_name", "card_number", "collector_number", "scryfall_id"} & headers:
        return False
    return bool(
        {
            "misprint",
            "altered",
            "purchase_currency",
            "binder_name",
            "list_name",
            "binder_list_name",
        }
        & headers
    )


def _matches_mtggoldfish_collection(headers: set[str]) -> bool:
    if not {"card", "quantity", "foil"}.issubset(headers):
        return False
    return bool({"set_id", "set_name", "edition"} & headers)


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
    CsvImportFormatAdapter(
        key=MANABOX_COLLECTION_CSV_FORMAT,
        matches=_matches_manabox_collection,
        normalize_row=_normalize_manabox_collection_row,
    ),
    CsvImportFormatAdapter(
        key=MTGGOLDFISH_COLLECTION_CSV_FORMAT,
        matches=_matches_mtggoldfish_collection,
        normalize_row=_normalize_mtggoldfish_collection_row,
    ),
)


def detect_csv_import_format(normalized_headers: set[str]) -> CsvImportFormatAdapter | None:
    for adapter in _CSV_IMPORT_FORMAT_ADAPTERS:
        if adapter.matches(normalized_headers):
            return adapter
    return None
