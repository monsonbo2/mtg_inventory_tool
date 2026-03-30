from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("var") / "db" / "mtg_mvp.db"


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection
