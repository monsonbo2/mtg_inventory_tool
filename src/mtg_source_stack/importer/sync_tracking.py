"""Bookkeeping helpers for importer and sync runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..db.connection import connect
from .service import ImportStats


def _json_text(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _json_value(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def file_artifact_info(path: str | Path) -> dict[str, Any]:
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return {
        "local_path": str(file_path.resolve()),
        "bytes_written": file_path.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def import_stats_dict(stats: ImportStats) -> dict[str, int]:
    return {
        "rows_seen": stats.rows_seen,
        "rows_written": stats.rows_written,
        "rows_skipped": stats.rows_skipped,
    }


def start_sync_run(
    db_path: str | Path,
    *,
    run_kind: str,
    trigger_kind: str = "cli",
    source_name: str | None = None,
    limit_value: int | None = None,
) -> int:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            INSERT INTO sync_runs (
                run_kind,
                status,
                trigger_kind,
                source_name,
                limit_value
            )
            VALUES (?, 'running', ?, ?, ?)
            RETURNING id
            """,
            (run_kind, trigger_kind, source_name, limit_value),
        ).fetchone()
        connection.commit()
    return int(row["id"])


def finish_sync_run(
    db_path: str | Path,
    run_id: int,
    *,
    status: str,
    snapshot_path: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE sync_runs
            SET
                status = ?,
                snapshot_path = ?,
                summary_json = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, snapshot_path, _json_text(summary), run_id),
        )
        connection.commit()


def start_sync_step(
    db_path: str | Path,
    run_id: int,
    *,
    step_name: str,
    details: dict[str, Any] | None = None,
) -> int:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            INSERT INTO sync_run_steps (
                sync_run_id,
                step_name,
                status,
                details_json
            )
            VALUES (?, ?, 'running', ?)
            RETURNING id
            """,
            (run_id, step_name, _json_text(details)),
        ).fetchone()
        connection.commit()
    return int(row["id"])


def finish_sync_step(
    db_path: str | Path,
    step_id: int,
    *,
    status: str,
    stats: ImportStats | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            UPDATE sync_run_steps
            SET
                status = ?,
                rows_seen = ?,
                rows_written = ?,
                rows_skipped = ?,
                details_json = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                status,
                stats.rows_seen if stats is not None else None,
                stats.rows_written if stats is not None else None,
                stats.rows_skipped if stats is not None else None,
                _json_text(details),
                step_id,
            ),
        )
        connection.commit()


def record_sync_artifact(
    db_path: str | Path,
    run_id: int,
    *,
    artifact_role: str,
    source_url: str | None = None,
    local_path: str | None = None,
    bytes_written: int | None = None,
    sha256: str | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO sync_run_artifacts (
                sync_run_id,
                artifact_role,
                source_url,
                local_path,
                bytes_written,
                sha256,
                etag,
                last_modified
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                artifact_role,
                source_url,
                local_path,
                bytes_written,
                sha256,
                etag,
                last_modified,
            ),
        )
        connection.commit()


def record_sync_issue(
    db_path: str | Path,
    run_id: int,
    *,
    level: str,
    code: str,
    message: str,
    step_name: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    with connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO sync_run_issues (
                sync_run_id,
                step_name,
                level,
                code,
                message,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, step_name, level, code, message, _json_text(payload)),
        )
        connection.commit()


def latest_sync_artifact(
    db_path: str | Path,
    *,
    artifact_role: str,
    source_url: str | None = None,
) -> dict[str, Any] | None:
    query = """
        SELECT
            artifacts.id,
            artifacts.sync_run_id,
            artifacts.source_url,
            artifacts.local_path,
            artifacts.bytes_written,
            artifacts.sha256,
            artifacts.etag,
            artifacts.last_modified
        FROM sync_run_artifacts AS artifacts
        WHERE artifacts.artifact_role = ?
    """
    params: list[Any] = [artifact_role]
    if source_url is not None:
        query += " AND artifacts.source_url = ?"
        params.append(source_url)
    query += " ORDER BY artifacts.id DESC LIMIT 1"
    with connect(db_path) as connection:
        row = connection.execute(query, params).fetchone()
    return dict(row) if row is not None else None


def unchanged_import_skip_reason(
    db_path: str | Path,
    *,
    step_name: str,
    artifact_role: str,
    source_url: str,
    sha256: str,
    limit_value: int | None,
    source_name: str | None = None,
    invalidated_by_steps: tuple[str, ...] = (),
) -> str | None:
    with connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT
                runs.id AS run_id,
                runs.limit_value,
                runs.source_name,
                artifacts.sha256
            FROM sync_runs AS runs
            JOIN sync_run_steps AS steps
                ON steps.sync_run_id = runs.id
            JOIN sync_run_artifacts AS artifacts
                ON artifacts.sync_run_id = runs.id
            WHERE runs.status = 'succeeded'
              AND steps.status = 'succeeded'
              AND steps.step_name = ?
              AND artifacts.artifact_role = ?
              AND artifacts.source_url = ?
            ORDER BY runs.id DESC
            LIMIT 1
            """,
            (step_name, artifact_role, source_url),
        ).fetchone()
        if row is None:
            return None
        if row["sha256"] != sha256:
            return None
        if row["limit_value"] != limit_value:
            return None
        if source_name is not None and row["source_name"] != source_name:
            return None
        if invalidated_by_steps:
            placeholders = ",".join("?" for _ in invalidated_by_steps)
            invalidation_row = connection.execute(
                f"""
                SELECT 1
                FROM sync_runs AS runs
                JOIN sync_run_steps AS steps
                    ON steps.sync_run_id = runs.id
                WHERE runs.status = 'succeeded'
                  AND steps.status = 'succeeded'
                  AND steps.step_name IN ({placeholders})
                  AND runs.id > ?
                LIMIT 1
                """,
                (*invalidated_by_steps, row["run_id"]),
            ).fetchone()
            if invalidation_row is not None:
                return None
    return f"artifact unchanged since run {row['run_id']}"


