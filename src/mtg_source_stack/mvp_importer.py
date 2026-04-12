from .cli.importer import build_parser, main
from .db.connection import DEFAULT_DB_PATH, connect
from .db.schema import column_exists, ensure_schema_upgrades, initialize_database, load_schema_sql
from .db.snapshots import (
    DEFAULT_SNAPSHOT_SUBDIR,
    SNAPSHOT_FILE_SUFFIX,
    build_snapshot_info,
    create_database_snapshot,
    derive_snapshot_label,
    list_database_snapshots,
    next_snapshot_path,
    parse_snapshot_created_at,
    resolve_snapshot_path,
    restore_database_snapshot,
    slugify_snapshot_label,
    snapshot_dir_for_db,
    snapshot_metadata_path,
    snapshot_timestamp,
)
from .importer.mtgjson import import_mtgjson_identifiers, import_mtgjson_prices
from .importer.scryfall import import_scryfall_cards, iter_scryfall_cards, pick_image_uris, pick_oracle_id
from .importer.service import (
    DEFAULT_BULK_CACHE_DIR,
    DEFAULT_SCRYFALL_BULK_TYPE,
    HTTP_HEADERS,
    MTGJSON_IDENTIFIERS_URL,
    MTGJSON_PRICES_URL,
    SCRYFALL_BULK_METADATA_URL,
    DownloadResult,
    ImportStats,
    compact_json,
    download_to_path,
    find_scryfall_bulk_download_url,
    first_non_empty,
    format_bytes,
    format_snapshot_brief,
    load_json,
    load_json_url,
    open_text,
    open_url,
    print_restore_snapshot_result,
    print_snapshot_created,
    print_snapshot_list,
    print_stats,
    print_sync_result,
    print_sync_bulk_result,
    sync_identifiers,
    sync_prices,
    sync_scryfall,
    sync_bulk,
    text_or_none,
)


if __name__ == "__main__":
    main()
