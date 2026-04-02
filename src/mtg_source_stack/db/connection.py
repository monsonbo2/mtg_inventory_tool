from __future__ import annotations

from decimal import Decimal
import sqlite3
from pathlib import Path

from ..errors import NotFoundError, ValidationError


DEFAULT_DB_PATH = Path("var") / "db" / "mtg_mvp.db"
SQLITE_JOURNAL_MODE = "WAL"
SQLITE_BUSY_TIMEOUT_MS = 5_000
SQLITE_SYNCHRONOUS_MODE = "NORMAL"
SQLITE_SYNCHRONOUS_LEVELS = {
    0: "OFF",
    1: "NORMAL",
    2: "FULL",
    3: "EXTRA",
}


sqlite3.register_adapter(Decimal, lambda value: format(value, "f"))


def require_database_file(db_path: str | Path) -> Path:
    path = Path(db_path)
    if path.is_dir():
        raise ValidationError(f"Database path '{path}' is a directory, not a SQLite file.")
    if not path.exists():
        raise NotFoundError(
            f"Database file '{path}' does not exist. Check --db or run mtg-mvp-importer init-db first."
        )
    return path


def describe_sqlite_connection(connection: sqlite3.Connection) -> dict[str, int | str | bool]:
    journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    busy_timeout = int(connection.execute("PRAGMA busy_timeout").fetchone()[0])
    synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]
    foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])

    if isinstance(synchronous, int):
        synchronous_mode = SQLITE_SYNCHRONOUS_LEVELS.get(synchronous, str(synchronous))
    else:
        synchronous_mode = str(synchronous).upper()

    return {
        "journal_mode": str(journal_mode).upper(),
        "busy_timeout_ms": busy_timeout,
        "synchronous": synchronous_mode,
        "foreign_keys": bool(foreign_keys),
    }


def describe_sqlite_runtime_posture(db_path: str | Path) -> dict[str, int | str | bool]:
    with connect(db_path) as connection:
        return describe_sqlite_connection(connection)


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    # Keep the local SQLite DB friendly to short concurrent reads/writes once an
    # HTTP layer sits on top of it, while still preserving the integrity rules
    # the schema expects.
    connection.execute(f"PRAGMA journal_mode = {SQLITE_JOURNAL_MODE}")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    connection.execute(f"PRAGMA synchronous = {SQLITE_SYNCHRONOUS_MODE}")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
