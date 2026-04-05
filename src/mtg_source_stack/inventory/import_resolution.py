"""Helpers for structured import ambiguity resolution."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from .normalize import extract_image_uri_fields, normalize_finish, normalized_catalog_finish_list, text_or_none


@dataclass(frozen=True, slots=True)
class ImportResolutionOption:
    scryfall_id: str
    finish: str
    name: str
    set_code: str
    set_name: str
    collector_number: str
    lang: str
    image_uri_small: str | None
    image_uri_normal: str | None


@dataclass(frozen=True, slots=True)
class DecklistRequestedCard:
    name: str
    quantity: int
    set_code: str | None = None
    collector_number: str | None = None
    finish: str | None = None


@dataclass(frozen=True, slots=True)
class CsvRequestedCard:
    scryfall_id: str | None
    oracle_id: str | None
    tcgplayer_product_id: str | None
    name: str | None
    quantity: int
    set_code: str | None = None
    set_name: str | None = None
    collector_number: str | None = None
    lang: str | None = None
    finish: str | None = None


@dataclass(frozen=True, slots=True)
class CsvResolutionIssue:
    kind: str
    csv_row: int
    requested: CsvRequestedCard
    options: list[ImportResolutionOption]


@dataclass(frozen=True, slots=True)
class CsvResolutionSelection:
    csv_row: int
    scryfall_id: str
    finish: str


@dataclass(frozen=True, slots=True)
class DecklistResolutionIssue:
    kind: str
    decklist_line: int
    section: str
    requested: DecklistRequestedCard
    options: list[ImportResolutionOption]


@dataclass(frozen=True, slots=True)
class DecklistResolutionSelection:
    decklist_line: int
    scryfall_id: str
    finish: str


@dataclass(frozen=True, slots=True)
class RemoteDeckRequestedCard:
    name: str | None
    quantity: int
    set_code: str | None = None
    collector_number: str | None = None
    finish: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteDeckResolutionIssue:
    kind: str
    source_position: int
    section: str
    requested: RemoteDeckRequestedCard
    options: list[ImportResolutionOption]


@dataclass(frozen=True, slots=True)
class RemoteDeckResolutionSelection:
    source_position: int
    scryfall_id: str
    finish: str


def build_resolution_options_for_catalog_row(
    row: sqlite3.Row,
    *,
    requested_finish: str | None = None,
    prefer_default_finish: bool = True,
) -> tuple[list[ImportResolutionOption], bool]:
    image_uris_json = row["image_uris_json"] if "image_uris_json" in row.keys() else None
    image_uri_small, image_uri_normal = extract_image_uri_fields(image_uris_json)
    finishes = normalized_catalog_finish_list(row["finishes_json"])
    if not finishes:
        finishes = ["normal"]

    if text_or_none(requested_finish) is not None:
        normalized_requested_finish = normalize_finish(requested_finish)
        if normalized_requested_finish not in finishes:
            raise ValueError(
                f"Requested finish '{normalized_requested_finish}' is not available for row '{row['scryfall_id']}'."
            )
        selected_finishes = [normalized_requested_finish]
        requires_choice = False
    elif not prefer_default_finish:
        selected_finishes = list(finishes)
        requires_choice = len(selected_finishes) > 1
    elif "normal" in finishes:
        selected_finishes = ["normal"]
        requires_choice = False
    elif len(finishes) == 1:
        selected_finishes = [finishes[0]]
        requires_choice = False
    else:
        selected_finishes = list(finishes)
        requires_choice = True

    base_payload = {
        "scryfall_id": str(row["scryfall_id"]),
        "name": text_or_none(row["name"]) or "",
        "set_code": text_or_none(row["set_code"]) or "",
        "set_name": text_or_none(row["set_name"]) or "",
        "collector_number": text_or_none(row["collector_number"]) or "",
        "lang": text_or_none(row["lang"]) or "",
        "image_uri_small": image_uri_small,
        "image_uri_normal": image_uri_normal,
    }
    return (
        [
            ImportResolutionOption(
                **base_payload,
                finish=finish,
            )
            for finish in selected_finishes
        ],
        requires_choice,
    )
