from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_DB_PATH = Path("MtG Source Stack") / "mtg_mvp.db"
DEFAULT_BULK_CACHE_DIR = Path("MtG Source Stack") / "_bulk_cache" / "latest"
SCRYFALL_BULK_METADATA_URL = "https://api.scryfall.com/bulk-data"
DEFAULT_SCRYFALL_BULK_TYPE = "default_cards"
MTGJSON_IDENTIFIERS_URL = "https://mtgjson.com/api/v5/AllIdentifiers.json.gz"
MTGJSON_PRICES_URL = "https://mtgjson.com/api/v5/AllPricesToday.json.gz"
DEFAULT_SNAPSHOT_SUBDIR = "_snapshots"
SNAPSHOT_FILE_SUFFIX = ".sqlite3"
HTTP_HEADERS = {
    "User-Agent": "mtg-source-stack-sync/0.1 (+local bulk refresh)",
    "Accept": "application/json",
}


@dataclass(slots=True)
class ImportStats:
    rows_seen: int = 0
    rows_written: int = 0
    rows_skipped: int = 0


@dataclass(slots=True)
class DownloadResult:
    label: str
    url: str
    path: Path
    bytes_written: int


def snapshot_dir_for_db(db_path: str | Path, snapshot_dir: str | Path | None = None) -> Path:
    if snapshot_dir is not None:
        return Path(snapshot_dir)
    db_file = Path(db_path)
    return db_file.parent / DEFAULT_SNAPSHOT_SUBDIR / db_file.stem


