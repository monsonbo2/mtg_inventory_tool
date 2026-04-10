"""Helpers for bulk-download orchestration and importer CLI output."""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

DEFAULT_BULK_CACHE_DIR = Path("var") / "bulk_cache" / "latest"
SCRYFALL_BULK_METADATA_URL = "https://api.scryfall.com/bulk-data"
DEFAULT_SCRYFALL_BULK_TYPE = "default_cards"
MTGJSON_IDENTIFIERS_URL = "https://mtgjson.com/api/v5/AllIdentifiers.json.gz"
MTGJSON_PRICES_URL = "https://mtgjson.com/api/v5/AllPricesToday.json.gz"
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
    sha256: str
    etag: str | None
    last_modified: str | None


def open_text(path: str | Path):
    file_path = Path(path)
    # MTGJSON payloads are often shipped as gzip files; callers should not need
    # to care whether a fixture or download is compressed.
    if file_path.suffix == ".gz":
        return gzip.open(file_path, mode="rt", encoding="utf-8")
    return file_path.open(mode="r", encoding="utf-8")


def load_json(path: str | Path) -> Any:
    try:
        with open_text(path) as handle:
            return json.load(handle)
    except OSError as exc:
        raise ValueError(f"Could not read JSON file '{path}'.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse JSON file '{path}': {exc.msg} at line {exc.lineno}, column {exc.colno}."
        ) from exc


def open_url(url: str, headers: dict[str, str] | None = None, timeout: int = 120):
    request = Request(url, headers=headers or {})
    return urlopen(request, timeout=timeout)


def load_json_url(url: str, headers: dict[str, str] | None = None, timeout: int = 120) -> Any:
    try:
        with open_url(url, headers=headers, timeout=timeout) as handle:
            return json.load(handle)
    except OSError as exc:
        raise ValueError(f"Could not read JSON from URL '{url}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse JSON from URL '{url}': {exc.msg} at line {exc.lineno}, column {exc.colno}."
        ) from exc


def download_to_path(
    url: str,
    destination: str | Path,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
) -> DownloadResult:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    with open_url(url, headers=headers, timeout=timeout) as response, path.open("wb") as handle:
        total = 0
        response_headers = response.headers
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            digest.update(chunk)
            total += len(chunk)
    return DownloadResult(
        label=path.name,
        url=url,
        path=path,
        bytes_written=total,
        sha256=digest.hexdigest(),
        etag=response_headers.get("ETag"),
        last_modified=response_headers.get("Last-Modified"),
    )


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


def compact_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


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
    before_write: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    from .mtgjson import import_mtgjson_identifiers, import_mtgjson_prices
    from .scryfall import import_scryfall_cards

    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)

    scryfall_download_url = find_scryfall_bulk_download_url(
        scryfall_metadata_url,
        bulk_type=scryfall_bulk_type,
    )

    # Download first and import from the cached artifacts so reruns can inspect
    # the exact files that were used to populate the database.
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

    # The imports are ordered to establish catalog rows first, then enrich them
    # with identifier crosswalks, and finally attach price snapshots.
    scryfall_started = time.perf_counter()
    scryfall_stats = import_scryfall_cards(db_path, downloads[0].path, limit, before_write=before_write)
    scryfall_elapsed_seconds = time.perf_counter() - scryfall_started

    identifier_started = time.perf_counter()
    identifier_stats = import_mtgjson_identifiers(db_path, downloads[1].path, limit, before_write=before_write)
    identifier_elapsed_seconds = time.perf_counter() - identifier_started

    price_started = time.perf_counter()
    price_stats = import_mtgjson_prices(db_path, downloads[2].path, limit, source_name, before_write=before_write)
    price_elapsed_seconds = time.perf_counter() - price_started

    return {
        "db_path": str(Path(db_path)),
        "cache_dir": str(cache_path),
        "downloads": downloads,
        "scryfall_stats": scryfall_stats,
        "scryfall_elapsed_seconds": scryfall_elapsed_seconds,
        "identifier_stats": identifier_stats,
        "identifier_elapsed_seconds": identifier_elapsed_seconds,
        "price_stats": price_stats,
        "price_elapsed_seconds": price_elapsed_seconds,
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
