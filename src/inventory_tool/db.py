from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("inventory.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS inventories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS inventory_fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    field_type TEXT NOT NULL DEFAULT 'string',
    required INTEGER NOT NULL DEFAULT 0,
    default_value TEXT,
    display_order INTEGER NOT NULL DEFAULT 0,
    UNIQUE(inventory_id, field_name),
    FOREIGN KEY (inventory_id) REFERENCES inventories(id)
);

CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inventory_id) REFERENCES inventories(id)
);

CREATE TABLE IF NOT EXISTS inventory_item_values (
    item_id INTEGER NOT NULL,
    field_id INTEGER NOT NULL,
    value_text TEXT,
    PRIMARY KEY (item_id, field_id),
    FOREIGN KEY (item_id) REFERENCES inventory_items(id),
    FOREIGN KEY (field_id) REFERENCES inventory_fields(id)
);
"""


DEFAULT_FIELDS: list[tuple[str, str, int, str | None]] = [
    ("name", "string", 1, None),
    ("quantity", "integer", 1, "1"),
    ("price", "number", 0, None),
    ("location", "string", 0, None),
    ("notes", "string", 0, None),
]


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