def slugify_snapshot_label(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return normalized or "snapshot"


def snapshot_metadata_path(snapshot_path: str | Path) -> Path:
    path = Path(snapshot_path)
    return path.with_suffix(path.suffix + ".json")


def snapshot_timestamp(created_at: dt.datetime) -> str:
    return created_at.strftime("%Y%m%dT%H%M%SZ")


def parse_snapshot_created_at(snapshot_path: Path) -> str:
    match = re.match(r"(?P<stamp>\d{8}T\d{6}Z)__", snapshot_path.name)
    if match:
        try:
            parsed = dt.datetime.strptime(match.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
            return parsed.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    created_at = dt.datetime.fromtimestamp(snapshot_path.stat().st_mtime, tz=dt.timezone.utc)
    return created_at.isoformat().replace("+00:00", "Z")


def derive_snapshot_label(snapshot_path: Path) -> str:
    stem = snapshot_path.name
    if "__" in stem:
        stem = stem.split("__", 1)[1]
    if snapshot_path.suffix:
        stem = stem[: -len(snapshot_path.suffix)]
    return stem.replace("_", " ")


def next_snapshot_path(snapshot_dir: Path, *, label: str) -> tuple[Path, str]:
    created_at = dt.datetime.now(dt.timezone.utc)
    base_name = f"{snapshot_timestamp(created_at)}__{slugify_snapshot_label(label)}{SNAPSHOT_FILE_SUFFIX}"
    candidate = snapshot_dir / base_name
    counter = 2
    while candidate.exists():
        candidate = snapshot_dir / f"{base_name[:-len(SNAPSHOT_FILE_SUFFIX)]}_{counter}{SNAPSHOT_FILE_SUFFIX}"
        counter += 1
    return candidate, created_at.isoformat().replace("+00:00", "Z")


def build_snapshot_info(snapshot_path: str | Path, db_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(snapshot_path)
    info = {
        "snapshot_path": str(path),
        "snapshot_name": path.name,
        "metadata_path": str(snapshot_metadata_path(path)),
        "size_bytes": path.stat().st_size,
        "created_at": parse_snapshot_created_at(path),
        "label": derive_snapshot_label(path),
        "db_path": str(Path(db_path)) if db_path is not None else "",
    }

    metadata = snapshot_metadata_path(path)
    if metadata.exists():
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            info.update({key: value for key, value in payload.items() if value not in (None, "")})

    info["snapshot_path"] = str(path)
    info["snapshot_name"] = path.name
    info["metadata_path"] = str(metadata)
    info["size_bytes"] = path.stat().st_size
    return info


def create_database_snapshot(
    db_path: str | Path,
    *,
    label: str,
    snapshot_dir: str | Path | None = None,
) -> dict[str, Any]:
    initialize_database(db_path)
    db_file = Path(db_path)
    target_dir = snapshot_dir_for_db(db_file, snapshot_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path, created_at = next_snapshot_path(target_dir, label=label)

    with sqlite3.connect(db_file) as source, sqlite3.connect(snapshot_path) as destination:
        source.backup(destination)

    info = {
        "db_path": str(db_file),
        "snapshot_path": str(snapshot_path),
        "snapshot_name": snapshot_path.name,
        "label": label,
        "created_at": created_at,
        "size_bytes": snapshot_path.stat().st_size,
    }
    snapshot_metadata_path(snapshot_path).write_text(json.dumps(info, ensure_ascii=True, indent=2), encoding="utf-8")
    return info


def list_database_snapshots(
    db_path: str | Path,
    *,
    snapshot_dir: str | Path | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    target_dir = snapshot_dir_for_db(db_path, snapshot_dir)
    if not target_dir.exists():
        return []

    snapshots = [
        build_snapshot_info(path, db_path=db_path)
        for path in target_dir.iterdir()
        if path.is_file() and path.suffix == SNAPSHOT_FILE_SUFFIX
    ]
    snapshots.sort(key=lambda item: (item.get("created_at", ""), item.get("snapshot_name", "")), reverse=True)
    if limit is not None:
        snapshots = snapshots[:limit]
    return snapshots


def resolve_snapshot_path(
    db_path: str | Path,
    snapshot: str | Path,
    *,
    snapshot_dir: str | Path | None = None,
) -> Path:
    snapshot_path = Path(snapshot)
    if snapshot_path.exists():
        return snapshot_path

    candidate = snapshot_dir_for_db(db_path, snapshot_dir) / str(snapshot)
    if candidate.exists():
        return candidate

    raise ValueError(f"Could not find snapshot '{snapshot}'. Use list-snapshots to see available snapshots.")


def restore_database_snapshot(
    db_path: str | Path,
    *,
    snapshot: str | Path,
    snapshot_dir: str | Path | None = None,
    create_pre_restore_snapshot: bool = True,
) -> dict[str, Any]:
    db_file = Path(db_path)
    snapshot_path = resolve_snapshot_path(db_file, snapshot, snapshot_dir=snapshot_dir)
    pre_restore_snapshot = None

    if create_pre_restore_snapshot and db_file.exists():
        pre_restore_snapshot = create_database_snapshot(
            db_file,
            label=f"before_restore_{snapshot_path.stem}",
            snapshot_dir=snapshot_dir,
        )

    db_file.parent.mkdir(parents=True, exist_ok=True)
    temp_handle = tempfile.NamedTemporaryFile(
        prefix=f".{db_file.stem}_restore_",
        suffix=db_file.suffix or ".db",
        dir=db_file.parent,
        delete=False,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()

    try:
        with sqlite3.connect(snapshot_path) as source, sqlite3.connect(temp_path) as destination:
            source.backup(destination)
        temp_path.replace(db_file)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_file) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    initialize_database(db_file)
    restored_snapshot = build_snapshot_info(snapshot_path, db_path=db_file)
    return {
        "db_path": str(db_file),
        "snapshot_path": str(snapshot_path),
        "snapshot_name": snapshot_path.name,
        "restored_snapshot": restored_snapshot,
        "pre_restore_snapshot": pre_restore_snapshot,
    }


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def load_schema_sql() -> str:
    return files("mtg_source_stack").joinpath("mtg_mvp_schema.sql").read_text(encoding="utf-8")


def column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def ensure_schema_upgrades(connection: sqlite3.Connection) -> None:
    if not column_exists(connection, "inventory_items", "tags_json"):
        connection.execute(
            """
            ALTER TABLE inventory_items
            ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'
            """
        )
        connection.execute(
            """
            UPDATE inventory_items
            SET tags_json = '[]'
            WHERE tags_json IS NULL OR TRIM(tags_json) = ''
            """
        )


def initialize_database(db_path: str | Path) -> None:
    with connect(db_path) as connection:
        connection.executescript(load_schema_sql())
        ensure_schema_upgrades(connection)


def open_text(path: str | Path):
    file_path = Path(path)
    if file_path.suffix == ".gz":
        return gzip.open(file_path, mode="rt", encoding="utf-8")
    return file_path.open(mode="r", encoding="utf-8")


def load_json(path: str | Path) -> Any:
    with open_text(path) as handle:
        return json.load(handle)


def open_url(url: str, headers: dict[str, str] | None = None, timeout: int = 120):
    request = Request(url, headers=headers or {})
    return urlopen(request, timeout=timeout)


def load_json_url(url: str, headers: dict[str, str] | None = None, timeout: int = 120) -> Any:
    with open_url(url, headers=headers, timeout=timeout) as handle:
        return json.load(handle)


def download_to_path(
    url: str,
    destination: str | Path,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> DownloadResult:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open_url(url, headers=headers, timeout=timeout) as response, path.open("wb") as handle:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            total += len(chunk)
    return DownloadResult(
        label=path.name,
        url=url,
        path=path,
        bytes_written=total,
    )


def find_scryfall_bulk_download_url(
    metadata_url: str,
    *,
    bulk_type: str,
) -> str:
    payload = load_json_url(metadata_url, headers=HTTP_HEADERS, timeout=60)
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Expected Scryfall bulk metadata to contain a data list.")

    for item in payload["data"]:
        if not isinstance(item, dict):
            continue
        if item.get("type") == bulk_type:
            download_url = text_or_none(item.get("download_uri"))
            if download_url is None:
                raise ValueError(f"Scryfall bulk type '{bulk_type}' did not include a download_uri.")
            return download_url

    raise ValueError(f"Could not find Scryfall bulk type '{bulk_type}' in metadata.")


def format_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024.0 or unit == "GiB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} GiB"


def compact_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def first_non_empty(*values: Any) -> str | None:
    for value in values:
        text = text_or_none(value)
        if text is not None:
            return text
    return None


def pick_image_uris(card: dict[str, Any]) -> dict[str, Any] | None:
    image_uris = card.get("image_uris")
    if isinstance(image_uris, dict):
        return image_uris

    card_faces = card.get("card_faces")
    if isinstance(card_faces, list):
        for face in card_faces:
            if isinstance(face, dict) and isinstance(face.get("image_uris"), dict):
                return face["image_uris"]
    return None


def pick_oracle_id(card: dict[str, Any]) -> str | None:
    oracle_id = text_or_none(card.get("oracle_id"))
    if oracle_id is not None:
        return oracle_id

    card_faces = card.get("card_faces")
    if isinstance(card_faces, list):
        for face in card_faces:
            if isinstance(face, dict):
                oracle_id = text_or_none(face.get("oracle_id"))
                if oracle_id is not None:
                    return oracle_id
    return None


def iter_scryfall_cards(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    raise ValueError("Expected Scryfall bulk data to be a JSON list or an object with a data list.")


def import_scryfall_cards(db_path: str | Path, json_path: str | Path, limit: int | None = None) -> ImportStats:
    payload = load_json(json_path)
    cards = iter_scryfall_cards(payload)
    stats = ImportStats()

    sql = """
    INSERT INTO mtg_cards (
        scryfall_id,
        oracle_id,
        mtgjson_uuid,
        name,
        set_code,
        set_name,
        collector_number,
        lang,
        rarity,
        released_at,
        mana_cost,
        type_line,
        oracle_text,
        colors_json,
        color_identity_json,
        finishes_json,
        image_uris_json,
        legalities_json,
        purchase_uris_json,
        tcgplayer_product_id,
        cardkingdom_id,
        cardmarket_id,
        cardsphere_id
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(scryfall_id) DO UPDATE SET
        oracle_id = excluded.oracle_id,
        name = excluded.name,
        set_code = excluded.set_code,
        set_name = excluded.set_name,
        collector_number = excluded.collector_number,
        lang = excluded.lang,
        rarity = excluded.rarity,
        released_at = excluded.released_at,
        mana_cost = excluded.mana_cost,
        type_line = excluded.type_line,
        oracle_text = excluded.oracle_text,
        colors_json = excluded.colors_json,
        color_identity_json = excluded.color_identity_json,
        finishes_json = excluded.finishes_json,
        image_uris_json = excluded.image_uris_json,
        legalities_json = excluded.legalities_json,
        purchase_uris_json = excluded.purchase_uris_json,
        mtgjson_uuid = COALESCE(excluded.mtgjson_uuid, mtg_cards.mtgjson_uuid),
        tcgplayer_product_id = COALESCE(excluded.tcgplayer_product_id, mtg_cards.tcgplayer_product_id),
        cardkingdom_id = COALESCE(excluded.cardkingdom_id, mtg_cards.cardkingdom_id),
        cardmarket_id = COALESCE(excluded.cardmarket_id, mtg_cards.cardmarket_id),
        cardsphere_id = COALESCE(excluded.cardsphere_id, mtg_cards.cardsphere_id),
        updated_at = CURRENT_TIMESTAMP
    """

    with connect(db_path) as connection:
        for index, card in enumerate(cards, start=1):
            if limit is not None and index > limit:
                break

            stats.rows_seen += 1
            scryfall_id = text_or_none(card.get("id"))
            oracle_id = pick_oracle_id(card)
            set_code = text_or_none(card.get("set"))
            set_name = text_or_none(card.get("set_name"))
            collector_number = text_or_none(card.get("collector_number"))
            name = text_or_none(card.get("name"))

            if not all([scryfall_id, oracle_id, set_code, set_name, collector_number, name]):
                stats.rows_skipped += 1
                continue

            connection.execute(
                sql,
                (
                    scryfall_id,
                    oracle_id,
                    None,
                    name,
                    set_code,
                    set_name,
                    collector_number,
                    first_non_empty(card.get("lang"), "en"),
                    text_or_none(card.get("rarity")),
                    text_or_none(card.get("released_at")),
                    text_or_none(card.get("mana_cost")),
                    text_or_none(card.get("type_line")),
                    text_or_none(card.get("oracle_text")),
                    compact_json(card.get("colors") or []),
                    compact_json(card.get("color_identity") or []),
                    compact_json(card.get("finishes") or []),
                    compact_json(pick_image_uris(card)),
                    compact_json(card.get("legalities") or {}),
                    compact_json(card.get("purchase_uris") or {}),
                    text_or_none(card.get("tcgplayer_id")),
                    None,
                    text_or_none(card.get("cardmarket_id")),
                    None,
                ),
            )
            stats.rows_written += 1

        connection.commit()

    return stats


def import_mtgjson_identifiers(db_path: str | Path, json_path: str | Path, limit: int | None = None) -> ImportStats:
    payload = load_json(json_path)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("Expected MTGJSON identifiers to contain an object at payload['data'].")

    stats = ImportStats()

    with connect(db_path) as connection:
        for index, (uuid, identifier_record) in enumerate(data.items(), start=1):
            if limit is not None and index > limit:
                break

            stats.rows_seen += 1
            if not isinstance(identifier_record, dict):
                stats.rows_skipped += 1
                continue

            identifiers = identifier_record.get("identifiers")
            if not isinstance(identifiers, dict):
                identifiers = identifier_record

            scryfall_id = text_or_none(identifiers.get("scryfallId"))
            mtgjson_uuid = text_or_none(uuid)

            if scryfall_id is not None:
                cursor = connection.execute(
                    """
                    UPDATE mtg_cards
                    SET
                        mtgjson_uuid = COALESCE(?, mtgjson_uuid),
                        tcgplayer_product_id = COALESCE(?, tcgplayer_product_id),
                        cardkingdom_id = COALESCE(?, cardkingdom_id),
                        cardmarket_id = COALESCE(?, cardmarket_id),
                        cardsphere_id = COALESCE(?, cardsphere_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE scryfall_id = ?
                    """,
                    (
                        mtgjson_uuid,
                        first_non_empty(
                            identifiers.get("tcgplayerProductId"),
                            identifiers.get("tcgplayerEtchedProductId"),
                            identifiers.get("tcgplayerAlternativeFoilProductId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardKingdomId"),
                            identifiers.get("cardKingdomFoilId"),
                            identifiers.get("cardKingdomEtchedId"),
                        ),
                        first_non_empty(
                            identifiers.get("mcmId"),
                            identifiers.get("mcmMetaId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardsphereId"),
                            identifiers.get("cardsphereFoilId"),
                        ),
                        scryfall_id,
                    ),
                )
                if cursor.rowcount:
                    stats.rows_written += 1
                else:
                    stats.rows_skipped += 1
                continue

            if mtgjson_uuid is not None:
                cursor = connection.execute(
                    """
                    UPDATE mtg_cards
                    SET
                        tcgplayer_product_id = COALESCE(?, tcgplayer_product_id),
                        cardkingdom_id = COALESCE(?, cardkingdom_id),
                        cardmarket_id = COALESCE(?, cardmarket_id),
                        cardsphere_id = COALESCE(?, cardsphere_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE mtgjson_uuid = ?
                    """,
                    (
                        first_non_empty(
                            identifiers.get("tcgplayerProductId"),
                            identifiers.get("tcgplayerEtchedProductId"),
                            identifiers.get("tcgplayerAlternativeFoilProductId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardKingdomId"),
                            identifiers.get("cardKingdomFoilId"),
                            identifiers.get("cardKingdomEtchedId"),
                        ),
                        first_non_empty(
                            identifiers.get("mcmId"),
                            identifiers.get("mcmMetaId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardsphereId"),
                            identifiers.get("cardsphereFoilId"),
                        ),
                        mtgjson_uuid,
                    ),
                )
                if cursor.rowcount:
                    stats.rows_written += 1
                else:
                    stats.rows_skipped += 1
                continue

            stats.rows_skipped += 1

        connection.commit()

    return stats


def import_mtgjson_prices(
    db_path: str | Path,
    json_path: str | Path,
    limit: int | None = None,
    source_name: str = "mtgjson_all_prices_today",
) -> ImportStats:
    payload = load_json(json_path)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("Expected MTGJSON prices to contain an object at payload['data'].")

    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT mtgjson_uuid, scryfall_id
            FROM mtg_cards
            WHERE mtgjson_uuid IS NOT NULL
            """
        ).fetchall()
        uuid_to_scryfall = {row["mtgjson_uuid"]: row["scryfall_id"] for row in rows}

    stats = ImportStats()

    sql = """
    INSERT INTO price_snapshots (
        scryfall_id,
        provider,
        price_kind,
        finish,
        currency,
        snapshot_date,
        price_value,
        source_name
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(
        scryfall_id,
        provider,
        price_kind,
        finish,
        currency,
        snapshot_date,
        source_name
    ) DO UPDATE SET
        price_value = excluded.price_value
    """

    with connect(db_path) as connection:
        for index, (uuid, price_formats) in enumerate(data.items(), start=1):
            if limit is not None and index > limit:
                break

            stats.rows_seen += 1
            if not isinstance(price_formats, dict):
                stats.rows_skipped += 1
                continue

            scryfall_id = uuid_to_scryfall.get(str(uuid))
            if scryfall_id is None:
                stats.rows_skipped += 1
                continue

            wrote_for_card = False
            for channel_payload in price_formats.values():
                if not isinstance(channel_payload, dict):
                    continue

                for provider, provider_payload in channel_payload.items():
                    if not isinstance(provider_payload, dict):
                        continue

                    currency = first_non_empty(provider_payload.get("currency"), "USD")
                    for price_kind in ("retail", "buylist"):
                        price_points = provider_payload.get(price_kind)
                        if not isinstance(price_points, dict):
                            continue

                        for finish, dated_points in price_points.items():
                            if isinstance(dated_points, dict):
                                items = dated_points.items()
                            else:
                                items = []

                            for snapshot_date, price_value in items:
                                if not isinstance(price_value, (int, float)):
                                    continue

                                connection.execute(
                                    sql,
                                    (
                                        scryfall_id,
                                        provider,
                                        price_kind,
                                        str(finish),
                                        currency,
                                        str(snapshot_date),
                                        float(price_value),
                                        source_name,
                                    ),
                                )
                                wrote_for_card = True
                                stats.rows_written += 1

            if not wrote_for_card:
                stats.rows_skipped += 1

        connection.commit()

    return stats


def print_stats(label: str, stats: ImportStats) -> None:
    print(f"{label}: seen={stats.rows_seen} written={stats.rows_written} skipped={stats.rows_skipped}")


def format_snapshot_brief(snapshot: dict[str, Any]) -> str:
    return f"{snapshot['snapshot_name']} ({format_bytes(int(snapshot['size_bytes']))})"


def print_snapshot_created(snapshot: dict[str, Any]) -> None:
    print("Safety snapshot created")
    print(f"database: {snapshot['db_path']}")
    print(f"label: {snapshot['label']}")
    print(f"snapshot: {snapshot['snapshot_path']}")
    print(f"size: {format_bytes(int(snapshot['size_bytes']))}")


def print_snapshot_list(snapshots: list[dict[str, Any]]) -> None:
    if not snapshots:
        print("No snapshots found.")
        return

    print("Available snapshots")
    for snapshot in snapshots:
        print(
            f"{snapshot['snapshot_name']}  "
            f"{snapshot.get('created_at', '')}  "
            f"{format_bytes(int(snapshot['size_bytes']))}  "
            f"{snapshot.get('label', '')}"
        )


def print_restore_snapshot_result(result: dict[str, Any]) -> None:
    print("Restored snapshot")
    print(f"database: {result['db_path']}")
    print(f"snapshot: {result['snapshot_path']}")
    print(f"restored_from: {format_snapshot_brief(result['restored_snapshot'])}")
    if result.get("pre_restore_snapshot") is not None:
        pre_restore_snapshot = result["pre_restore_snapshot"]
        print(f"pre_restore_snapshot: {pre_restore_snapshot['snapshot_path']}")


def sync_bulk(
    db_path: str | Path,
    *,
    cache_dir: str | Path,
    scryfall_metadata_url: str = SCRYFALL_BULK_METADATA_URL,
    scryfall_bulk_type: str = DEFAULT_SCRYFALL_BULK_TYPE,
    mtgjson_identifiers_url: str = MTGJSON_IDENTIFIERS_URL,
    mtgjson_prices_url: str = MTGJSON_PRICES_URL,
    limit: int | None = None,
    source_name: str = "mtgjson_all_prices_today",
) -> dict[str, Any]:
    initialize_database(db_path)

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    scryfall_download_url = find_scryfall_bulk_download_url(
        scryfall_metadata_url,
        bulk_type=scryfall_bulk_type,
    )

    downloads = [
        download_to_path(
            scryfall_download_url,
            cache_path / "scryfall_default_cards.json",
            headers=HTTP_HEADERS,
            timeout=300,
        ),
        download_to_path(
            mtgjson_identifiers_url,
            cache_path / "AllIdentifiers.json.gz",
            headers=HTTP_HEADERS,
            timeout=300,
        ),
        download_to_path(
            mtgjson_prices_url,
            cache_path / "AllPricesToday.json.gz",
            headers=HTTP_HEADERS,
            timeout=300,
        ),
    ]

    scryfall_stats = import_scryfall_cards(db_path, downloads[0].path, limit)
    identifier_stats = import_mtgjson_identifiers(db_path, downloads[1].path, limit)
    price_stats = import_mtgjson_prices(db_path, downloads[2].path, limit, source_name)

    return {
        "db_path": str(Path(db_path)),
        "cache_dir": str(cache_path),
        "downloads": downloads,
        "scryfall_stats": scryfall_stats,
        "identifier_stats": identifier_stats,
        "price_stats": price_stats,
        "source_name": source_name,
        "scryfall_bulk_type": scryfall_bulk_type,
    }


def print_sync_bulk_result(result: dict[str, Any]) -> None:
    print("sync-bulk completed")
    print(f"database: {result['db_path']}")
    if result.get("snapshot") is not None:
        print(f"snapshot: {result['snapshot']['snapshot_path']}")
    print(f"cache_dir: {result['cache_dir']}")
    print("downloads:")
    for download in result["downloads"]:
        print(f"  {download.label}: {download.path} ({format_bytes(download.bytes_written)})")
    print_stats("import-scryfall", result["scryfall_stats"])
    print_stats("import-identifiers", result["identifier_stats"])
    print_stats("import-prices", result["price_stats"])


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
    sync_bulk_parser.add_argument(
        "--limit",
        type=int,
        help="Optional max number of rows per import step.",
    )
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


if __name__ == "__main__":
    main()
