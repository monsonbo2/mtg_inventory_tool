from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from ..db.connection import DEFAULT_DB_PATH, require_database_file
from ..db.migrator import migrate_database
from ..db.schema import initialize_database
from ..db.snapshots import create_database_snapshot, list_database_snapshots, restore_database_snapshot
from ..importer.mtgjson import import_mtgjson_identifiers, import_mtgjson_prices
from ..importer.scryfall import import_scryfall_cards
from ..importer.service import (
    DEFAULT_BULK_CACHE_DIR,
    DEFAULT_SCRYFALL_BULK_TYPE,
    MTGJSON_IDENTIFIERS_URL,
    MTGJSON_PRICES_URL,
    SCRYFALL_BULK_METADATA_URL,
    print_restore_snapshot_result,
    print_snapshot_created,
    print_snapshot_list,
    print_stats,
    print_sync_result,
    print_sync_bulk_result,
    sync_bulk,
    sync_identifiers,
    sync_prices,
    sync_scryfall,
)
from ..importer.sync_tracking import (
    file_artifact_info,
    finish_sync_run,
    finish_sync_step,
    import_stats_dict,
    record_sync_artifact,
    record_sync_issue,
    start_sync_run,
    start_sync_step,
)


def build_snapshot_callback(
    db_path: str | Path,
    *,
    label: str,
    snapshot_dir: str | Path | None = None,
) -> tuple[Callable[[], dict[str, Any]], Callable[[], dict[str, Any] | None]]:
    snapshot: dict[str, Any] | None = None

    def ensure_snapshot() -> dict[str, Any]:
        nonlocal snapshot
        if snapshot is None:
            snapshot = create_database_snapshot(
                db_path,
                label=label,
                snapshot_dir=snapshot_dir,
            )
        return snapshot

    def current_snapshot() -> dict[str, Any] | None:
        return snapshot

    return ensure_snapshot, current_snapshot


def _ensure_existing_json_file(path: str | Path) -> None:
    if not Path(path).exists():
        raise ValueError(f"Could not read JSON file '{path}'.")


def _record_local_artifact(
    db_path: str | Path,
    run_id: int,
    *,
    artifact_role: str,
    path: str | Path,
) -> None:
    info = file_artifact_info(path)
    record_sync_artifact(
        db_path,
        run_id,
        artifact_role=artifact_role,
        local_path=info["local_path"],
        bytes_written=info["bytes_written"],
        sha256=info["sha256"],
    )


def _merge_step_details(
    base_details: dict[str, Any] | None,
    stats: Any | None = None,
    *,
    elapsed_seconds: float | None = None,
    error: Exception | None = None,
) -> dict[str, Any] | None:
    merged: dict[str, Any] = dict(base_details or {})
    result_details = getattr(stats, "details", None)
    if isinstance(result_details, dict):
        merged.update(result_details)
    if elapsed_seconds is not None:
        merged["elapsed_seconds"] = round(elapsed_seconds, 6)
    if error is not None:
        merged["error"] = str(error)
    return merged or None


def _run_tracked_step(
    db_path: str | Path,
    run_id: int,
    *,
    step_name: str,
    operation: Callable[[], Any],
    details: dict[str, Any] | None = None,
) -> Any:
    step_id = start_sync_step(db_path, run_id, step_name=step_name, details=details)
    try:
        result = operation()
    except Exception as exc:
        finish_sync_step(
            db_path,
            step_id,
            status="failed",
            details=_merge_step_details(details, error=exc),
        )
        raise

    if hasattr(result, "rows_seen") and hasattr(result, "rows_written") and hasattr(result, "rows_skipped"):
        finish_sync_step(
            db_path,
            step_id,
            status="succeeded",
            stats=result,
            details=_merge_step_details(details, result),
        )
    else:
        finish_sync_step(
            db_path,
            step_id,
            status="succeeded",
            details=details,
        )
    return result


def _summary_for_stats(**stats: Any) -> dict[str, Any]:
    return {label: import_stats_dict(value) for label, value in stats.items()}


