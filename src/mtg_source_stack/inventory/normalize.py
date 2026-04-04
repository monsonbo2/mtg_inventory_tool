from __future__ import annotations

import json
import re
from typing import Any

from ..errors import ValidationError
from .money import format_decimal


DEFAULT_PROVIDER = "tcgplayer"
DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 100
DEFAULT_CATALOG_SEARCH_SCOPE = "default"
CATALOG_SEARCH_SCOPES = ("default", "all")
CSV_PREVIEW_LIMIT = 25
DEFAULT_HEALTH_STALE_DAYS = 30
HEALTH_PREVIEW_LIMIT = 10
MAX_OWNED_ROWS_LIMIT = 250
DEFAULT_AUDIT_EVENT_LIMIT = 50
MAX_AUDIT_EVENT_LIMIT = 200
DEFAULT_FINISH = "normal"
DEFAULT_CONDITION_CODE = "NM"
DEFAULT_LANGUAGE_CODE = "en"
CANONICAL_FINISHES = ("normal", "foil", "etched")
ACCEPTED_FINISH_INPUTS = ("normal", "nonfoil", "foil", "etched")
CANONICAL_CONDITION_CODES = ("M", "NM", "LP", "MP", "HP", "DMG")
CANONICAL_LANGUAGE_CODES = ("en", "ja", "de", "fr", "it", "es", "pt", "ru", "ko", "zhs", "zht", "ph")
MERGED_ACQUISITION_NOTE_MARKER = "Merged source acquisition from item "
CSV_HEADER_ALIASES = {
    "inventory_slug": "inventory",
    "inventoryname": "inventory",
    "inventoryslug": "inventory",
    "collection_name": "inventory_name",
    "collection": "inventory_name",
    "created_at": "source_created_at",
    "product_id": "tcgplayer_product_id",
    "tcgplayer_id": "tcgplayer_product_id",
    "tcgplayer_product_id": "tcgplayer_product_id",
    "scryfallid": "scryfall_id",
    "card_name": "name",
    "cardname": "name",
    "product_name": "name",
    "set": "set_code",
    "setcode": "set_code",
    "set_name": "set_name",
    "collector_no": "collector_number",
    "collectornumber": "collector_number",
    "number": "collector_number",
    "printing_lang": "lang",
    "qty": "quantity",
    "condition_code": "condition",
    "cond": "condition",
    "language": "language_code",
    "languagecode": "language_code",
    "owned_language": "language_code",
    "variant": "variant",
    "total_quantity": "total_quantity",
    "add_to_quantity": "add_to_quantity",
    "tcg_marketplace_price": "marketplace_price",
    "tcg_market_price": "market_price",
    "acquisitionprice": "acquisition_price",
    "purchase_price": "acquisition_price",
    "acquisitioncurrency": "acquisition_currency",
    "currency": "acquisition_currency",
    "tag": "tags",
}


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_limit_value(
    value: int | None,
    *,
    maximum: int,
    allow_none: bool = False,
    field_name: str = "--limit",
) -> int | None:
    if value is None:
        if allow_none:
            return None
        raise ValidationError(f"{field_name} must be provided.")
    if value <= 0:
        raise ValidationError(f"{field_name} must be a positive integer.")
    if value > maximum:
        raise ValidationError(f"{field_name} cannot exceed {maximum}.")
    return value


def normalize_catalog_search_scope(value: str | None) -> str:
    text = text_or_none(value)
    if text is None:
        return DEFAULT_CATALOG_SEARCH_SCOPE
    normalized = text.lower()
    if normalized not in CATALOG_SEARCH_SCOPES:
        allowed = ", ".join(CATALOG_SEARCH_SCOPES)
        raise ValidationError(f"scope must be one of: {allowed}.")
    return normalized


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = text_or_none(value)
        if text is not None:
            return text
    return None


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def normalize_inventory_slug(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValidationError("inventory_slug is required.")
    return normalized


def slugify_inventory_name(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return slug or "inventory"


def normalize_condition_code(value: str | None) -> str:
    text = text_or_none(value)
    if text is None:
        return DEFAULT_CONDITION_CODE

    normalized = text.strip().lower()
    for suffix in (" etched foil", " foil", " etched"):
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)].strip()

    mapping = {
        "m": "M",
        "mint": "M",
        "nm": "NM",
        "near mint": "NM",
        "near-mint": "NM",
        "lp": "LP",
        "lightly played": "LP",
        "light-played": "LP",
        "slightly played": "LP",
        "sp": "LP",
        "mp": "MP",
        "moderately played": "MP",
        "moderately-played": "MP",
        "hp": "HP",
        "heavily played": "HP",
        "heavily-played": "HP",
        "dmg": "DMG",
        "damaged": "DMG",
    }
    return mapping.get(normalized, text.upper())


