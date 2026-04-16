#!/usr/bin/env python3
"""Run a repeatable local benchmark for the importer pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
IMPORTER_MODULE = "mtg_source_stack.mvp_importer"


def _module_env() -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(SRC_DIR)
    return env


def _run_importer(*args: str) -> dict[str, Any]:
    command = [sys.executable, "-m", IMPORTER_MODULE, *args]
    started = time.perf_counter()
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=_module_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    elapsed_seconds = time.perf_counter() - started
    return {
        "command": command,
        "returncode": result.returncode,
        "wall_seconds": round(elapsed_seconds, 6),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def _latest_run_step(db_path: Path, *, run_kind: str, step_name: str) -> dict[str, Any] | None:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT
                runs.id AS run_id,
                runs.status AS run_status,
                runs.summary_json,
                steps.status AS step_status,
                steps.rows_seen,
                steps.rows_written,
                steps.rows_skipped,
                steps.details_json
            FROM sync_runs AS runs
            LEFT JOIN sync_run_steps AS steps
                ON steps.sync_run_id = runs.id
               AND steps.step_name = ?
            WHERE runs.run_kind = ?
            ORDER BY runs.id DESC
            LIMIT 1
            """,
            (step_name, run_kind),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "run_status": row["run_status"],
        "summary": json.loads(row["summary_json"]) if row["summary_json"] else None,
        "step_status": row["step_status"],
        "rows_seen": row["rows_seen"],
        "rows_written": row["rows_written"],
        "rows_skipped": row["rows_skipped"],
        "details": json.loads(row["details_json"]) if row["details_json"] else None,
    }


def _db_counts(db_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(db_path)
    try:
        return {
            "mtg_cards": int(connection.execute("SELECT COUNT(*) FROM mtg_cards").fetchone()[0]),
            "mtgjson_card_links": int(
                connection.execute("SELECT COUNT(*) FROM mtgjson_card_links").fetchone()[0]
            ),
            "price_snapshots": int(connection.execute("SELECT COUNT(*) FROM price_snapshots").fetchone()[0]),
        }
    finally:
        connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark the local importer pipeline on local bulk files.")
    parser.add_argument("--db", required=True, help="SQLite database path for the benchmark run.")
    parser.add_argument("--scryfall-json", required=True, help="Path to Scryfall default-cards JSON.")
    parser.add_argument("--identifiers-json", required=True, help="Path to MTGJSON AllIdentifiers JSON or JSON.GZ.")
    parser.add_argument("--prices-json", required=True, help="Path to MTGJSON AllPricesToday JSON or JSON.GZ.")
    parser.add_argument(
        "--source-name",
        default="mtgjson_all_prices_today",
        help="Source name to use for the price import step.",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Reuse an existing database instead of deleting it before the benchmark.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    db_path = Path(args.db)
    if db_path.exists() and not args.keep_db:
        db_path.unlink()

    init_result = _run_importer("init-db", "--db", str(db_path))
    if init_result["returncode"] != 0:
        print(json.dumps({"init": init_result}, indent=2))
        return int(init_result["returncode"])

    steps = [
        {
            "label": "import_scryfall",
            "run_kind": "import_scryfall",
            "step_name": "import_scryfall",
            "args": ("import-scryfall", "--db", str(db_path), "--json", args.scryfall_json),
        },
        {
            "label": "import_identifiers",
            "run_kind": "import_identifiers",
            "step_name": "import_identifiers",
            "args": ("import-identifiers", "--db", str(db_path), "--json", args.identifiers_json),
        },
        {
            "label": "import_prices",
            "run_kind": "import_prices",
            "step_name": "import_prices",
            "args": (
                "import-prices",
                "--db",
                str(db_path),
                "--json",
                args.prices_json,
                "--source-name",
                args.source_name,
            ),
        },
    ]

    results: dict[str, Any] = {
        "db_path": str(db_path),
        "inputs": {
            "scryfall_json": str(Path(args.scryfall_json).resolve()),
            "identifiers_json": str(Path(args.identifiers_json).resolve()),
            "prices_json": str(Path(args.prices_json).resolve()),
        },
        "steps": {},
    }

    for step in steps:
        command_result = _run_importer(*step["args"])
        results["steps"][step["label"]] = {
            "command": command_result,
            "run": _latest_run_step(
                db_path,
                run_kind=step["run_kind"],
                step_name=step["step_name"],
            ),
        }
        if command_result["returncode"] != 0:
            results["db_counts"] = _db_counts(db_path)
            print(json.dumps(results, indent=2, sort_keys=True))
            return int(command_result["returncode"])

    results["db_counts"] = _db_counts(db_path)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