def _artifact_role_for_download(label: str) -> str:
    return {
        "scryfall_default_cards.json": "scryfall_bulk",
        "AllIdentifiers.json.gz": "mtgjson_identifiers",
        "AllPricesToday.json.gz": "mtgjson_prices",
    }.get(label, label)


def _build_sync_tracking_callbacks(
    db_path: str | Path,
    run_id: int,
) -> tuple[
    Callable[[Any], None],
    Callable[[str, str, Any | None, float, Exception | None], None],
]:
    def on_download(download: Any) -> None:
        record_sync_artifact(
            db_path,
            run_id,
            artifact_role=_artifact_role_for_download(download.label),
            source_url=download.url,
            local_path=str(download.path.resolve()),
            bytes_written=download.bytes_written,
            sha256=download.sha256,
            etag=download.etag,
            last_modified=download.last_modified,
        )

    def on_step(
        step_name: str,
        status: str,
        stats: Any | None,
        elapsed_seconds: float,
        error: Exception | None,
    ) -> None:
        details = _merge_step_details(None, stats, elapsed_seconds=elapsed_seconds, error=error)
        step_id = start_sync_step(
            db_path,
            run_id,
            step_name=step_name,
            details=details,
        )
        finish_sync_step(
            db_path,
            step_id,
            status=status,
            stats=stats,
            details=details,
        )

    return on_download, on_step


