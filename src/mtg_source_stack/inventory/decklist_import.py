"""Decklist parsing helpers for pasted text imports."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable

from ..errors import ValidationError
from .catalog import resolve_card_row, resolve_default_card_row_for_name
from ..db.connection import connect
from ..db.schema import initialize_database
from .csv_import import InventoryValidator, PendingImportRow, _import_pending_rows
from .normalize import DEFAULT_CONDITION_CODE, DEFAULT_FINISH, text_or_none


_DEFAULT_SECTION = "mainboard"
_SECTION_ALIASES = {
    "deck": _DEFAULT_SECTION,
    "main": _DEFAULT_SECTION,
    "mainboard": _DEFAULT_SECTION,
    "main deck": _DEFAULT_SECTION,
    "maindeck": _DEFAULT_SECTION,
    "sideboard": "sideboard",
    "side board": "sideboard",
    "commander": "commander",
    "commanders": "commander",
    "companion": "companion",
    "maybeboard": "maybeboard",
}
_SECTION_PREFIX_ALIASES = {
    "sb": "sideboard",
    "sideboard": "sideboard",
}
_NAMED_SECTION_PREFIX_ALIASES = {
    "commander": "commander",
    "companion": "companion",
}
_PARENTHESIZED_COUNT_RE = re.compile(r"\s*\(\d+\)\s*$")
_QUANTITY_LINE_RE = re.compile(
    r"^(?P<quantity>\d+)(?:\s*x)?\s+(?P<body>.+?)$",
    re.IGNORECASE,
)
_PREFIXED_LINE_RE = re.compile(
    r"^(?P<prefix>[A-Za-z ]+):\s*(?P<body>.+?)$",
    re.IGNORECASE,
)
_EXACT_PRINTING_RE = re.compile(
    r"^(?P<name>.+?)\s+\((?P<set_code>[A-Za-z0-9]+)\)\s+(?P<collector_number>[A-Za-z0-9][A-Za-z0-9/-]*)$"
)
_EXPORTED_DECK_NAME_RE = re.compile(r"^Name\s+(?P<name>.+?)\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ParsedDecklistText:
    deck_name: str | None
    entries: list[ParsedDecklistEntry]


@dataclass(frozen=True, slots=True)
class ParsedDecklistEntry:
    line_number: int
    quantity: int
    name: str
    section: str = _DEFAULT_SECTION
    set_code: str | None = None
    collector_number: str | None = None


def _normalize_section_label(label: str) -> str | None:
    normalized = _PARENTHESIZED_COUNT_RE.sub("", label.strip().lower())
    normalized = " ".join(normalized.split())
    return _SECTION_ALIASES.get(normalized)


def _parse_exact_printing(body: str) -> tuple[str, str | None, str | None]:
    match = _EXACT_PRINTING_RE.fullmatch(body)
    if match is None:
        return body.strip(), None, None
    return (
        match.group("name").strip(),
        match.group("set_code").upper(),
        match.group("collector_number"),
    )


def _build_entry(
    *,
    line_number: int,
    quantity: int,
    body: str,
    section: str,
) -> ParsedDecklistEntry:
    if quantity <= 0:
        raise ValidationError(f"Decklist line {line_number}: quantity must be a positive integer.")
    name, set_code, collector_number = _parse_exact_printing(body)
    if not name:
        raise ValidationError(f"Decklist line {line_number}: card name is required.")
    return ParsedDecklistEntry(
        line_number=line_number,
        quantity=quantity,
        name=name,
        section=section,
        set_code=set_code,
        collector_number=collector_number,
    )


def _parse_exported_deck_name(value: str) -> str | None:
    match = _EXPORTED_DECK_NAME_RE.fullmatch(value.strip())
    if match is None:
        return None
    return match.group("name").strip()


def parse_decklist_text(deck_text: str) -> list[ParsedDecklistEntry]:
    return parse_decklist_text_with_metadata(deck_text).entries


def parse_decklist_text_with_metadata(deck_text: str) -> ParsedDecklistText:
    if not deck_text.strip():
        raise ValidationError("deck_text is required.")

    entries: list[ParsedDecklistEntry] = []
    current_section = _DEFAULT_SECTION
    deck_name: str | None = None
    saw_export_preamble = False
    started_deck_body = False

    for line_number, raw_line in enumerate(deck_text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        if not started_deck_body:
            exported_name = _parse_exported_deck_name(stripped)
            if exported_name is not None:
                deck_name = exported_name
                saw_export_preamble = True
                continue
            if stripped.lower() == "about":
                saw_export_preamble = True
                continue

        section_header = _normalize_section_label(stripped.rstrip(":"))
        if section_header is not None:
            started_deck_body = True
            current_section = section_header
            continue

        section = current_section
        prefixed_match = _PREFIXED_LINE_RE.fullmatch(stripped)
        if prefixed_match is not None:
            prefix = " ".join(prefixed_match.group("prefix").strip().lower().split())
            body = prefixed_match.group("body").strip()
            named_section = _NAMED_SECTION_PREFIX_ALIASES.get(prefix)
            if named_section is not None:
                entries.append(
                    _build_entry(
                        line_number=line_number,
                        quantity=1,
                        body=body,
                        section=named_section,
                    )
                )
                continue
            inline_section = _SECTION_PREFIX_ALIASES.get(prefix)
            if inline_section is not None:
                stripped = body
                section = inline_section
            else:
                raise ValidationError(
                    f"Decklist line {line_number}: unsupported section prefix '{prefixed_match.group('prefix').strip()}'."
                )

        quantity_match = _QUANTITY_LINE_RE.fullmatch(stripped)
        if quantity_match is None:
            if not started_deck_body and saw_export_preamble:
                continue
            raise ValidationError(
                f"Decklist line {line_number}: expected '<qty> <card name>' or a supported section header."
            )

        started_deck_body = True
        entries.append(
            _build_entry(
                line_number=line_number,
                quantity=int(quantity_match.group("quantity")),
                body=quantity_match.group("body").strip(),
                section=section,
            )
        )

    if not entries:
        raise ValidationError("deck_text must include at least one card entry.")
    return ParsedDecklistText(deck_name=deck_name, entries=entries)


def resolve_decklist_entry_card_row(
    connection: sqlite3.Connection,
    *,
    entry: ParsedDecklistEntry,
    lang: str | None = None,
    finish: str | None = None,
) -> sqlite3.Row:
    if entry.set_code is not None and entry.collector_number is not None:
        return resolve_card_row(
            connection,
            scryfall_id=None,
            oracle_id=None,
            tcgplayer_product_id=None,
            name=entry.name,
            set_code=entry.set_code,
            collector_number=entry.collector_number,
            lang=lang,
            finish=finish,
        )
    return resolve_default_card_row_for_name(
        connection,
        name=entry.name,
        lang=lang,
        finish=finish,
    )


def build_add_card_kwargs_from_decklist_entry(
    entry: ParsedDecklistEntry,
    *,
    resolved_card: sqlite3.Row,
    default_inventory: str | None,
) -> dict[str, Any]:
    inventory_slug = text_or_none(default_inventory)
    if inventory_slug is None:
        raise ValidationError("default_inventory is required for decklist imports.")
    return {
        "inventory_slug": inventory_slug,
        "inventory_display_name": None,
        "scryfall_id": str(resolved_card["scryfall_id"]),
        "oracle_id": None,
        "tcgplayer_product_id": None,
        "name": None,
        "set_code": None,
        "collector_number": None,
        "lang": None,
        "quantity": entry.quantity,
        "condition_code": DEFAULT_CONDITION_CODE,
        "finish": DEFAULT_FINISH,
        "language_code": None,
        "location": "",
        "acquisition_price": None,
        "acquisition_currency": None,
        "notes": None,
        "tags": None,
    }


def _load_pending_decklist_rows(
    db_path: str | Path,
    *,
    deck_text: str,
    default_inventory: str | None,
) -> tuple[str | None, int, list[PendingImportRow]]:
    parsed_decklist = parse_decklist_text_with_metadata(deck_text)
    entries = parsed_decklist.entries
    initialize_database(db_path)
    pending_rows: list[PendingImportRow] = []
    with connect(db_path) as connection:
        for entry in entries:
            resolved_card = resolve_decklist_entry_card_row(connection, entry=entry)
            pending_rows.append(
                PendingImportRow(
                    row_number=entry.line_number,
                    add_kwargs=build_add_card_kwargs_from_decklist_entry(
                        entry,
                        resolved_card=resolved_card,
                        default_inventory=default_inventory,
                    ),
                    response_metadata={
                        "decklist_line": entry.line_number,
                        "section": entry.section,
                    },
                    error_label="Decklist line",
                )
            )
    return parsed_decklist.deck_name, len(entries), pending_rows


def import_decklist_text(
    db_path: str | Path,
    *,
    deck_text: str,
    default_inventory: str | None,
    dry_run: bool = False,
    before_write: Callable[[], Any] | None = None,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    deck_name, rows_seen, pending_rows = _load_pending_decklist_rows(
        db_path,
        deck_text=deck_text,
        default_inventory=default_inventory,
    )
    imported_rows = _import_pending_rows(
        db_path,
        pending_rows=pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        allow_inventory_auto_create=False,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return {
        "deck_name": deck_name,
        "default_inventory": default_inventory,
        "rows_seen": rows_seen,
        "rows_written": len(imported_rows),
        "imported_rows": imported_rows,
        "dry_run": dry_run,
    }
