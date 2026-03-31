from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("var") / "db" / "mtg_mvp.db"


def require_database_file(db_path: str | Path) -> Path:
    path = Path(db_path)
    if path.is_dir():
        raise ValueError(f"Database path '{path}' is a directory, not a SQLite file.")
    if not path.exists():
        raise ValueError(
            f"Database file '{path}' does not exist. Check --db or run mtg-mvp-importer init-db first."
        )
    return path


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    # SQLite disables foreign-key enforcement by default on each connection, so
    # enable it here instead of relying on schema bootstrap side effects.
    connection.execute("PRAGMA foreign_keys = ON")
    return connection