def _sync_summary_for_result(result: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "downloads": [
            {
                "label": download.label,
                "bytes_written": download.bytes_written,
                "sha256": download.sha256,
            }
            for download in result["downloads"]
        ]
    }
    for label, key in (
        ("import_scryfall", "scryfall_stats"),
        ("import_identifiers", "identifier_stats"),
        ("import_prices", "price_stats"),
    ):
        if key in result:
            summary.update(_summary_for_stats(**{label: result[key]}))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize and import the MTG MVP schema from local Scryfall and MTGJSON bulk files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Create the MVP SQLite schema.")
    init_db.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")

    migrate_db = subparsers.add_parser("migrate-db", help="Apply pending schema migrations to an existing database.")
    migrate_db.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")

    snapshot_db = subparsers.add_parser("snapshot-db", help="Create a named safety snapshot of the database.")
    snapshot_db.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    snapshot_db.add_argument("--label", default="manual_snapshot", help="Short label for the snapshot.")
    snapshot_db.add_argument("--snapshot-dir", help="Optional override directory for snapshots.")

    list_snapshots = subparsers.add_parser("list-snapshots", help="List saved database snapshots.")
    list_snapshots.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    list_snapshots.add_argument("--snapshot-dir", help="Optional override directory for snapshots.")
    list_snapshots.add_argument("--limit", type=int, help="Optional max number of snapshots to show.")

    restore_snapshot = subparsers.add_parser("restore-snapshot", help="Restore the database from a saved snapshot.")
    restore_snapshot.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    restore_snapshot.add_argument("--snapshot", required=True, help="Snapshot path or snapshot name from list-snapshots.")
    restore_snapshot.add_argument("--snapshot-dir", help="Optional override directory for snapshots.")
    restore_snapshot.add_argument(
        "--no-pre-restore-snapshot",
        action="store_true",
        help="Skip creating an automatic pre-restore safety snapshot of the current database.",
    )

    import_scryfall = subparsers.add_parser("import-scryfall", help="Import local Scryfall bulk card data.")
    import_scryfall.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    import_scryfall.add_argument("--json", required=True, help="Path to Scryfall bulk JSON or JSON.GZ file.")
    import_scryfall.add_argument("--limit", type=int, help="Optional max number of rows to import.")

    import_identifiers = subparsers.add_parser(
        "import-identifiers",
        help="Import local MTGJSON AllIdentifiers data.",
    )
    import_identifiers.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    import_identifiers.add_argument("--json", required=True, help="Path to MTGJSON identifiers JSON or JSON.GZ file.")
    import_identifiers.add_argument("--limit", type=int, help="Optional max number of rows to import.")

    import_prices = subparsers.add_parser("import-prices", help="Import local MTGJSON AllPricesToday data.")
    import_prices.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    import_prices.add_argument("--json", required=True, help="Path to MTGJSON prices JSON or JSON.GZ file.")
    import_prices.add_argument("--limit", type=int, help="Optional max number of rows to import.")
    import_prices.add_argument(
        "--source-name",
        default="mtgjson_all_prices_today",
        help="Source label stored in price_snapshots.source_name.",
    )

    import_all = subparsers.add_parser("import-all", help="Run schema init and all local imports in sequence.")
    import_all.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    import_all.add_argument("--scryfall-json", required=True, help="Path to Scryfall bulk JSON or JSON.GZ file.")
    import_all.add_argument(
        "--identifiers-json",
        required=True,
        help="Path to MTGJSON identifiers JSON or JSON.GZ file.",
    )
    import_all.add_argument("--prices-json", required=True, help="Path to MTGJSON prices JSON or JSON.GZ file.")
    import_all.add_argument("--limit", type=int, help="Optional max number of rows per import step.")
    import_all.add_argument(
        "--source-name",
        default="mtgjson_all_prices_today",
        help="Source label stored in price_snapshots.source_name.",
    )

    sync_bulk_parser = subparsers.add_parser(
        "sync-bulk",
        help="Download the latest official bulk files and run all import steps in one command.",
    )
    sync_bulk_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    sync_bulk_parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_BULK_CACHE_DIR),
        help="Directory to store the downloaded bulk files.",
    )
    sync_bulk_parser.add_argument("--limit", type=int, help="Optional max number of rows per import step.")
    sync_bulk_parser.add_argument(
        "--source-name",
        default="mtgjson_all_prices_today",
        help="Source label stored in price_snapshots.source_name.",
    )
    sync_bulk_parser.add_argument(
        "--scryfall-bulk-type",
        default=DEFAULT_SCRYFALL_BULK_TYPE,
        help="Scryfall bulk type to download, such as default_cards.",
    )
    sync_bulk_parser.add_argument(
        "--scryfall-metadata-url",
        default=SCRYFALL_BULK_METADATA_URL,
        help="Scryfall bulk metadata URL.",
    )
    sync_bulk_parser.add_argument(
        "--mtgjson-identifiers-url",
        default=MTGJSON_IDENTIFIERS_URL,
        help="MTGJSON AllIdentifiers download URL.",
    )
    sync_bulk_parser.add_argument(
        "--mtgjson-prices-url",
        default=MTGJSON_PRICES_URL,
        help="MTGJSON AllPricesToday download URL.",
    )

    sync_scryfall_parser = subparsers.add_parser(
        "sync-scryfall",
        help="Download the latest Scryfall bulk file and import it.",
    )
    sync_scryfall_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    sync_scryfall_parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_BULK_CACHE_DIR),
        help="Directory to store the downloaded bulk files.",
    )
    sync_scryfall_parser.add_argument("--limit", type=int, help="Optional max number of rows to import.")
    sync_scryfall_parser.add_argument(
        "--scryfall-bulk-type",
        default=DEFAULT_SCRYFALL_BULK_TYPE,
        help="Scryfall bulk type to download, such as default_cards.",
    )
    sync_scryfall_parser.add_argument(
        "--scryfall-metadata-url",
        default=SCRYFALL_BULK_METADATA_URL,
        help="Scryfall bulk metadata URL.",
    )

    sync_identifiers_parser = subparsers.add_parser(
        "sync-identifiers",
        help="Download the latest MTGJSON AllIdentifiers file and import it.",
    )
    sync_identifiers_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    sync_identifiers_parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_BULK_CACHE_DIR),
        help="Directory to store the downloaded bulk files.",
    )
    sync_identifiers_parser.add_argument("--limit", type=int, help="Optional max number of rows to import.")
    sync_identifiers_parser.add_argument(
        "--mtgjson-identifiers-url",
        default=MTGJSON_IDENTIFIERS_URL,
        help="MTGJSON AllIdentifiers download URL.",
    )

    sync_prices_parser = subparsers.add_parser(
        "sync-prices",
        help="Download the latest MTGJSON AllPricesToday file and import it.",
    )
    sync_prices_parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")
    sync_prices_parser.add_argument(
        "--cache-dir",
        default=str(DEFAULT_BULK_CACHE_DIR),
        help="Directory to store the downloaded bulk files.",
    )
    sync_prices_parser.add_argument("--limit", type=int, help="Optional max number of rows to import.")
    sync_prices_parser.add_argument(
        "--source-name",
        default="mtgjson_all_prices_today",
        help="Source label stored in price_snapshots.source_name.",
    )
    sync_prices_parser.add_argument(
        "--mtgjson-prices-url",
        default=MTGJSON_PRICES_URL,
        help="MTGJSON AllPricesToday download URL.",
    )

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    tracked_db_path: str | Path | None = None
    tracked_run_id: int | None = None
    tracked_snapshot_getter: Callable[[], dict[str, Any] | None] | None = None
    try:
        if args.command == "init-db":
            initialize_database(args.db)
            print(f"Initialized database at {Path(args.db)}")
            return

        if args.command == "migrate-db":
            require_database_file(args.db)
            applied = migrate_database(args.db)
            if applied:
                details = ", ".join(f"{migration.version:04d} {migration.name}" for migration in applied)
                print(f"Migrated database at {Path(args.db)}")
                print(f"Applied migrations: {details}")
            else:
                print(f"Database at {Path(args.db)} is already at the current schema version.")
            return

        if args.command == "snapshot-db":
            snapshot = create_database_snapshot(
                args.db,
                label=args.label,
                snapshot_dir=args.snapshot_dir,
            )
            print_snapshot_created(snapshot)
            return

        if args.command == "list-snapshots":
            snapshots = list_database_snapshots(
                args.db,
                snapshot_dir=args.snapshot_dir,
                limit=args.limit,
            )
            print_snapshot_list(snapshots)
            return

        if args.command == "restore-snapshot":
            result = restore_database_snapshot(
                args.db,
                snapshot=args.snapshot,
                snapshot_dir=args.snapshot_dir,
                create_pre_restore_snapshot=not args.no_pre_restore_snapshot,
            )
            print_restore_snapshot_result(result)
            return

        if args.command == "import-scryfall":
            _ensure_existing_json_file(args.json)
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_import_scryfall")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="import_scryfall",
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            _record_local_artifact(args.db, tracked_run_id, artifact_role="scryfall_json", path=args.json)
            stats = _run_tracked_step(
                args.db,
                tracked_run_id,
                step_name="import_scryfall",
                operation=lambda: import_scryfall_cards(args.db, args.json, args.limit, before_write=ensure_snapshot),
                details={"input_path": str(Path(args.json).resolve())},
            )
            snapshot = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=snapshot["snapshot_path"] if snapshot is not None else None,
                summary=_summary_for_stats(import_scryfall=stats),
            )
            tracked_run_id = None
            if snapshot is not None:
                print(f"snapshot: {snapshot['snapshot_path']}")
            print_stats("import-scryfall", stats)
            return

        if args.command == "import-identifiers":
            _ensure_existing_json_file(args.json)
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_import_identifiers")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="import_identifiers",
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            _record_local_artifact(args.db, tracked_run_id, artifact_role="mtgjson_identifiers", path=args.json)
            stats = _run_tracked_step(
                args.db,
                tracked_run_id,
                step_name="import_identifiers",
                operation=lambda: import_mtgjson_identifiers(args.db, args.json, args.limit, before_write=ensure_snapshot),
                details={"input_path": str(Path(args.json).resolve())},
            )
            snapshot = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=snapshot["snapshot_path"] if snapshot is not None else None,
                summary=_summary_for_stats(import_identifiers=stats),
            )
            tracked_run_id = None
            if snapshot is not None:
                print(f"snapshot: {snapshot['snapshot_path']}")
            print_stats("import-identifiers", stats)
            return

        if args.command == "import-prices":
            _ensure_existing_json_file(args.json)
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_import_prices")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="import_prices",
                source_name=args.source_name,
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            _record_local_artifact(args.db, tracked_run_id, artifact_role="mtgjson_prices", path=args.json)
            stats = _run_tracked_step(
                args.db,
                tracked_run_id,
                step_name="import_prices",
                operation=lambda: import_mtgjson_prices(
                    args.db,
                    args.json,
                    args.limit,
                    args.source_name,
                    before_write=ensure_snapshot,
                ),
                details={
                    "input_path": str(Path(args.json).resolve()),
                    "source_name": args.source_name,
                },
            )
            snapshot = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=snapshot["snapshot_path"] if snapshot is not None else None,
                summary=_summary_for_stats(import_prices=stats),
            )
            tracked_run_id = None
            if snapshot is not None:
                print(f"snapshot: {snapshot['snapshot_path']}")
            print_stats("import-prices", stats)
            return

        if args.command == "import-all":
            _ensure_existing_json_file(args.scryfall_json)
            _ensure_existing_json_file(args.identifiers_json)
            _ensure_existing_json_file(args.prices_json)
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_import_all")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="import_all",
                source_name=args.source_name,
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            _record_local_artifact(args.db, tracked_run_id, artifact_role="scryfall_json", path=args.scryfall_json)
            _record_local_artifact(
                args.db,
                tracked_run_id,
                artifact_role="mtgjson_identifiers",
                path=args.identifiers_json,
            )
            _record_local_artifact(args.db, tracked_run_id, artifact_role="mtgjson_prices", path=args.prices_json)
            scryfall_stats = _run_tracked_step(
                args.db,
                tracked_run_id,
                step_name="import_scryfall",
                operation=lambda: import_scryfall_cards(
                    args.db,
                    args.scryfall_json,
                    args.limit,
                    before_write=ensure_snapshot,
                ),
                details={"input_path": str(Path(args.scryfall_json).resolve())},
            )
            identifier_stats = _run_tracked_step(
                args.db,
                tracked_run_id,
                step_name="import_identifiers",
                operation=lambda: import_mtgjson_identifiers(
                    args.db,
                    args.identifiers_json,
                    args.limit,
                    before_write=ensure_snapshot,
                ),
                details={"input_path": str(Path(args.identifiers_json).resolve())},
            )
            price_stats = _run_tracked_step(
                args.db,
                tracked_run_id,
                step_name="import_prices",
                operation=lambda: import_mtgjson_prices(
                    args.db,
                    args.prices_json,
                    args.limit,
                    args.source_name,
                    before_write=ensure_snapshot,
                ),
                details={
                    "input_path": str(Path(args.prices_json).resolve()),
                    "source_name": args.source_name,
                },
            )
            snapshot = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=snapshot["snapshot_path"] if snapshot is not None else None,
                summary=_summary_for_stats(
                    import_scryfall=scryfall_stats,
                    import_identifiers=identifier_stats,
                    import_prices=price_stats,
                ),
            )
            tracked_run_id = None
            if snapshot is not None:
                print(f"snapshot: {snapshot['snapshot_path']}")
            print_stats("import-scryfall", scryfall_stats)
            print_stats("import-identifiers", identifier_stats)
            print_stats("import-prices", price_stats)
            return

        if args.command == "sync-bulk":
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_sync_bulk")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="sync_bulk",
                source_name=args.source_name,
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            on_download, on_step = _build_sync_tracking_callbacks(args.db, tracked_run_id)

            result = sync_bulk(
                args.db,
                cache_dir=args.cache_dir,
                scryfall_metadata_url=args.scryfall_metadata_url,
                scryfall_bulk_type=args.scryfall_bulk_type,
                mtgjson_identifiers_url=args.mtgjson_identifiers_url,
                mtgjson_prices_url=args.mtgjson_prices_url,
                limit=args.limit,
                source_name=args.source_name,
                before_write=ensure_snapshot,
                on_download=on_download,
                on_step=on_step,
            )
            result["snapshot"] = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=result["snapshot"]["snapshot_path"] if result["snapshot"] is not None else None,
                summary=_sync_summary_for_result(result),
            )
            tracked_run_id = None
            print_sync_bulk_result(result)
            return

        if args.command == "sync-scryfall":
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_sync_scryfall")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="sync_scryfall",
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            on_download, on_step = _build_sync_tracking_callbacks(args.db, tracked_run_id)
            result = sync_scryfall(
                args.db,
                cache_dir=args.cache_dir,
                scryfall_metadata_url=args.scryfall_metadata_url,
                scryfall_bulk_type=args.scryfall_bulk_type,
                limit=args.limit,
                before_write=ensure_snapshot,
                on_download=on_download,
                on_step=on_step,
            )
            result["snapshot"] = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=result["snapshot"]["snapshot_path"] if result["snapshot"] is not None else None,
                summary=_sync_summary_for_result(result),
            )
            tracked_run_id = None
            print_sync_result(
                "sync-scryfall",
                result,
                stat_labels=[("import-scryfall", "scryfall_stats")],
            )
            return

        if args.command == "sync-identifiers":
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_sync_identifiers")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="sync_identifiers",
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            on_download, on_step = _build_sync_tracking_callbacks(args.db, tracked_run_id)
            result = sync_identifiers(
                args.db,
                cache_dir=args.cache_dir,
                mtgjson_identifiers_url=args.mtgjson_identifiers_url,
                limit=args.limit,
                before_write=ensure_snapshot,
                on_download=on_download,
                on_step=on_step,
            )
            result["snapshot"] = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=result["snapshot"]["snapshot_path"] if result["snapshot"] is not None else None,
                summary=_sync_summary_for_result(result),
            )
            tracked_run_id = None
            print_sync_result(
                "sync-identifiers",
                result,
                stat_labels=[("import-identifiers", "identifier_stats")],
            )
            return

        if args.command == "sync-prices":
            initialize_database(args.db)
            ensure_snapshot, get_snapshot = build_snapshot_callback(args.db, label="before_sync_prices")
            tracked_db_path = args.db
            tracked_snapshot_getter = get_snapshot
            tracked_run_id = start_sync_run(
                args.db,
                run_kind="sync_prices",
                source_name=args.source_name,
                limit_value=args.limit,
            )
            print(f"run_id: {tracked_run_id}")
            on_download, on_step = _build_sync_tracking_callbacks(args.db, tracked_run_id)
            result = sync_prices(
                args.db,
                cache_dir=args.cache_dir,
                mtgjson_prices_url=args.mtgjson_prices_url,
                limit=args.limit,
                source_name=args.source_name,
                before_write=ensure_snapshot,
                on_download=on_download,
                on_step=on_step,
            )
            result["snapshot"] = get_snapshot()
            finish_sync_run(
                args.db,
                tracked_run_id,
                status="succeeded",
                snapshot_path=result["snapshot"]["snapshot_path"] if result["snapshot"] is not None else None,
                summary=_sync_summary_for_result(result),
            )
            tracked_run_id = None
            print_sync_result(
                "sync-prices",
                result,
                stat_labels=[("import-prices", "price_stats")],
            )
            return

        parser.error(f"Unknown command {args.command}")
    except Exception as exc:
        if tracked_run_id is not None and tracked_db_path is not None:
            snapshot = tracked_snapshot_getter() if tracked_snapshot_getter is not None else None
            finish_sync_run(
                tracked_db_path,
                tracked_run_id,
                status="failed",
                snapshot_path=snapshot["snapshot_path"] if snapshot is not None else None,
                summary={"error": str(exc)},
            )
            record_sync_issue(
                tracked_db_path,
                tracked_run_id,
                level="error",
                code=type(exc).__name__,
                message=str(exc),
            )
        if isinstance(exc, (OSError, ValueError)):
            parser.exit(status=2, message=f"Error: {exc}\n")
        raise
