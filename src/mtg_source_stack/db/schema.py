from __future__ import annotations

import sqlite3
from importlib.resources import files
from pathlib import Path

from .connection import connect, require_database_file
from .migrator import migrate_database, pending_migrations
from ..errors import SchemaNotReadyError


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
    migrate_database(db_path)


def require_current_schema(db_path: str | Path) -> Path:
    path = require_database_file(db_path)
    with connect(path) as connection:
        pending = pending_migrations(connection)

    if pending:
        raise SchemaNotReadyError(
            f"Database file '{path}' is not at the current schema version. "
            f"Run mtg-mvp-importer migrate-db --db '{path}' before using read-only commands."
        )

    return path
