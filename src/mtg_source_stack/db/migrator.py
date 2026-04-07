from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .connection import connect


MIGRATIONS_PACKAGE = "mtg_source_stack.db.migrations"
MIGRATION_NAME_RE = re.compile(r"^(?P<version>\d{4})_(?P<name>.+)\.sql$")


@dataclass(frozen=True)
class MigrationFile:
    version: int
    name: str
    resource_name: str


def column_exists(connection: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def list_migration_files() -> list[MigrationFile]:
    migrations: list[MigrationFile] = []
    seen_versions: set[int] = set()
    for resource in files(MIGRATIONS_PACKAGE).iterdir():
        if not resource.is_file() or not resource.name.endswith(".sql"):
            continue
        match = MIGRATION_NAME_RE.match(resource.name)
        if match is None:
            continue
        version = int(match.group("version"))
        if version in seen_versions:
            raise ValueError(f"Duplicate migration version {version:04d}.")
        seen_versions.add(version)
        migrations.append(
            MigrationFile(
                version=version,
                name=match.group("name").replace("_", " "),
                resource_name=resource.name,
            )
        )
    migrations.sort(key=lambda migration: migration.version)
    return migrations


def load_migration_sql(resource_name: str) -> str:
    return files(MIGRATIONS_PACKAGE).joinpath(resource_name).read_text(encoding="utf-8")


def ensure_schema_migrations_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def applied_migration_versions(connection: sqlite3.Connection) -> set[int]:
    ensure_schema_migrations_table(connection)
    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return {int(row["version"]) for row in rows}


def recorded_migration_versions(connection: sqlite3.Connection) -> set[int]:
    if not table_exists(connection, "schema_migrations"):
        return set()
    rows = connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return {int(row["version"]) for row in rows}


def pending_migrations(connection: sqlite3.Connection) -> list[MigrationFile]:
    recorded = recorded_migration_versions(connection)
    return [migration for migration in list_migration_files() if migration.version not in recorded]


def current_schema_version(connection: sqlite3.Connection) -> int:
    versions = applied_migration_versions(connection)
    return max(versions) if versions else 0


def _prepare_migration(connection: sqlite3.Connection, migration: MigrationFile) -> None:
    if migration.version == 2 and not column_exists(connection, "inventory_items", "tags_json"):
        connection.execute(
            """
            ALTER TABLE inventory_items
            ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'
            """
        )
    if (
        migration.version == 10
        and table_exists(connection, "inventory_items")
        and not column_exists(connection, "inventory_items", "printing_selection_mode")
    ):
        connection.execute(
            """
            ALTER TABLE inventory_items
            ADD COLUMN printing_selection_mode TEXT NOT NULL DEFAULT 'explicit'
            CHECK (printing_selection_mode IN ('explicit', 'defaulted'))
            """
        )
    if migration.version == 11 and not table_exists(connection, "inventories"):
        connection.execute(
            """
            CREATE TABLE inventories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                slug TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def migrate_connection(connection: sqlite3.Connection) -> list[MigrationFile]:
    applied_versions = applied_migration_versions(connection)
    applied_now: list[MigrationFile] = []

    for migration in list_migration_files():
        if migration.version in applied_versions:
            continue

        _prepare_migration(connection, migration)
        sql = load_migration_sql(migration.resource_name)
        if sql.strip():
            connection.executescript(sql)
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name)
            VALUES (?, ?)
            """,
            (migration.version, migration.name),
        )
        applied_now.append(migration)
        applied_versions.add(migration.version)

    return applied_now


def migrate_database(db_path: str | Path) -> list[MigrationFile]:
    with connect(db_path) as connection:
        return migrate_connection(connection)
