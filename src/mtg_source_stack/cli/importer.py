from __future__ import annotations

import argparse
from pathlib import Path

from ..db.connection import DEFAULT_DB_PATH
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
    print_sync_bulk_result,
    sync_bulk,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize and import the MTG MVP schema from local Scryfall and MTGJSON bulk files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="Create the MVP SQLite schema.")
    init_db.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path.")

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

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init-db":
        initialize_database(args.db)
        print(f"Initialized database at {Path(args.db)}")
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

    initialize_database(args.db)

    if args.command == "import-scryfall":
        snapshot = create_database_snapshot(args.db, label="before_import_scryfall")
        stats = import_scryfall_cards(args.db, args.json, args.limit)
        print(f"snapshot: {snapshot['snapshot_path']}")
        print_stats("import-scryfall", stats)
        return

    if args.command == "import-identifiers":
        snapshot = create_database_snapshot(args.db, label="before_import_identifiers")
        stats = import_mtgjson_identifiers(args.db, args.json, args.limit)
        print(f"snapshot: {snapshot['snapshot_path']}")
        print_stats("import-identifiers", stats)
        return

    if args.command == "import-prices":
        snapshot = create_database_snapshot(args.db, label="before_import_prices")
        stats = import_mtgjson_prices(args.db, args.json, args.limit, args.source_name)
        print(f"snapshot: {snapshot['snapshot_path']}")
        print_stats("import-prices", stats)
        return

    if args.command == "import-all":
        snapshot = create_database_snapshot(args.db, label="before_import_all")
        scryfall_stats = import_scryfall_cards(args.db, args.scryfall_json, args.limit)
        identifier_stats = import_mtgjson_identifiers(args.db, args.identifiers_json, args.limit)
        price_stats = import_mtgjson_prices(args.db, args.prices_json, args.limit, args.source_name)
        print(f"snapshot: {snapshot['snapshot_path']}")
        print_stats("import-scryfall", scryfall_stats)
        print_stats("import-identifiers", identifier_stats)
        print_stats("import-prices", price_stats)
        return

    if args.command == "sync-bulk":
        snapshot = create_database_snapshot(args.db, label="before_sync_bulk")
        result = sync_bulk(
            args.db,
            cache_dir=args.cache_dir,
            scryfall_metadata_url=args.scryfall_metadata_url,
            scryfall_bulk_type=args.scryfall_bulk_type,
            mtgjson_identifiers_url=args.mtgjson_identifiers_url,
            mtgjson_prices_url=args.mtgjson_prices_url,
            limit=args.limit,
            source_name=args.source_name,
        )
        result["snapshot"] = snapshot
        print_sync_bulk_result(result)
        return

    parser.error(f"Unknown command {args.command}")

