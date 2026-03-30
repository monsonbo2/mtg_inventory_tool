from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .schema import initialize_database


DEFAULT_SNAPSHOT_SUBDIR = "_snapshots"
SNAPSHOT_FILE_SUFFIX = ".sqlite3"


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

