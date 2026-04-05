"""CSV ingestion helpers that normalize rows into inventory mutations."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from ..db.connection import connect
from ..db.schema import initialize_database
from ..errors import MtgStackError, ValidationError
from .catalog import (
    determine_printing_selection_mode,
    list_default_card_name_candidate_rows,
    list_printing_candidate_rows,
    list_tcgplayer_product_candidate_rows,
    resolve_card_row,
    resolve_default_card_row_for_name,
)
from .csv_formats import GENERIC_CSV_FORMAT, detect_csv_import_format
from .import_resolution import (
    CsvRequestedCard,
    CsvResolutionIssue,
    CsvResolutionSelection,
    build_resolution_options_for_catalog_row,
)
from .import_summary import build_resolvable_import_summary
from .normalize import (
    CSV_HEADER_ALIASES,
    finish_and_source_from_row,
    first_non_empty,
    normalize_condition_code,
    normalize_finish,
    normalized_catalog_finish_list,
    normalize_external_id,
    normalize_language_code,
    resolve_csv_quantity,
    slugify_inventory_name,
    text_or_none,
)
from .money import parse_decimal_text
from .mutations import add_card_with_connection
from .query_inventory import get_inventory_row
from .response_models import serialize_response

InventoryValidator = Callable[[sqlite3.Connection, str], Any]


@dataclass(frozen=True, slots=True)
class PendingImportRow:
    row_number: int
    add_kwargs: dict[str, Any]
    response_metadata: dict[str, Any]
    error_label: str
    finish_source: str = "finish"


@dataclass(frozen=True, slots=True)
class PlannedCsvImport:
    detected_format: str
    rows_seen: int
    requested_card_quantity: int
    pending_rows: list[PendingImportRow]
    resolution_issues: list[CsvResolutionIssue]


def normalize_csv_header(header: str) -> str:
    normalized = header.strip().lower()
    for old, new in ((" ", "_"), ("-", "_"), ("/", "_"), (".", "_")):
        normalized = normalized.replace(old, new)
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return CSV_HEADER_ALIASES.get(normalized, normalized)


def normalize_csv_row(raw_row: dict[str, Any]) -> dict[str, str | None]:
    normalized: dict[str, str | None] = {}
    for key, value in raw_row.items():
        if key is None:
            continue
        normalized[normalize_csv_header(key)] = text_or_none(value)
    return normalized


def is_blank_csv_row(row: dict[str, str | None]) -> bool:
    return not any(value is not None for value in row.values())


def build_add_card_kwargs_from_csv_row(
    row: dict[str, str | None],
    *,
    row_number: int,
    default_inventory: str | None,
) -> dict[str, Any] | None:
    inventory_display_name = text_or_none(row.get("inventory_name"))
    # Accept either a stable slug, a human display name, or the CLI default so
    # the same import path can handle hand-authored CSVs and exported files.
    inventory_slug = first_non_empty(
        row.get("inventory"),
        slugify_inventory_name(inventory_display_name) if inventory_display_name else None,
        default_inventory,
    )
    if inventory_slug is None:
        raise ValueError(f"CSV row {row_number}: provide an inventory column or pass --inventory.")

    scryfall_id = text_or_none(row.get("scryfall_id"))
    oracle_id = text_or_none(row.get("oracle_id"))
    tcgplayer_product_id = normalize_external_id(row.get("tcgplayer_product_id"))
    name = text_or_none(row.get("name"))
    if scryfall_id is None and oracle_id is None and tcgplayer_product_id is None and name is None:
        raise ValueError(
            f"CSV row {row_number}: provide one of scryfall_id, oracle_id, tcgplayer product id, or name."
        )

    quantity = resolve_csv_quantity(row, row_number=row_number)
    if quantity is None:
        return None

    finish, finish_source = finish_and_source_from_row(row)

    return {
        "inventory_slug": inventory_slug,
        "inventory_display_name": inventory_display_name,
        "scryfall_id": scryfall_id,
        "oracle_id": oracle_id,
        "tcgplayer_product_id": tcgplayer_product_id,
        "name": name,
        "set_code": text_or_none(row.get("set_code")),
        "set_name": text_or_none(row.get("set_name")),
        "collector_number": text_or_none(row.get("collector_number")),
        "lang": text_or_none(row.get("lang")),
        "quantity": quantity,
        "condition_code": normalize_condition_code(row.get("condition")),
        "finish": finish,
        "_finish_source": finish_source,
        "language_code": (
            normalize_language_code(row.get("language_code"))
            if text_or_none(row.get("language_code")) is not None
            else None
        ),
        "location": text_or_none(row.get("location")) or "",
        "acquisition_price": parse_decimal_text(
            row.get("acquisition_price"),
            field_name="acquisition_price",
            row_number=row_number,
        ),
        "acquisition_currency": text_or_none(row.get("acquisition_currency")),
        "notes": text_or_none(row.get("notes")),
        "tags": text_or_none(row.get("tags")),
    }


def _resolve_csv_finish_for_row(
    connection: sqlite3.Connection,
    *,
    add_kwargs: dict[str, Any],
    finish_source: str,
) -> sqlite3.Row | None:
    if finish_source != "default":
        return None

    card = resolve_card_row(
        connection,
        scryfall_id=add_kwargs["scryfall_id"],
        oracle_id=add_kwargs["oracle_id"],
        tcgplayer_product_id=normalize_external_id(add_kwargs["tcgplayer_product_id"]),
        name=add_kwargs["name"],
        set_code=add_kwargs["set_code"],
        set_name=add_kwargs["set_name"],
        collector_number=add_kwargs["collector_number"],
        lang=add_kwargs["lang"],
        finish=None,
    )
    available_finishes = normalized_catalog_finish_list(card["finishes_json"])
    if len(available_finishes) == 1:
        add_kwargs["finish"] = available_finishes[0]
        return card
    if len(available_finishes) > 1:
        raise ValidationError(
            "finish is required for this printing when multiple finishes are available. "
            f"Available finishes: {', '.join(available_finishes)}."
        )
    return card


def _load_pending_csv_rows(
    handle: TextIO,
    *,
    source_name: str,
    default_inventory: str | None,
) -> tuple[str, int, list[PendingImportRow]]:
    pending_rows: list[PendingImportRow] = []
    rows_seen = 0

    try:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV file must include a header row.")
        normalized_headers = {
            normalize_csv_header(fieldname)
            for fieldname in reader.fieldnames
            if fieldname is not None
        }
        format_adapter = detect_csv_import_format(normalized_headers)
        detected_format = format_adapter.key if format_adapter is not None else GENERIC_CSV_FORMAT

        for row_number, raw_row in enumerate(reader, start=2):
            row = normalize_csv_row(raw_row)
            if format_adapter is not None:
                row = format_adapter.normalize_row(row)
            if is_blank_csv_row(row):
                continue

            rows_seen += 1
            add_kwargs = build_add_card_kwargs_from_csv_row(
                row,
                row_number=row_number,
                default_inventory=default_inventory,
            )
            if add_kwargs is None:
                continue
            pending_rows.append(
                PendingImportRow(
                    row_number=row_number,
                    add_kwargs=add_kwargs,
                    response_metadata={"csv_row": row_number},
                    error_label="CSV row",
                    finish_source=str(add_kwargs.get("_finish_source", "finish")),
                )
            )
    except csv.Error as exc:
        raise ValueError(f"Could not parse CSV file '{source_name}': {exc}") from exc
    except UnicodeError as exc:
        raise ValueError(f"Could not decode CSV file '{source_name}' as UTF-8.") from exc

    return detected_format, rows_seen, pending_rows


def _build_csv_requested_card(pending_row: PendingImportRow) -> CsvRequestedCard:
    add_kwargs = pending_row.add_kwargs
    return CsvRequestedCard(
        scryfall_id=text_or_none(add_kwargs.get("scryfall_id")),
        oracle_id=text_or_none(add_kwargs.get("oracle_id")),
        tcgplayer_product_id=normalize_external_id(add_kwargs.get("tcgplayer_product_id")),
        name=text_or_none(add_kwargs.get("name")),
        quantity=int(add_kwargs.get("quantity") or 0),
        set_code=text_or_none(add_kwargs.get("set_code")),
        set_name=text_or_none(add_kwargs.get("set_name")),
        collector_number=text_or_none(add_kwargs.get("collector_number")),
        lang=text_or_none(add_kwargs.get("lang")),
        finish=None if pending_row.finish_source == "default" else text_or_none(add_kwargs.get("finish")),
    )


def _build_csv_issue(
    kind: str,
    pending_row: PendingImportRow,
    *,
    options: list[Any],
) -> CsvResolutionIssue:
    return CsvResolutionIssue(
        kind=kind,
        csv_row=pending_row.row_number,
        requested=_build_csv_requested_card(pending_row),
        options=options,
    )


def _normalize_csv_resolution_selections(
    resolutions: list[Mapping[str, Any]] | None,
) -> dict[int, CsvResolutionSelection]:
    if not resolutions:
        return {}

    normalized: dict[int, CsvResolutionSelection] = {}
    for raw_selection in resolutions:
        csv_row = raw_selection.get("csv_row")
        if not isinstance(csv_row, int):
            raise ValidationError("Each CSV resolution must include an integer csv_row.")
        if csv_row in normalized:
            raise ValidationError("CSV resolutions must not repeat the same csv_row.")
        scryfall_id = text_or_none(raw_selection.get("scryfall_id"))
        if scryfall_id is None:
            raise ValidationError("Each CSV resolution must include a scryfall_id.")
        finish = text_or_none(raw_selection.get("finish"))
        if finish is None:
            raise ValidationError("Each CSV resolution must include a finish.")
        normalized[csv_row] = CsvResolutionSelection(
            csv_row=csv_row,
            scryfall_id=scryfall_id,
            finish=normalize_finish(finish),
        )
    return normalized


def _resolved_csv_pending_row(
    pending_row: PendingImportRow,
    *,
    resolved_card: sqlite3.Row,
    finish: str,
    printing_selection_mode: str,
) -> PendingImportRow:
    add_kwargs = dict(pending_row.add_kwargs)
    add_kwargs["scryfall_id"] = str(resolved_card["scryfall_id"])
    add_kwargs["oracle_id"] = None
    add_kwargs["tcgplayer_product_id"] = None
    add_kwargs["name"] = None
    add_kwargs["set_code"] = None
    add_kwargs["set_name"] = None
    add_kwargs["collector_number"] = None
    add_kwargs["lang"] = None
    add_kwargs["finish"] = finish
    add_kwargs["_finish_source"] = "finish"
    add_kwargs["printing_selection_mode"] = printing_selection_mode
    return PendingImportRow(
        row_number=pending_row.row_number,
        add_kwargs=add_kwargs,
        response_metadata=dict(pending_row.response_metadata),
        error_label=pending_row.error_label,
        finish_source="finish",
    )


def _probe_csv_row_resolution(
    connection: sqlite3.Connection,
    *,
    pending_row: PendingImportRow,
) -> tuple[PendingImportRow | None, CsvResolutionIssue | None]:
    add_kwargs = pending_row.add_kwargs
    requested_finish = None if pending_row.finish_source == "default" else add_kwargs.get("finish")

    scryfall_id = text_or_none(add_kwargs.get("scryfall_id"))
    if scryfall_id is not None:
        resolved_card = resolve_card_row(
            connection,
            scryfall_id=scryfall_id,
            oracle_id=None,
            tcgplayer_product_id=None,
            name=None,
            set_code=None,
            set_name=None,
            collector_number=None,
            lang=None,
            finish=requested_finish,
        )
        row_options, requires_choice = build_resolution_options_for_catalog_row(
            resolved_card,
            requested_finish=requested_finish,
            prefer_default_finish=False,
        )
        if requires_choice:
            return None, _build_csv_issue("finish_required", pending_row, options=row_options)
        return _resolved_csv_pending_row(
            pending_row,
            resolved_card=resolved_card,
            finish=row_options[0].finish,
            printing_selection_mode="explicit",
        ), None

    tcgplayer_product_id = normalize_external_id(add_kwargs.get("tcgplayer_product_id"))
    if tcgplayer_product_id is not None:
        candidate_rows = list_tcgplayer_product_candidate_rows(
            connection,
            tcgplayer_product_id=tcgplayer_product_id,
            finish=requested_finish,
        )
        if len(candidate_rows) > 1:
            options: list[Any] = []
            for row in candidate_rows:
                row_options, _ = build_resolution_options_for_catalog_row(
                    row,
                    requested_finish=requested_finish,
                    prefer_default_finish=False,
                )
                options.extend(row_options)
            return None, _build_csv_issue("ambiguous_printing", pending_row, options=options)

        row_options, requires_choice = build_resolution_options_for_catalog_row(
            candidate_rows[0],
            requested_finish=requested_finish,
            prefer_default_finish=False,
        )
        if requires_choice:
            return None, _build_csv_issue("finish_required", pending_row, options=row_options)
        return _resolved_csv_pending_row(
            pending_row,
            resolved_card=candidate_rows[0],
            finish=row_options[0].finish,
            printing_selection_mode="explicit",
        ), None

    oracle_id = text_or_none(add_kwargs.get("oracle_id"))
    if oracle_id is not None:
        resolved_card = resolve_card_row(
            connection,
            scryfall_id=None,
            oracle_id=oracle_id,
            tcgplayer_product_id=None,
            name=None,
            set_code=text_or_none(add_kwargs.get("set_code")),
            set_name=text_or_none(add_kwargs.get("set_name")),
            collector_number=text_or_none(add_kwargs.get("collector_number")),
            lang=text_or_none(add_kwargs.get("lang")),
            finish=requested_finish,
        )
        row_options, requires_choice = build_resolution_options_for_catalog_row(
            resolved_card,
            requested_finish=requested_finish,
            prefer_default_finish=False,
        )
        if requires_choice:
            return None, _build_csv_issue("finish_required", pending_row, options=row_options)
        printing_selection_mode = determine_printing_selection_mode(
            connection,
            scryfall_id=None,
            oracle_id=oracle_id,
            tcgplayer_product_id=None,
            name=None,
            set_code=text_or_none(add_kwargs.get("set_code")),
            set_name=text_or_none(add_kwargs.get("set_name")),
            collector_number=text_or_none(add_kwargs.get("collector_number")),
            lang=text_or_none(add_kwargs.get("lang")),
            finish=requested_finish,
        )
        return _resolved_csv_pending_row(
            pending_row,
            resolved_card=resolved_card,
            finish=row_options[0].finish,
            printing_selection_mode=printing_selection_mode,
        ), None

    name = text_or_none(add_kwargs.get("name"))
    if name is None:
        raise ValidationError(f"CSV row {pending_row.row_number}: name or another identifier is required.")

    set_code = text_or_none(add_kwargs.get("set_code"))
    set_name = text_or_none(add_kwargs.get("set_name"))
    collector_number = text_or_none(add_kwargs.get("collector_number"))
    lang = text_or_none(add_kwargs.get("lang"))
    if set_code is not None or set_name is not None or collector_number is not None:
        candidate_rows = list_printing_candidate_rows(
            connection,
            name=name,
            set_code=set_code,
            set_name=set_name,
            collector_number=collector_number,
            lang=lang,
            finish=requested_finish,
        )
        if len(candidate_rows) > 1:
            options: list[Any] = []
            for row in candidate_rows:
                row_options, _ = build_resolution_options_for_catalog_row(
                    row,
                    requested_finish=requested_finish,
                    prefer_default_finish=False,
                )
                options.extend(row_options)
            return None, _build_csv_issue("ambiguous_printing", pending_row, options=options)

        row_options, requires_choice = build_resolution_options_for_catalog_row(
            candidate_rows[0],
            requested_finish=requested_finish,
            prefer_default_finish=False,
        )
        if requires_choice:
            return None, _build_csv_issue("finish_required", pending_row, options=row_options)
        return _resolved_csv_pending_row(
            pending_row,
            resolved_card=candidate_rows[0],
            finish=row_options[0].finish,
            printing_selection_mode="explicit",
        ), None

    candidate_rows = list_default_card_name_candidate_rows(
        connection,
        name=name,
        lang=lang,
        finish=requested_finish,
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
                set_name=None,
                collector_number=None,
                lang=lang,
                finish=requested_finish,
            )
            row_options, _ = build_resolution_options_for_catalog_row(
                resolved_card,
                requested_finish=requested_finish,
                prefer_default_finish=False,
            )
            options.extend(row_options)
        return None, _build_csv_issue("ambiguous_card_name", pending_row, options=options)

    resolved_card = resolve_default_card_row_for_name(
        connection,
        name=name,
        lang=lang,
        finish=requested_finish,
    )
    row_options, requires_choice = build_resolution_options_for_catalog_row(
        resolved_card,
        requested_finish=requested_finish,
        prefer_default_finish=False,
    )
    if requires_choice:
        return None, _build_csv_issue("finish_required", pending_row, options=row_options)
    printing_selection_mode = determine_printing_selection_mode(
        connection,
        scryfall_id=None,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=name,
        set_code=None,
        set_name=None,
        collector_number=None,
        lang=lang,
        finish=requested_finish,
    )
    return _resolved_csv_pending_row(
        pending_row,
        resolved_card=resolved_card,
        finish=row_options[0].finish,
        printing_selection_mode=printing_selection_mode,
    ), None


def _build_pending_csv_row_from_selection(
    connection: sqlite3.Connection,
    *,
    pending_row: PendingImportRow,
    selection: CsvResolutionSelection,
) -> PendingImportRow:
    resolved_pending_row, resolution_issue = _probe_csv_row_resolution(
        connection,
        pending_row=pending_row,
    )
    if resolution_issue is None:
        raise ValidationError(f"CSV row {pending_row.row_number} does not require an explicit resolution.")
    valid_options = {
        (option.scryfall_id, option.finish)
        for option in resolution_issue.options
    }
    if (selection.scryfall_id, selection.finish) not in valid_options:
        raise ValidationError(
            f"CSV row {pending_row.row_number} resolution does not match any suggested option.",
            details={"resolution_issue": serialize_response(resolution_issue)},
        )

    resolved_card = resolve_card_row(
        connection,
        scryfall_id=selection.scryfall_id,
        oracle_id=None,
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        set_name=None,
        collector_number=None,
        lang=None,
        finish=selection.finish,
    )
    return _resolved_csv_pending_row(
        pending_row,
        resolved_card=resolved_card,
        finish=selection.finish,
        printing_selection_mode="explicit",
    )


def _plan_csv_import(
    db_path: str | Path,
    *,
    csv_handle: TextIO,
    csv_filename: str,
    default_inventory: str | None,
    resolutions: list[Mapping[str, Any]] | None = None,
    allow_inventory_auto_create: bool = True,
    inventory_validator: InventoryValidator | None = None,
) -> PlannedCsvImport:
    detected_format, rows_seen, loaded_rows = _load_pending_csv_rows(
        csv_handle,
        source_name=csv_filename,
        default_inventory=default_inventory,
    )
    requested_card_quantity = sum(int(pending_row.add_kwargs.get("quantity") or 0) for pending_row in loaded_rows)
    selection_map = _normalize_csv_resolution_selections(resolutions)
    pending_rows: list[PendingImportRow] = []
    resolution_issues: list[CsvResolutionIssue] = []

    initialize_database(db_path)
    with connect(db_path) as connection:
        validated_inventories: set[str] = set()
        for loaded_row in loaded_rows:
            inventory_slug = str(loaded_row.add_kwargs["inventory_slug"])
            if inventory_slug in validated_inventories:
                continue
            if inventory_validator is not None:
                inventory_validator(connection, inventory_slug)
            if not allow_inventory_auto_create:
                get_inventory_row(connection, inventory_slug)
            validated_inventories.add(inventory_slug)

        for loaded_row in loaded_rows:
            selection = selection_map.pop(loaded_row.row_number, None)
            if selection is not None:
                pending_rows.append(
                    _build_pending_csv_row_from_selection(
                        connection,
                        pending_row=loaded_row,
                        selection=selection,
                    )
                )
                continue

            resolved_pending_row, resolution_issue = _probe_csv_row_resolution(
                connection,
                pending_row=loaded_row,
            )
            if resolution_issue is not None:
                resolution_issues.append(resolution_issue)
                continue
            if resolved_pending_row is None:
                raise AssertionError("CSV probe returned neither a pending row nor a resolution issue.")
            pending_rows.append(resolved_pending_row)

    if selection_map:
        unknown_rows = ", ".join(str(row_number) for row_number in sorted(selection_map))
        raise ValidationError(f"CSV resolutions reference unknown csv rows: {unknown_rows}.")

    return PlannedCsvImport(
        detected_format=detected_format,
        rows_seen=rows_seen,
        requested_card_quantity=requested_card_quantity,
        pending_rows=pending_rows,
        resolution_issues=resolution_issues,
    )


def _import_pending_rows(
    db_path: str | Path,
    *,
    pending_rows: list[PendingImportRow],
    dry_run: bool = False,
    before_write: Callable[[], Any] | None = None,
    allow_inventory_auto_create: bool = True,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    imported_rows: list[dict[str, Any]] = []
    inventory_cache: dict[str, sqlite3.Row] = {}

    initialize_database(db_path)
    with connect(db_path) as connection:
        validated_inventories: set[str] = set()
        for pending_row in pending_rows:
            inventory_slug = str(pending_row.add_kwargs["inventory_slug"])
            if inventory_slug in validated_inventories:
                continue
            if inventory_validator is not None:
                inventory_validator(connection, inventory_slug)
            validated_inventories.add(inventory_slug)

        for pending_row in pending_rows:
            row_add_kwargs = dict(pending_row.add_kwargs)
            if not allow_inventory_auto_create:
                row_add_kwargs["inventory_display_name"] = None

            finish_source = pending_row.finish_source
            row_add_kwargs.pop("_finish_source", None)
            try:
                resolved_card = _resolve_csv_finish_for_row(
                    connection,
                    add_kwargs=row_add_kwargs,
                    finish_source=finish_source,
                )
                result = add_card_with_connection(
                    connection,
                    inventory_cache=inventory_cache,
                    before_write=None if dry_run else before_write,
                    resolved_card=resolved_card,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    request_id=request_id,
                    **row_add_kwargs,
                )
            except MtgStackError as exc:
                raise type(exc)(
                    f"{pending_row.error_label} {pending_row.row_number}: {exc}",
                    error_code=exc.error_code,
                ) from exc
            except ValueError as exc:
                raise ValueError(f"{pending_row.error_label} {pending_row.row_number}: {exc}") from exc
            imported_rows.append({**pending_row.response_metadata, **serialize_response(result)})

        if dry_run:
            # Preview mode reuses the real add-card workflow, then rolls
            # back at the end so validation and reporting stay identical.
            connection.rollback()
        else:
            connection.commit()

    return imported_rows


def import_csv_stream(
    db_path: str | Path,
    *,
    csv_handle: TextIO,
    csv_filename: str,
    default_inventory: str | None,
    dry_run: bool = False,
    resolutions: list[Mapping[str, Any]] | None = None,
    before_write: Callable[[], Any] | None = None,
    allow_inventory_auto_create: bool = True,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    plan = _plan_csv_import(
        db_path,
        csv_handle=csv_handle,
        csv_filename=csv_filename,
        default_inventory=default_inventory,
        resolutions=resolutions,
        allow_inventory_auto_create=allow_inventory_auto_create,
        inventory_validator=inventory_validator,
    )
    if plan.resolution_issues and not dry_run:
        raise ValidationError(
            "Unresolved CSV import ambiguities remain.",
            details={"resolution_issues": serialize_response(plan.resolution_issues)},
        )
    imported_rows = _import_pending_csv_rows(
        db_path,
        pending_rows=plan.pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        allow_inventory_auto_create=allow_inventory_auto_create,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )
    return {
        "csv_filename": csv_filename,
        "detected_format": plan.detected_format,
        "default_inventory": default_inventory,
        "rows_seen": plan.rows_seen,
        "rows_written": len(imported_rows),
        "ready_to_commit": not plan.resolution_issues,
        "summary": build_resolvable_import_summary(
            imported_rows,
            requested_card_quantity=plan.requested_card_quantity,
        ),
        "resolution_issues": serialize_response(plan.resolution_issues),
        "imported_rows": imported_rows,
        "dry_run": dry_run,
    }


def _import_pending_csv_rows(
    db_path: str | Path,
    *,
    pending_rows: list[PendingImportRow],
    dry_run: bool = False,
    before_write: Callable[[], Any] | None = None,
    allow_inventory_auto_create: bool = True,
    inventory_validator: InventoryValidator | None = None,
    actor_type: str = "cli",
    actor_id: str | None = None,
    request_id: str | None = None,
) -> list[dict[str, Any]]:
    return _import_pending_rows(
        db_path,
        pending_rows=pending_rows,
        dry_run=dry_run,
        before_write=before_write,
        allow_inventory_auto_create=allow_inventory_auto_create,
        inventory_validator=inventory_validator,
        actor_type=actor_type,
        actor_id=actor_id,
        request_id=request_id,
    )


def import_csv(
    db_path: str | Path,
    *,
    csv_path: str | Path,
    default_inventory: str | None,
    dry_run: bool = False,
    resolutions: list[Mapping[str, Any]] | None = None,
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    try:
        with Path(csv_path).open(mode="r", encoding="utf-8-sig", newline="") as handle:
            plan = _plan_csv_import(
                db_path,
                csv_handle=handle,
                csv_filename=str(csv_path),
                default_inventory=default_inventory,
                resolutions=resolutions,
            )
    except OSError as exc:
        raise ValueError(f"Could not read CSV file '{csv_path}'.") from exc
    if plan.resolution_issues and not dry_run:
        raise ValidationError(
            "Unresolved CSV import ambiguities remain.",
            details={"resolution_issues": serialize_response(plan.resolution_issues)},
        )
    imported_rows = _import_pending_csv_rows(
        db_path,
        pending_rows=plan.pending_rows,
        dry_run=dry_run,
        before_write=before_write,
    )

    return {
        "csv_path": str(csv_path),
        "detected_format": plan.detected_format,
        "default_inventory": default_inventory,
        "rows_seen": plan.rows_seen,
        "rows_written": len(imported_rows),
        "ready_to_commit": not plan.resolution_issues,
        "summary": build_resolvable_import_summary(
            imported_rows,
            requested_card_quantity=plan.requested_card_quantity,
        ),
        "resolution_issues": serialize_response(plan.resolution_issues),
        "imported_rows": imported_rows,
        "dry_run": dry_run,
    }