def normalize_language_code(value: str | None) -> str:
    text = text_or_none(value)
    if text is None:
        return DEFAULT_LANGUAGE_CODE

    normalized = text.strip().lower()
    mapping = {
        "english": "en",
        "en": "en",
        "japanese": "ja",
        "ja": "ja",
        "german": "de",
        "de": "de",
        "french": "fr",
        "fr": "fr",
        "italian": "it",
        "it": "it",
        "spanish": "es",
        "es": "es",
        "portuguese": "pt",
        "pt": "pt",
        "russian": "ru",
        "ru": "ru",
        "korean": "ko",
        "ko": "ko",
        "simplified chinese": "zhs",
        "zhs": "zhs",
        "traditional chinese": "zht",
        "zht": "zht",
        "phyrexian": "ph",
        "ph": "ph",
    }
    return mapping.get(normalized, normalized)


def normalize_currency_code(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None
    return text.upper()


def normalize_external_id(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def parse_int_value(value: str | None, *, row_number: int, field_name: str) -> int | None:
    text = text_or_none(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"CSV row {row_number}: {field_name} must be an integer.") from exc


def resolve_csv_quantity(row: dict[str, str | None], *, row_number: int) -> int | None:
    direct_quantity = parse_int_value(row.get("quantity"), row_number=row_number, field_name="quantity")
    if direct_quantity is not None:
        if direct_quantity <= 0:
            raise ValueError(f"CSV row {row_number}: quantity must be a positive integer.")
        return direct_quantity

    total_quantity = parse_int_value(row.get("total_quantity"), row_number=row_number, field_name="total_quantity")
    add_to_quantity = parse_int_value(
        row.get("add_to_quantity"),
        row_number=row_number,
        field_name="add_to_quantity",
    )
    if total_quantity is not None or add_to_quantity is not None:
        computed = max(0, (total_quantity or 0) + (add_to_quantity or 0))
        if computed == 0:
            return None
        return computed

    return 1


def finish_from_variant(variant: str | None, finish: str | None) -> str:
    explicit_finish = text_or_none(finish)
    if explicit_finish is not None:
        return explicit_finish

    variant_text = text_or_none(variant)
    if variant_text is None:
        return DEFAULT_FINISH

    lowered = variant_text.lower()
    if "etched" in lowered:
        return "etched"
    if "foil" in lowered:
        return "foil"
    return DEFAULT_FINISH


def finish_and_source_from_row(row: dict[str, str | None]) -> tuple[str, str]:
    explicit = text_or_none(row.get("finish"))
    if explicit is not None:
        return explicit, "finish"

    from_variant = finish_from_variant(row.get("variant"), None)
    if from_variant != "normal":
        return from_variant, "variant"

    condition_text = text_or_none(row.get("condition"))
    if condition_text is not None:
        lowered = condition_text.lower()
        if "etched" in lowered:
            return "etched", "condition"
        if "foil" in lowered:
            return "foil", "condition"

    return DEFAULT_FINISH, "default"


def finish_from_row(row: dict[str, str | None]) -> str:
    finish, _ = finish_and_source_from_row(row)
    return finish


def normalize_finish(value: str | None) -> str:
    normalized = (value or DEFAULT_FINISH).strip().lower()
    mapping = {
        "normal": "normal",
        "nonfoil": "normal",
        "foil": "foil",
        "etched": "etched",
    }
    if normalized not in mapping:
        raise ValidationError("Finish must be one of: normal, nonfoil, foil, etched.")
    return mapping[normalized]


def normalize_price_snapshot_finish(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None

    normalized = text.strip().lower()
    if normalized == "etched foil":
        normalized = "etched"

    try:
        return normalize_finish(normalized)
    except ValueError:
        return None


def parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [str(item) for item in parsed]
    return []


def parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def extract_image_uri_fields(value: str | None) -> tuple[str | None, str | None]:
    image_uris = parse_json_object(value)
    small = text_or_none(image_uris.get("small"))
    normal = text_or_none(image_uris.get("normal"))
    return small, normal


def normalize_tag(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None
    normalized = " ".join(text.split()).lower()
    return normalized or None


def normalize_tags(values: list[str]) -> list[str]:
    normalized_tags: list[str] = []
    for value in values:
        normalized = normalize_tag(value)
        if normalized is not None and normalized not in normalized_tags:
            normalized_tags.append(normalized)
    return normalized_tags


def parse_tags(value: str | None) -> list[str]:
    text = text_or_none(value)
    if text is None:
        return []
    return normalize_tags(text.split(","))


def load_tags_json(value: str | None) -> list[str]:
    return normalize_tags(parse_json_list(value))


def merge_tags(existing_tags: list[str], new_tags: list[str]) -> list[str]:
    return normalize_tags([*existing_tags, *new_tags])


def tags_to_json(tags: list[str]) -> str:
    return compact_json(normalize_tags(tags))


def format_tags(tags: list[str]) -> str:
    return ", ".join(tags) if tags else "(none)"


def format_finishes(finishes: list[str]) -> str:
    return ", ".join(finishes) if finishes else "(none)"


def format_optional_text(value: str | None) -> str:
    text = text_or_none(value)
    return text if text is not None else "(none)"


def format_acquisition_text(price: Any, currency: Any) -> str:
    return format_optional_text(format_acquisition_summary(price, currency))


def format_acquisition_summary(price: Any, currency: Any) -> str | None:
    if price is None:
        return None
    price_text = format_decimal(price)
    currency_text = text_or_none(currency)
    return f"{price_text} {currency_text}".strip() if currency_text else price_text


def merge_note_text(
    *,
    target_notes: str | None,
    source_notes: str | None,
) -> str | None:
    merged_parts: list[str] = []
    for note in (text_or_none(target_notes), text_or_none(source_notes)):
        if note is not None and note not in merged_parts:
            merged_parts.append(note)

    if not merged_parts:
        return None
    return "\n\n".join(merged_parts)


def parse_tag_filters(values: list[str] | None) -> list[str]:
    if not values:
        return []
    parsed: list[str] = []
    for value in values:
        parsed.extend(parse_tags(value))
    return normalize_tags(parsed)


def normalize_catalog_finishes(raw_finishes: str | None) -> str:
    return ",".join(normalized_catalog_finish_list(raw_finishes))


def normalized_catalog_finish_list(raw_finishes: str | None) -> list[str]:
    finishes: list[str] = []
    for finish in parse_json_list(raw_finishes):
        normalized = normalize_finish(finish)
        if normalized not in finishes:
            finishes.append(normalized)
    return finishes


def validate_supported_finish(raw_finishes: str | None, requested_finish: str) -> str:
    available_finishes = normalized_catalog_finish_list(raw_finishes)
    if requested_finish in available_finishes:
        return requested_finish

    available_text = ", ".join(available_finishes) if available_finishes else "(none recorded)"
    raise ValidationError(
        f"Finish '{requested_finish}' is not available for this card printing. "
        f"Available finishes: {available_text}."
    )


def truncate(value: Any, max_len: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def parse_finish_list(value: str | None) -> list[str]:
    finishes: list[str] = []
    text = text_or_none(value)
    if text is None:
        return finishes
    for part in text.split(","):
        finish = text_or_none(part)
        if finish is None:
            continue
        normalized = normalize_finish(finish)
        if normalized not in finishes:
            finishes.append(normalized)
    return finishes
