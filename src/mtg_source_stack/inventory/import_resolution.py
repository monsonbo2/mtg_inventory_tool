"""Helpers for structured import ambiguity resolution."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from .normalize import extract_image_uri_fields, normalized_catalog_finish_list, text_or_none


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


def build_resolution_options_for_catalog_row(
    row: sqlite3.Row,
) -> tuple[list[ImportResolutionOption], bool]:
    image_uri_small, image_uri_normal = extract_image_uri_fields(row["image_uris_json"])
    finishes = normalized_catalog_finish_list(row["finishes_json"])
    if not finishes:
        finishes = ["normal"]

    if "normal" in finishes:
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
