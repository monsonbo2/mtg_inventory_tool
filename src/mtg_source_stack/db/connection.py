from __future__ import annotations

from decimal import Decimal
import sqlite3
from pathlib import Path

from ..errors import NotFoundError, ValidationError


DEFAULT_DB_PATH = Path("var") / "db" / "mtg_mvp.db"
SQLITE_BUSY_TIMEOUT_MS = 5_000


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


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    # Keep the local SQLite DB friendly to short concurrent reads/writes once an
    # HTTP layer sits on top of it, while still preserving the integrity rules
    # the schema expects.
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