def list_sync_runs(
    db_path: str | Path,
    *,
    limit: int = 20,
    run_kind: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    query = """
        SELECT
            runs.id,
            runs.run_kind,
            runs.status,
            runs.trigger_kind,
            runs.source_name,
            runs.limit_value,
            runs.snapshot_path,
            runs.started_at,
            runs.finished_at,
            ROUND((julianday(COALESCE(runs.finished_at, CURRENT_TIMESTAMP)) - julianday(runs.started_at)) * 86400.0, 3)
                AS duration_seconds,
            COALESCE(step_counts.step_count, 0) AS step_count,
            COALESCE(artifact_counts.artifact_count, 0) AS artifact_count,
            COALESCE(issue_counts.issue_count, 0) AS issue_count,
            runs.summary_json
        FROM sync_runs AS runs
        LEFT JOIN (
            SELECT sync_run_id, COUNT(*) AS step_count
            FROM sync_run_steps
            GROUP BY sync_run_id
        ) AS step_counts
            ON step_counts.sync_run_id = runs.id
        LEFT JOIN (
            SELECT sync_run_id, COUNT(*) AS artifact_count
            FROM sync_run_artifacts
            GROUP BY sync_run_id
        ) AS artifact_counts
            ON artifact_counts.sync_run_id = runs.id
        LEFT JOIN (
            SELECT sync_run_id, COUNT(*) AS issue_count
            FROM sync_run_issues
            GROUP BY sync_run_id
        ) AS issue_counts
            ON issue_counts.sync_run_id = runs.id
        WHERE 1 = 1
    """
    params: list[Any] = []
    if run_kind is not None:
        query += " AND runs.run_kind = ?"
        params.append(run_kind)
    if status is not None:
        query += " AND runs.status = ?"
        params.append(status)
    query += " ORDER BY runs.id DESC LIMIT ?"
    params.append(limit)

    with connect(db_path) as connection:
        run_rows = [dict(row) for row in connection.execute(query, params).fetchall()]
        run_ids = [row["id"] for row in run_rows]
        step_rows: dict[int, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
        if run_ids:
            placeholders = ",".join("?" for _ in run_ids)
            for row in connection.execute(
                f"""
                SELECT
                    sync_run_id,
                    step_name,
                    status,
                    rows_seen,
                    rows_written,
                    rows_skipped,
                    details_json
                FROM sync_run_steps
                WHERE sync_run_id IN ({placeholders})
                ORDER BY id
                """,
                run_ids,
            ).fetchall():
                step_rows[int(row["sync_run_id"])].append(dict(row))

    for row in run_rows:
        row["summary"] = _json_value(row.pop("summary_json"))
        row["steps"] = step_rows.get(int(row["id"]), [])

    return run_rows


def get_sync_run_report(db_path: str | Path, *, run_id: int) -> dict[str, Any] | None:
    with connect(db_path) as connection:
        run_row = connection.execute(
            """
            SELECT
                id,
                run_kind,
                status,
                trigger_kind,
                source_name,
                limit_value,
                snapshot_path,
                started_at,
                finished_at,
                ROUND((julianday(COALESCE(finished_at, CURRENT_TIMESTAMP)) - julianday(started_at)) * 86400.0, 3)
                    AS duration_seconds,
                summary_json
            FROM sync_runs
            WHERE id = ?
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            return None

        steps = [
            {
                **dict(row),
                "details": _json_value(row["details_json"]),
            }
            for row in connection.execute(
                """
                SELECT
                    step_name,
                    status,
                    rows_seen,
                    rows_written,
                    rows_skipped,
                    details_json,
                    started_at,
                    finished_at,
                    ROUND((julianday(COALESCE(finished_at, CURRENT_TIMESTAMP)) - julianday(started_at)) * 86400.0, 3)
                        AS duration_seconds
                FROM sync_run_steps
                WHERE sync_run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        ]
        for step in steps:
            step.pop("details_json", None)

        artifacts = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    artifact_role,
                    source_url,
                    local_path,
                    bytes_written,
                    sha256,
                    etag,
                    last_modified,
                    created_at
                FROM sync_run_artifacts
                WHERE sync_run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        ]

        issues = [
            {
                **dict(row),
                "payload": _json_value(row["payload_json"]),
            }
            for row in connection.execute(
                """
                SELECT
                    step_name,
                    level,
                    code,
                    message,
                    payload_json,
                    created_at
                FROM sync_run_issues
                WHERE sync_run_id = ?
                ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        ]
        for issue in issues:
            issue.pop("payload_json", None)

    report = dict(run_row)
    report["summary"] = _json_value(report.pop("summary_json"))
    report["steps"] = steps
    report["artifacts"] = artifacts
    report["issues"] = issues
    return report
