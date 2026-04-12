"""Helpers for bulk-download orchestration and importer CLI output."""

from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, TextIO
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
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
SCRYFALL_BULK_METADATA_CACHE_FILENAME = "scryfall_bulk_metadata.json"
SCRYFALL_BULK_CACHE_FILENAME = "scryfall_default_cards.json"
MTGJSON_IDENTIFIERS_CACHE_FILENAME = "AllIdentifiers.json.gz"
MTGJSON_PRICES_CACHE_FILENAME = "AllPricesToday.json.gz"


@dataclass(slots=True)
class ImportStats:
    rows_seen: int = 0
    rows_written: int = 0
    rows_skipped: int = 0
    details: dict[str, Any] | None = None


@dataclass(slots=True)
class DownloadResult:
    label: str
    url: str
    path: Path
    bytes_written: int
    sha256: str
    etag: str | None
    last_modified: str | None
    downloaded: bool


def _merge_import_stats_details(
    stats: ImportStats,
    extra_details: dict[str, Any] | None = None,
) -> ImportStats:
    merged: dict[str, Any] = {}
    if isinstance(stats.details, dict):
        merged.update(stats.details)
    if extra_details:
        merged.update(extra_details)
    stats.details = merged or None
    return stats


def file_digest_info(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return {
        "path": file_path,
        "bytes_written": file_path.stat().st_size,
        "sha256": digest.hexdigest(),
        "last_modified": str(int(file_path.stat().st_mtime)),
    }


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


class _JsonValueStream:
    def __init__(self, handle: TextIO, *, chunk_size: int = 1024 * 1024) -> None:
        self._handle = handle
        self._chunk_size = chunk_size
        self._decoder = json.JSONDecoder()
        self._buffer = ""
        self._position = 0
        self._eof = False

    def _read_more(self) -> bool:
        if self._eof:
            return False
        chunk = self._handle.read(self._chunk_size)
        if chunk == "":
            self._eof = True
            return False
        self._buffer += chunk
        return True

    def _compact(self) -> None:
        if self._position > self._chunk_size:
            self._buffer = self._buffer[self._position :]
            self._position = 0

    def _ensure_buffered(self) -> bool:
        while self._position >= len(self._buffer):
            if not self._read_more():
                return False
        return True

    def skip_whitespace(self) -> None:
        while True:
            if not self._ensure_buffered():
                return
            start = self._position
            while self._position < len(self._buffer) and self._buffer[self._position].isspace():
                self._position += 1
            if self._position < len(self._buffer) or self._eof:
                self._compact()
                return
            if self._position == start and not self._read_more():
                return

    def _require_char(self, expected: str) -> None:
        self.skip_whitespace()
        if not self._ensure_buffered():
            raise ValueError("Unexpected end of JSON input.")
        actual = self._buffer[self._position]
        if actual != expected:
            raise ValueError(f"Expected '{expected}' in JSON input, found '{actual}'.")
        self._position += 1
        self._compact()

    def _consume_char(self, expected: str) -> bool:
        self.skip_whitespace()
        if not self._ensure_buffered():
            return False
        if self._buffer[self._position] != expected:
            return False
        self._position += 1
        self._compact()
        return True

    def peek_char(self) -> str:
        self.skip_whitespace()
        if not self._ensure_buffered():
            raise ValueError("Unexpected end of JSON input.")
        return self._buffer[self._position]

    def decode_value(self) -> Any:
        self.skip_whitespace()
        while True:
            if not self._ensure_buffered():
                raise ValueError("Unexpected end of JSON input.")
            try:
                value, end = self._decoder.raw_decode(self._buffer, self._position)
            except json.JSONDecodeError as exc:
                if not self._read_more():
                    raise ValueError(f"Could not parse JSON input: {exc.msg}.") from exc
                continue
            self._position = end
            self._compact()
            return value

    def ensure_root_object(self) -> None:
        self._require_char("{")

    def ensure_input_consumed(self) -> None:
        self.skip_whitespace()
        if self._ensure_buffered():
            raise ValueError("Expected end of JSON input after top-level object.")

    def iter_object_items(self) -> Iterator[tuple[str, Any]]:
        self._require_char("{")
        if self._consume_char("}"):
            return
        while True:
            key = self.decode_value()
            if not isinstance(key, str):
                raise ValueError("Expected object keys in JSON input to be strings.")
            self._require_char(":")
            value = self.decode_value()
            yield key, value
            if self._consume_char(","):
                continue
            self._require_char("}")
            return


def iter_json_object_items(
    path: str | Path,
    *,
    top_level_key: str,
) -> Iterator[tuple[str, Any]]:
    try:
        with open_text(path) as handle:
            stream = _JsonValueStream(handle)
            stream.ensure_root_object()
            found_key = False
            if stream._consume_char("}"):
                raise ValueError(f"Expected JSON object to contain an object at payload['{top_level_key}'].")
            while True:
                key = stream.decode_value()
                if not isinstance(key, str):
                    raise ValueError("Expected object keys in JSON input to be strings.")
                stream._require_char(":")
                if key == top_level_key:
                    if stream.peek_char() != "{":
                        raise ValueError(
                            f"Expected JSON object to contain an object at payload['{top_level_key}']."
                        )
                    found_key = True
                    yield from stream.iter_object_items()
                else:
                    stream.decode_value()
                if stream._consume_char(","):
                    continue
                stream._require_char("}")
                break
            if not found_key:
                raise ValueError(f"Expected JSON object to contain an object at payload['{top_level_key}'].")
            stream.ensure_input_consumed()
    except OSError as exc:
        raise ValueError(f"Could not read JSON file '{path}'.") from exc


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
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> DownloadResult:
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    parsed_url = urlparse(url)
    if parsed_url.scheme == "file":
        source_path = Path(unquote(parsed_url.path))
        source_info = file_digest_info(source_path)
        if path.exists():
            destination_info = file_digest_info(path)
            if destination_info["sha256"] == source_info["sha256"]:
                return DownloadResult(
                    label=path.name,
                    url=url,
                    path=path,
                    bytes_written=destination_info["bytes_written"],
                    sha256=destination_info["sha256"],
                    etag=None,
                    last_modified=source_info["last_modified"],
                    downloaded=False,
                )
        with source_path.open("rb") as source_handle, path.open("wb") as destination_handle:
            while True:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    break
                destination_handle.write(chunk)
        destination_info = file_digest_info(path)
        return DownloadResult(
            label=path.name,
            url=url,
            path=path,
            bytes_written=destination_info["bytes_written"],
            sha256=destination_info["sha256"],
            etag=None,
            last_modified=source_info["last_modified"],
            downloaded=True,
        )

    digest = hashlib.sha256()
    request_headers = dict(headers or {})
    if path.exists():
        if if_none_match is not None:
            request_headers["If-None-Match"] = if_none_match
        if if_modified_since is not None:
            request_headers["If-Modified-Since"] = if_modified_since
    try:
        response_context = open_url(url, headers=request_headers, timeout=timeout)
    except HTTPError as exc:
        if exc.code == 304 and path.exists():
            destination_info = file_digest_info(path)
            return DownloadResult(
                label=path.name,
                url=url,
                path=path,
                bytes_written=destination_info["bytes_written"],
                sha256=destination_info["sha256"],
                etag=exc.headers.get("ETag") or if_none_match,
                last_modified=exc.headers.get("Last-Modified") or if_modified_since,
                downloaded=False,
            )
        raise
    with response_context as response, path.open("wb") as handle:
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
        downloaded=True,
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
    return find_scryfall_bulk_download_url_from_payload(payload, bulk_type=bulk_type)


def find_scryfall_bulk_download_url_from_payload(
    payload: Any,
    *,
    bulk_type: str,
) -> str:
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


def find_scryfall_bulk_download_url_in_file(
    metadata_path: str | Path,
    *,
    bulk_type: str,
) -> str:
    payload = load_json(metadata_path)
    return find_scryfall_bulk_download_url_from_payload(payload, bulk_type=bulk_type)


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
    summary = f"{label}: seen={stats.rows_seen} written={stats.rows_written} skipped={stats.rows_skipped}"
    skip_reason = None
    elapsed_seconds = None
    phase_seconds = None
    detail_parts: list[str] = []
    if isinstance(stats.details, dict):
        skip_reason = stats.details.get("skip_reason")
        elapsed_seconds = stats.details.get("elapsed_seconds")
        phase_seconds = stats.details.get("phase_seconds")
        for detail_key in (
            "matched_cards",
            "changed_cards",
            "no_op_cards",
            "staged_link_rows",
            "link_rows_written",
            "merged_price_rows",
            "conflict_rows",
        ):
            if detail_key in stats.details:
                detail_parts.append(f"{detail_key}={stats.details[detail_key]}")
    if skip_reason:
        summary = f"{summary} ({skip_reason})"
    print(summary)
    if isinstance(elapsed_seconds, (int, float)):
        print(f"  elapsed: {elapsed_seconds:.3f}s")
    if isinstance(phase_seconds, dict) and phase_seconds:
        phase_summary = " ".join(
            f"{phase_name}={float(seconds):.3f}s"
            for phase_name, seconds in phase_seconds.items()
            if isinstance(seconds, (int, float))
        )
        if phase_summary:
            print(f"  phases: {phase_summary}")
    if detail_parts:
        print(f"  details: {' '.join(detail_parts)}")


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


def _ensure_cache_dir(cache_dir: str | Path) -> Path:
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    return cache_path


def _download_sync_artifact(
    url: str,
    destination: str | Path,
    *,
    on_download: Callable[[DownloadResult], None] | None = None,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> DownloadResult:
    download = download_to_path(
        url,
        destination,
        headers=HTTP_HEADERS,
        timeout=300,
        if_none_match=if_none_match,
        if_modified_since=if_modified_since,
    )
    if on_download is not None:
        on_download(download)
    return download


def _download_scryfall_metadata(
    metadata_url: str,
    destination: str | Path,
    *,
    bulk_type: str,
    on_download: Callable[[DownloadResult], None] | None = None,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> tuple[DownloadResult, str]:
    metadata_download = _download_sync_artifact(
        metadata_url,
        destination,
        on_download=on_download,
        if_none_match=if_none_match,
        if_modified_since=if_modified_since,
    )
    download_url = find_scryfall_bulk_download_url_in_file(metadata_download.path, bulk_type=bulk_type)
    return metadata_download, download_url


def _run_sync_step(
    step_name: str,
    operation: Callable[[], ImportStats],
    *,
    on_step: Callable[[str, str, ImportStats | None, float, Exception | None], None] | None = None,
) -> tuple[ImportStats, float]:
    started = time.perf_counter()
    try:
        stats = operation()
    except Exception as exc:
        elapsed_seconds = time.perf_counter() - started
        if on_step is not None:
            on_step(step_name, "failed", None, elapsed_seconds, exc)
        raise
    elapsed_seconds = time.perf_counter() - started
    _merge_import_stats_details(stats, {"elapsed_seconds": round(elapsed_seconds, 6)})
    if on_step is not None:
        on_step(step_name, "succeeded", stats, elapsed_seconds, None)
    return stats, elapsed_seconds


def _run_or_skip_sync_step(
    step_name: str,
    download: DownloadResult,
    operation: Callable[[], ImportStats],
    *,
    should_skip_step: Callable[[str, DownloadResult], str | None] | None = None,
    on_step: Callable[[str, str, ImportStats | None, float, Exception | None], None] | None = None,
) -> tuple[ImportStats, float]:
    skip_reason = should_skip_step(step_name, download) if should_skip_step is not None else None
    if skip_reason is not None:
        stats = ImportStats(details={"skip_reason": skip_reason})
        elapsed_seconds = 0.0
        _merge_import_stats_details(stats, {"elapsed_seconds": round(elapsed_seconds, 6)})
        if on_step is not None:
            on_step(step_name, "skipped", stats, elapsed_seconds, None)
        return stats, elapsed_seconds
    return _run_sync_step(step_name, operation, on_step=on_step)


def sync_scryfall(
    db_path: str | Path,
    *,
    cache_dir: str | Path,
    scryfall_metadata_url: str = SCRYFALL_BULK_METADATA_URL,
    scryfall_bulk_type: str = DEFAULT_SCRYFALL_BULK_TYPE,
    limit: int | None = None,
    before_write: Callable[[], Any] | None = None,
    on_download: Callable[[DownloadResult], None] | None = None,
    on_step: Callable[[str, str, ImportStats | None, float, Exception | None], None] | None = None,
    should_skip_step: Callable[[str, DownloadResult], str | None] | None = None,
    metadata_if_none_match: str | None = None,
    metadata_if_modified_since: str | None = None,
    bulk_if_none_match: str | None = None,
    bulk_if_modified_since: str | None = None,
) -> dict[str, Any]:
    from .scryfall import import_scryfall_cards

    cache_path = _ensure_cache_dir(cache_dir)
    metadata_download, scryfall_download_url = _download_scryfall_metadata(
        scryfall_metadata_url,
        cache_path / SCRYFALL_BULK_METADATA_CACHE_FILENAME,
        bulk_type=scryfall_bulk_type,
        on_download=on_download,
        if_none_match=metadata_if_none_match,
        if_modified_since=metadata_if_modified_since,
    )
    download = _download_sync_artifact(
        scryfall_download_url,
        cache_path / SCRYFALL_BULK_CACHE_FILENAME,
        on_download=on_download,
        if_none_match=bulk_if_none_match,
        if_modified_since=bulk_if_modified_since,
    )
    scryfall_stats, scryfall_elapsed_seconds = _run_or_skip_sync_step(
        "import_scryfall",
        download,
        lambda: import_scryfall_cards(db_path, download.path, limit, before_write=before_write),
        should_skip_step=should_skip_step,
        on_step=on_step,
    )
    return {
        "db_path": str(Path(db_path)),
        "cache_dir": str(cache_path),
        "downloads": [metadata_download, download],
        "scryfall_stats": scryfall_stats,
        "scryfall_elapsed_seconds": scryfall_elapsed_seconds,
        "scryfall_bulk_type": scryfall_bulk_type,
    }


def sync_identifiers(
    db_path: str | Path,
    *,
    cache_dir: str | Path,
    mtgjson_identifiers_url: str = MTGJSON_IDENTIFIERS_URL,
    limit: int | None = None,
    before_write: Callable[[], Any] | None = None,
    on_download: Callable[[DownloadResult], None] | None = None,
    on_step: Callable[[str, str, ImportStats | None, float, Exception | None], None] | None = None,
    should_skip_step: Callable[[str, DownloadResult], str | None] | None = None,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> dict[str, Any]:
    from .mtgjson import import_mtgjson_identifiers

    cache_path = _ensure_cache_dir(cache_dir)
    download = _download_sync_artifact(
        mtgjson_identifiers_url,
        cache_path / MTGJSON_IDENTIFIERS_CACHE_FILENAME,
        on_download=on_download,
        if_none_match=if_none_match,
        if_modified_since=if_modified_since,
    )
    identifier_stats, identifier_elapsed_seconds = _run_or_skip_sync_step(
        "import_identifiers",
        download,
        lambda: import_mtgjson_identifiers(db_path, download.path, limit, before_write=before_write),
        should_skip_step=should_skip_step,
        on_step=on_step,
    )
    return {
        "db_path": str(Path(db_path)),
        "cache_dir": str(cache_path),
        "downloads": [download],
        "identifier_stats": identifier_stats,
        "identifier_elapsed_seconds": identifier_elapsed_seconds,
    }


def sync_prices(
    db_path: str | Path,
    *,
    cache_dir: str | Path,
    mtgjson_prices_url: str = MTGJSON_PRICES_URL,
    limit: int | None = None,
    source_name: str = "mtgjson_all_prices_today",
    before_write: Callable[[], Any] | None = None,
    on_download: Callable[[DownloadResult], None] | None = None,
    on_step: Callable[[str, str, ImportStats | None, float, Exception | None], None] | None = None,
    should_skip_step: Callable[[str, DownloadResult], str | None] | None = None,
    if_none_match: str | None = None,
    if_modified_since: str | None = None,
) -> dict[str, Any]:
    from .mtgjson import import_mtgjson_prices

    cache_path = _ensure_cache_dir(cache_dir)
    download = _download_sync_artifact(
        mtgjson_prices_url,
        cache_path / MTGJSON_PRICES_CACHE_FILENAME,
        on_download=on_download,
        if_none_match=if_none_match,
        if_modified_since=if_modified_since,
    )
    price_stats, price_elapsed_seconds = _run_or_skip_sync_step(
        "import_prices",
        download,
        lambda: import_mtgjson_prices(db_path, download.path, limit, source_name, before_write=before_write),
        should_skip_step=should_skip_step,
        on_step=on_step,
    )
    return {
        "db_path": str(Path(db_path)),
        "cache_dir": str(cache_path),
        "downloads": [download],
        "price_stats": price_stats,
        "price_elapsed_seconds": price_elapsed_seconds,
        "source_name": source_name,
    }


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
    on_download: Callable[[DownloadResult], None] | None = None,
    on_step: Callable[[str, str, ImportStats | None, float, Exception | None], None] | None = None,
    should_skip_step: Callable[[str, DownloadResult], str | None] | None = None,
    download_hints: dict[str, dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    from .mtgjson import import_mtgjson_identifiers, import_mtgjson_prices
    from .scryfall import import_scryfall_cards

    cache_path = _ensure_cache_dir(cache_dir)

    # Download first and import from the cached artifacts so reruns can inspect
    # the exact files that were used to populate the database.
    downloads: list[DownloadResult] = []
    metadata_hints = (download_hints or {}).get(SCRYFALL_BULK_METADATA_CACHE_FILENAME, {})
    metadata_download, scryfall_download_url = _download_scryfall_metadata(
        scryfall_metadata_url,
        cache_path / SCRYFALL_BULK_METADATA_CACHE_FILENAME,
        bulk_type=scryfall_bulk_type,
        on_download=on_download,
        if_none_match=metadata_hints.get("etag"),
        if_modified_since=metadata_hints.get("last_modified"),
    )
    downloads.append(metadata_download)
    bulk_downloads: list[DownloadResult] = []
    for download_url, destination in (
        (scryfall_download_url, cache_path / SCRYFALL_BULK_CACHE_FILENAME),
        (mtgjson_identifiers_url, cache_path / MTGJSON_IDENTIFIERS_CACHE_FILENAME),
        (mtgjson_prices_url, cache_path / MTGJSON_PRICES_CACHE_FILENAME),
    ):
        hints = (download_hints or {}).get(destination.name, {})
        download = _download_sync_artifact(
            download_url,
            destination,
            on_download=on_download,
            if_none_match=hints.get("etag"),
            if_modified_since=hints.get("last_modified"),
        )
        downloads.append(download)
        bulk_downloads.append(download)

    # The imports are ordered to establish catalog rows first, then enrich them
    # with identifier crosswalks, and finally attach price snapshots.
    scryfall_stats, scryfall_elapsed_seconds = _run_or_skip_sync_step(
        "import_scryfall",
        bulk_downloads[0],
        lambda: import_scryfall_cards(db_path, bulk_downloads[0].path, limit, before_write=before_write),
        should_skip_step=should_skip_step,
        on_step=on_step,
    )
    identifier_stats, identifier_elapsed_seconds = _run_or_skip_sync_step(
        "import_identifiers",
        bulk_downloads[1],
        lambda: import_mtgjson_identifiers(db_path, bulk_downloads[1].path, limit, before_write=before_write),
        should_skip_step=should_skip_step,
        on_step=on_step,
    )
    price_stats, price_elapsed_seconds = _run_or_skip_sync_step(
        "import_prices",
        bulk_downloads[2],
        lambda: import_mtgjson_prices(db_path, bulk_downloads[2].path, limit, source_name, before_write=before_write),
        should_skip_step=should_skip_step,
        on_step=on_step,
    )

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


def print_sync_result(
    command_name: str,
    result: dict[str, Any],
    *,
    stat_labels: list[tuple[str, str]],
) -> None:
    print(f"{command_name} completed")
    print(f"database: {result['db_path']}")
    if result.get("snapshot") is not None:
        print(f"snapshot: {result['snapshot']['snapshot_path']}")
    print(f"cache_dir: {result['cache_dir']}")
    print("downloads:")
    for download in result["downloads"]:
        print(f"  {download.label}: {download.path} ({format_bytes(download.bytes_written)})")
    for label, key in stat_labels:
        if key in result:
            print_stats(label, result[key])


def print_sync_bulk_result(result: dict[str, Any]) -> None:
    print_sync_result(
        "sync-bulk",
        result,
        stat_labels=[
            ("import-scryfall", "scryfall_stats"),
            ("import-identifiers", "identifier_stats"),
            ("import-prices", "price_stats"),
        ],
    )
