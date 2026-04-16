from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .connection import connect


SEARCH_INDEX_COLUMNS: tuple[str, ...] = (
    "scryfall_id",
    "name",
    "set_code",
    "set_name",
    "collector_number",
    "lang",
)


@dataclass(frozen=True, slots=True)
class SearchIndexCheckResult:
    missing_count: int
    orphan_count: int
    duplicate_count: int
    mismatch_count: int
    missing_rows: list[dict[str, Any]]
    orphan_rows: list[dict[str, Any]]
    duplicate_rows: list[dict[str, Any]]
    mismatch_rows: list[dict[str, Any]]

    @property
    def is_healthy(self) -> bool:
        return (
            self.missing_count == 0
            and self.orphan_count == 0
            and self.duplicate_count == 0
            and self.mismatch_count == 0
        )


@dataclass(frozen=True, slots=True)
class SearchIndexRebuildResult:
    previous_row_count: int
    source_row_count: int
    rebuilt_row_count: int


def _validate_limit(limit: int) -> None:
    if limit < 0:
        raise ValueError("Preview limit must be zero or greater.")


def _preview_value(value: Any) -> str:
    if value is None:
        return "(null)"
    text = str(value)
    return text if len(text) <= 40 else f"{text[:37]}..."


def _difference_summary(card_row: dict[str, Any], fts_row: dict[str, Any]) -> str:
    differences: list[str] = []
    for column_name in SEARCH_INDEX_COLUMNS:
        card_value = card_row[column_name]
        fts_value = fts_row[column_name]
        if card_value != fts_value:
            differences.append(
                f"{column_name}: card={_preview_value(card_value)} fts={_preview_value(fts_value)}"
            )
    return "; ".join(differences)


def _rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def check_card_search_index(db_path: str | Path, *, limit: int = 10) -> SearchIndexCheckResult:
    _validate_limit(limit)

    with connect(db_path) as connection:
        missing_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM mtg_cards AS cards
                LEFT JOIN mtg_cards_fts AS fts
                    ON fts.scryfall_id = cards.scryfall_id
                WHERE fts.scryfall_id IS NULL
                """
            ).fetchone()[0]
        )
        missing_rows = _rows_to_dicts(
            connection.execute(
                """
                SELECT
                    cards.scryfall_id,
                    cards.name,
                    cards.set_code,
                    cards.collector_number,
                    cards.lang
                FROM mtg_cards AS cards
                LEFT JOIN mtg_cards_fts AS fts
                    ON fts.scryfall_id = cards.scryfall_id
                WHERE fts.scryfall_id IS NULL
                ORDER BY cards.scryfall_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

        orphan_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM mtg_cards_fts AS fts
                LEFT JOIN mtg_cards AS cards
                    ON cards.scryfall_id = fts.scryfall_id
                WHERE cards.scryfall_id IS NULL
                """
            ).fetchone()[0]
        )
        orphan_rows = _rows_to_dicts(
            connection.execute(
                """
                SELECT
                    fts.scryfall_id,
                    fts.name,
                    fts.set_code,
                    fts.collector_number,
                    fts.lang
                FROM mtg_cards_fts AS fts
                LEFT JOIN mtg_cards AS cards
                    ON cards.scryfall_id = fts.scryfall_id
                WHERE cards.scryfall_id IS NULL
                ORDER BY fts.scryfall_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

        duplicate_count = int(
            connection.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT fts.scryfall_id
                    FROM mtg_cards_fts AS fts
                    GROUP BY fts.scryfall_id
                    HAVING COUNT(*) > 1
                )
                """
            ).fetchone()[0]
        )
        duplicate_rows = _rows_to_dicts(
            connection.execute(
                """
                SELECT
                    fts.scryfall_id,
                    COUNT(*) AS row_count
                FROM mtg_cards_fts AS fts
                GROUP BY fts.scryfall_id
                HAVING COUNT(*) > 1
                ORDER BY row_count DESC, fts.scryfall_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

        mismatch_query = """
            SELECT
                cards.scryfall_id,
                cards.name AS card_name,
                cards.set_code AS card_set_code,
                cards.set_name AS card_set_name,
                cards.collector_number AS card_collector_number,
                cards.lang AS card_lang,
                fts.name AS fts_name,
                fts.set_code AS fts_set_code,
                fts.set_name AS fts_set_name,
                fts.collector_number AS fts_collector_number,
                fts.lang AS fts_lang
            FROM mtg_cards AS cards
            JOIN mtg_cards_fts AS fts
                ON fts.scryfall_id = cards.scryfall_id
            WHERE
                cards.name IS NOT fts.name
                OR cards.set_code IS NOT fts.set_code
                OR cards.set_name IS NOT fts.set_name
                OR cards.collector_number IS NOT fts.collector_number
                OR cards.lang IS NOT fts.lang
            ORDER BY cards.scryfall_id, fts.rowid
        """
        mismatch_count = int(
            connection.execute(
                f"""
                SELECT COUNT(*)
                FROM ({mismatch_query})
                """
            ).fetchone()[0]
        )
        raw_mismatch_rows = _rows_to_dicts(
            connection.execute(
                f"""
                {mismatch_query}
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        )

    mismatch_rows: list[dict[str, Any]] = []
    for row in raw_mismatch_rows:
        mismatch_rows.append(
            {
                "scryfall_id": row["scryfall_id"],
                "differences": _difference_summary(
                    {
                        "scryfall_id": row["scryfall_id"],
                        "name": row["card_name"],
                        "set_code": row["card_set_code"],
                        "set_name": row["card_set_name"],
                        "collector_number": row["card_collector_number"],
                        "lang": row["card_lang"],
                    },
                    {
                        "scryfall_id": row["scryfall_id"],
                        "name": row["fts_name"],
                        "set_code": row["fts_set_code"],
                        "set_name": row["fts_set_name"],
                        "collector_number": row["fts_collector_number"],
                        "lang": row["fts_lang"],
                    },
                ),
            }
        )

    return SearchIndexCheckResult(
        missing_count=missing_count,
        orphan_count=orphan_count,
        duplicate_count=duplicate_count,
        mismatch_count=mismatch_count,
        missing_rows=missing_rows,
        orphan_rows=orphan_rows,
        duplicate_rows=duplicate_rows,
        mismatch_rows=mismatch_rows,
    )


def rebuild_card_search_index(db_path: str | Path) -> SearchIndexRebuildResult:
    with connect(db_path) as connection:
        previous_row_count = int(connection.execute("SELECT COUNT(*) FROM mtg_cards_fts").fetchone()[0])
        source_row_count = int(connection.execute("SELECT COUNT(*) FROM mtg_cards").fetchone()[0])
        connection.execute("DELETE FROM mtg_cards_fts")
        connection.execute(
            """
            INSERT INTO mtg_cards_fts (scryfall_id, name, set_code, set_name, collector_number, lang)
            SELECT
                scryfall_id,
                name,
                set_code,
                set_name,
                collector_number,
                lang
            FROM mtg_cards
            ORDER BY scryfall_id
            """
        )
        connection.commit()
        rebuilt_row_count = int(connection.execute("SELECT COUNT(*) FROM mtg_cards_fts").fetchone()[0])

    return SearchIndexRebuildResult(
        previous_row_count=previous_row_count,
        source_row_count=source_row_count,
        rebuilt_row_count=rebuilt_row_count,
    )
