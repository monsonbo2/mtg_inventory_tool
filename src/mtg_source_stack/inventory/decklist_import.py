"""Decklist parsing helpers for pasted text imports."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping

from ..errors import ValidationError
from .catalog import (
    determine_printing_selection_mode,
    list_default_card_name_candidate_rows,
    list_printing_candidate_rows,
    resolve_card_row,
    resolve_default_card_row_for_name,
)
from ..db.connection import connect
from ..db.schema import SchemaPreparationPolicy, prepare_database
from .csv_import import InventoryValidator, PendingImportRow, _import_pending_rows
from .import_summary import build_resolvable_deck_import_summary
from .import_resolution import (
    DecklistRequestedCard,
    DecklistResolutionIssue,
    DecklistResolutionSelection,
    build_resolution_options_for_catalog_row,
)
from .normalize import DEFAULT_CONDITION_CODE, normalize_finish, text_or_none
from .query_inventory import get_inventory_row
from .response_models import serialize_response


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


@dataclass(frozen=True, slots=True)
class PlannedDecklistImport:
    deck_name: str | None
    rows_seen: int
    requested_card_quantity: int
    pending_rows: list[PendingImportRow]
    resolution_issues: list[DecklistResolutionIssue]


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
    finish: str,
    printing_selection_mode: str = "explicit",
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
        "finish": finish,
        "language_code": None,
        "location": "",
        "acquisition_price": None,
        "acquisition_currency": None,
        "notes": None,
        "tags": None,
        "printing_selection_mode": printing_selection_mode,
    }


def _build_decklist_requested_card(entry: ParsedDecklistEntry) -> DecklistRequestedCard:
    return DecklistRequestedCard(
        name=entry.name,
        quantity=entry.quantity,
        set_code=entry.set_code,
        collector_number=entry.collector_number,
        finish=None,
    )


def _normalize_decklist_resolution_selections(
    resolutions: list[Mapping[str, Any]] | None,
) -> dict[int, DecklistResolutionSelection]:
    if not resolutions:
        return {}

    normalized: dict[int, DecklistResolutionSelection] = {}
    for raw_selection in resolutions:
        decklist_line = raw_selection.get("decklist_line")
        if not isinstance(decklist_line, int):
            raise ValidationError("Each decklist resolution must include an integer decklist_line.")
        if decklist_line in normalized:
            raise ValidationError("decklist resolutions must not repeat the same decklist_line.")
        scryfall_id = text_or_none(raw_selection.get("scryfall_id"))
        if scryfall_id is None:
            raise ValidationError("Each decklist resolution must include a scryfall_id.")
        finish_raw = text_or_none(raw_selection.get("finish"))
        if finish_raw is None:
            raise ValidationError("Each decklist resolution must include a finish.")
        normalized[decklist_line] = DecklistResolutionSelection(
            decklist_line=decklist_line,
            scryfall_id=scryfall_id,
            finish=normalize_finish(finish_raw),
        )
    return normalized


def _build_pending_decklist_row(
    entry: ParsedDecklistEntry,
    *,
    resolved_card: sqlite3.Row,
    default_inventory: str | None,
    finish: str,
    printing_selection_mode: str,
) -> PendingImportRow:
    return PendingImportRow(
        row_number=entry.line_number,
        add_kwargs=build_add_card_kwargs_from_decklist_entry(
            entry,
            resolved_card=resolved_card,
            default_inventory=default_inventory,
            finish=finish,
            printing_selection_mode=printing_selection_mode,
        ),
        response_metadata={
            "decklist_line": entry.line_number,
            "section": entry.section,
        },
        error_label="Decklist line",
    )


def _build_decklist_issue(
    kind: str,
    entry: ParsedDecklistEntry,
    *,
    options: list[Any],
) -> DecklistResolutionIssue:
    return DecklistResolutionIssue(
        kind=kind,
        decklist_line=entry.line_number,
        section=entry.section,
        requested=_build_decklist_requested_card(entry),
        options=options,
    )


def _probe_decklist_resolution(
    connection: sqlite3.Connection,
    *,
    entry: ParsedDecklistEntry,
    default_inventory: str | None,
) -> tuple[PendingImportRow | None, DecklistResolutionIssue | None]:
    if entry.set_code is not None and entry.collector_number is not None:
        candidate_rows = list_printing_candidate_rows(
            connection,
            name=entry.name,
            set_code=entry.set_code,
            set_name=None,
            collector_number=entry.collector_number,
            lang=None,
            finish=None,
        )
        if len(candidate_rows) > 1:
            options: list[Any] = []
            for row in candidate_rows:
                row_options, _ = build_resolution_options_for_catalog_row(row)
                options.extend(row_options)
            return None, _build_decklist_issue("ambiguous_printing", entry, options=options)

        row_options, requires_choice = build_resolution_options_for_catalog_row(candidate_rows[0])
        if requires_choice:
            return None, _build_decklist_issue("finish_required", entry, options=row_options)
        return _build_pending_decklist_row(
            entry,
            resolved_card=candidate_rows[0],
            default_inventory=default_inventory,
            finish=row_options[0].finish,
            printing_selection_mode="explicit",
        ), None

    candidate_rows = list_default_card_name_candidate_rows(
        connection,
        name=entry.name,
        lang=None,
        finish=None,
    )
    oracle_ids = sorted({str(row["oracle_id"]) for row in candidate_rows})
    if len(oracle_ids) > 1:
        options: list[Any] = []
        for oracle_id in oracle_ids:
            resolved_card = resolve_card_row(
                connection,
                scryfall_id=None,
                oracle_id=oracle_id,
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                finish=None,
            )
            row_options, _ = build_resolution_options_for_catalog_row(resolved_card)
            options.extend(row_options)
        return None, _build_decklist_issue("ambiguous_card_name", entry, options=options)

    resolved_card = resolve_default_card_row_for_name(
        connection,
        name=entry.name,
        lang=None,
        finish=None,
    )
    row_options, requires_choice = build_resolution_options_for_catalog_row(resolved_card)
    if requires_choice:
        return None, _build_decklist_issue("finish_required", entry, options=row_options)
    printing_selection_mode = determine_printing_selection_mode(
        connection,
        scryfall_id=None,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=entry.name,
        set_code=None,
        set_name=None,
        collector_number=None,
        lang=None,
        finish=None,
    )
    return _build_pending_decklist_row(
        entry,
        resolved_card=resolved_card,
        default_inventory=default_inventory,
        finish=row_options[0].finish,
        printing_selection_mode=printing_selection_mode,
    ), None


def _build_pending_decklist_row_from_selection(
    connection: sqlite3.Connection,
    *,
    entry: ParsedDecklistEntry,
    default_inventory: str | None,
    selection: DecklistResolutionSelection,
) -> PendingImportRow:
    pending_row, resolution_issue = _probe_decklist_resolution(
        connection,
        entry=entry,
        default_inventory=default_inventory,
    )
    if resolution_issue is None:
        raise ValidationError(f"Decklist line {entry.line_number} does not require an explicit resolution.")

    valid_options = {
        (option.scryfall_id, option.finish)
        for option in resolution_issue.options
    }
    if (selection.scryfall_id, selection.finish) not in valid_options:
        raise ValidationError(
            f"Decklist line {entry.line_number} resolution does not match any suggested option.",
            details={"resolution_issue": serialize_response(resolution_issue)},
        )

    resolved_card = resolve_card_row(
        connection,
        scryfall_id=selection.scryfall_id,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
        finish=selection.finish,
    )
    return _build_pending_decklist_row(
        entry,
        resolved_card=resolved_card,
        default_inventory=default_inventory,
        finish=selection.finish,
        printing_selection_mode="explicit",
    )


def _resolve_decklist_import_plan(
    prepared_db_path: str | Path,
    *,
    parsed_decklist: ParsedDecklistText,
    inventory_slug: str,
    resolutions: list[Mapping[str, Any]] | None,
    inventory_validator: InventoryValidator | None = None,
) -> PlannedDecklistImport:
    entries = parsed_decklist.entries
    requested_card_quantity = sum(entry.quantity for entry in entries)
    selection_map = _normalize_decklist_resolution_selections(resolutions)
    pending_rows: list[PendingImportRow] = []
    resolution_issues: list[DecklistResolutionIssue] = []
    with connect(prepared_db_path) as connection:
        if inventory_validator is not None:
            inventory_validator(connection, inventory_slug)
        get_inventory_row(connection, inventory_slug)
        for entry in entries:
            selection = selection_map.pop(entry.line_number, None)
            if selection is not None:
                pending_rows.append(
                    _build_pending_decklist_row_from_selection(
                        connection,
                        entry=entry,
                        default_inventory=inventory_slug,
                        selection=selection,
                    )
                )
                continue

            pending_row, resolution_issue = _probe_decklist_resolution(
                connection,
                entry=entry,
                default_inventory=inventory_slug,
            )
            if resolution_issue is not None:
                resolution_issues.append(resolution_issue)
                continue
            if pending_row is None:
                raise AssertionError("Decklist probe returned neither a pending row nor a resolution issue.")
            pending_rows.append(pending_row)

    if selection_map:
        unknown_lines = ", ".join(str(line_number) for line_number in sorted(selection_map))
        raise ValidationError(f"decklist resolutions reference unknown decklist lines: {unknown_lines}.")

    return PlannedDecklistImport(
        deck_name=parsed_decklist.deck_name,
        rows_seen=len(entries),
        requested_card_quantity=requested_card_quantity,
        pending_rows=pending_rows,
        resolution_issues=resolution_issues,
    )


def import_decklist_text(
    db_path: str | Path,
    *,
    deck_text: str,
    default_inventory: str | None,
    dry_run: bool = False,
    resolutions: list[Mapping[str, Any]] | None = None,
    before_write: Callable[[], Any] | None = None,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
    schema_policy: SchemaPreparationPolicy = "initialize_if_needed",
) -> dict[str, Any]:
    parsed_decklist = parse_decklist_text_with_metadata(deck_text)
    inventory_slug = text_or_none(default_inventory)
    if inventory_slug is None:
        raise ValidationError("default_inventory is required for decklist imports.")
    prepared_db_path = prepare_database(
        db_path,
        schema_policy=schema_policy,
    )
    plan = _resolve_decklist_import_plan(
        prepared_db_path,
        parsed_decklist=parsed_decklist,
        inventory_slug=inventory_slug,
        resolutions=resolutions,
        inventory_validator=inventory_validator,
    )
    if plan.resolution_issues and not dry_run:
        raise ValidationError(
            "Unresolved decklist import ambiguities remain.",
            details={"resolution_issues": serialize_response(plan.resolution_issues)},
        )
    imported_rows = _import_pending_rows(
        prepared_db_path,
        pending_rows=plan.pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        allow_inventory_auto_create=False,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return {
        "deck_name": plan.deck_name,
        "default_inventory": default_inventory,
        "rows_seen": plan.rows_seen,
        "rows_written": len(imported_rows),
        "ready_to_commit": not plan.resolution_issues,
        "summary": build_resolvable_deck_import_summary(
            imported_rows,
            requested_card_quantity=plan.requested_card_quantity,
        ),
        "resolution_issues": serialize_response(plan.resolution_issues),
        "imported_rows": imported_rows,
        "dry_run": dry_run,
    }
