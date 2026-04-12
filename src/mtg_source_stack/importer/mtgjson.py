"""MTGJSON importers for identifier crosswalks and historical price data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..db.connection import connect
from ..db.schema import initialize_database
from ..inventory.money import coerce_decimal
from ..inventory.normalize import normalize_price_snapshot_finish
from ..pricing import DEFAULT_PRICE_CURRENCY
from .service import ImportStats, first_non_empty, load_json, text_or_none


@dataclass(frozen=True, slots=True)
class IdentifierImportRow:
    mtgjson_uuid: str | None
    scryfall_id: str | None
    tcgplayer_product_id: str | None
    cardkingdom_id: str | None
    cardmarket_id: str | None
    cardsphere_id: str | None
    side: str | None


def _normalize_identifier_import_row(uuid: Any, identifier_record: Any) -> IdentifierImportRow | None:
    if not isinstance(identifier_record, dict):
        return None

    identifiers = identifier_record.get("identifiers")
    if not isinstance(identifiers, dict):
        identifiers = identifier_record

    return IdentifierImportRow(
        mtgjson_uuid=text_or_none(uuid),
        scryfall_id=text_or_none(identifiers.get("scryfallId")),
        tcgplayer_product_id=first_non_empty(
            identifiers.get("tcgplayerProductId"),
            identifiers.get("tcgplayerEtchedProductId"),
            identifiers.get("tcgplayerAlternativeFoilProductId"),
        ),
        cardkingdom_id=first_non_empty(
            identifiers.get("cardKingdomId"),
            identifiers.get("cardKingdomFoilId"),
            identifiers.get("cardKingdomEtchedId"),
        ),
        cardmarket_id=first_non_empty(
            identifiers.get("mcmId"),
            identifiers.get("mcmMetaId"),
        ),
        cardsphere_id=first_non_empty(
            identifiers.get("cardsphereId"),
            identifiers.get("cardsphereFoilId"),
        ),
        side=text_or_none(identifier_record.get("side")),
    )


def _identifier_import_row_sort_key(row: IdentifierImportRow) -> tuple[int, int, str]:
    provider_count = sum(
        value is not None
        for value in (
            row.tcgplayer_product_id,
            row.cardkingdom_id,
            row.cardmarket_id,
            row.cardsphere_id,
        )
    )
    normalized_side = row.side.lower() if row.side is not None else None
    side_rank = 0 if normalized_side == "a" else 1
    uuid_text = row.mtgjson_uuid or ""
    return (-provider_count, side_rank, uuid_text)


def _merge_identifier_import_rows(rows: list[IdentifierImportRow]) -> IdentifierImportRow:
    ordered_rows = sorted(rows, key=_identifier_import_row_sort_key)
    compatibility_row = next(
        (row for row in ordered_rows if row.mtgjson_uuid is not None),
        ordered_rows[0],
    )
    return IdentifierImportRow(
        mtgjson_uuid=compatibility_row.mtgjson_uuid,
        scryfall_id=compatibility_row.scryfall_id,
        tcgplayer_product_id=first_non_empty(*(row.tcgplayer_product_id for row in ordered_rows)),
        cardkingdom_id=first_non_empty(*(row.cardkingdom_id for row in ordered_rows)),
        cardmarket_id=first_non_empty(*(row.cardmarket_id for row in ordered_rows)),
        cardsphere_id=first_non_empty(*(row.cardsphere_id for row in ordered_rows)),
        side=compatibility_row.side,
    )


def _price_uuid_preference(uuid: str, *, preferred_uuid: str | None) -> tuple[int, str]:
    return (0 if preferred_uuid is not None and uuid == preferred_uuid else 1, uuid)


def import_mtgjson_identifiers(
    db_path: str | Path,
    json_path: str | Path,
    limit: int | None = None,
    *,
    before_write: Callable[[], Any] | None = None,
) -> ImportStats:
    payload = load_json(json_path)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("Expected MTGJSON identifiers to contain an object at payload['data'].")

    stats = ImportStats()
    initialize_database(db_path)
    snapshot_taken = False

    def maybe_before_write() -> None:
        nonlocal snapshot_taken
        if before_write is not None and not snapshot_taken:
            before_write()
            snapshot_taken = True

    with connect(db_path) as connection:
        known_rows = connection.execute(
            """
            SELECT scryfall_id, mtgjson_uuid
            FROM mtg_cards
            """
        ).fetchall()
        known_link_rows = connection.execute(
            """
            SELECT mtgjson_uuid, scryfall_id
            FROM mtgjson_card_links
            """
        ).fetchall()
    known_scryfall_ids = {row["scryfall_id"] for row in known_rows if row["scryfall_id"] is not None}
    uuid_to_scryfall = {
        row["mtgjson_uuid"]: row["scryfall_id"]
        for row in known_link_rows
        if row["mtgjson_uuid"] is not None and row["scryfall_id"] is not None
    }
    for row in known_rows:
        mtgjson_uuid = row["mtgjson_uuid"]
        scryfall_id = row["scryfall_id"]
        if mtgjson_uuid is not None and scryfall_id is not None:
            uuid_to_scryfall.setdefault(mtgjson_uuid, scryfall_id)

    grouped_rows: dict[str, list[IdentifierImportRow]] = {}

    for index, (uuid, identifier_record) in enumerate(data.items(), start=1):
        if limit is not None and index > limit:
            break

        stats.rows_seen += 1
        row = _normalize_identifier_import_row(uuid, identifier_record)
        if row is None:
            stats.rows_skipped += 1
            continue

        target_scryfall_id: str | None = None
        if row.scryfall_id is not None and row.scryfall_id in known_scryfall_ids:
            target_scryfall_id = row.scryfall_id
            if row.mtgjson_uuid is not None:
                uuid_to_scryfall[row.mtgjson_uuid] = row.scryfall_id
        elif row.mtgjson_uuid is not None:
            target_scryfall_id = uuid_to_scryfall.get(row.mtgjson_uuid)

        if target_scryfall_id is None:
            stats.rows_skipped += 1
            continue

        grouped_rows.setdefault(target_scryfall_id, []).append(row)

    merged_rows = {
        scryfall_id: _merge_identifier_import_rows(rows_for_card)
        for scryfall_id, rows_for_card in grouped_rows.items()
    }
    link_rows = sorted(
        {
            (row.mtgjson_uuid, scryfall_id)
            for scryfall_id, rows_for_card in grouped_rows.items()
            for row in rows_for_card
            if row.mtgjson_uuid is not None
        }
    )
    stats.details = {
        "matched_cards": len(grouped_rows),
        "staged_link_rows": len(link_rows),
    }
    if not merged_rows:
        stats.details["changed_cards"] = 0
        stats.details["no_op_cards"] = 0
        stats.details["link_rows_written"] = 0
        return stats

    card_change_predicate = """
        (updates.mtgjson_uuid IS NOT NULL AND COALESCE(cards.mtgjson_uuid, '') <> updates.mtgjson_uuid)
        OR (
            updates.tcgplayer_product_id IS NOT NULL
            AND COALESCE(cards.tcgplayer_product_id, '') <> updates.tcgplayer_product_id
        )
        OR (
            updates.cardkingdom_id IS NOT NULL
            AND COALESCE(cards.cardkingdom_id, '') <> updates.cardkingdom_id
        )
        OR (
            updates.cardmarket_id IS NOT NULL
            AND COALESCE(cards.cardmarket_id, '') <> updates.cardmarket_id
        )
        OR (
            updates.cardsphere_id IS NOT NULL
            AND COALESCE(cards.cardsphere_id, '') <> updates.cardsphere_id
        )
    """

    with connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TEMP TABLE temp_identifier_card_updates (
                scryfall_id TEXT PRIMARY KEY,
                mtgjson_uuid TEXT,
                tcgplayer_product_id TEXT,
                cardkingdom_id TEXT,
                cardmarket_id TEXT,
                cardsphere_id TEXT
            );
            CREATE TEMP TABLE temp_identifier_links (
                mtgjson_uuid TEXT PRIMARY KEY,
                scryfall_id TEXT NOT NULL
            );
            CREATE TEMP TABLE temp_identifier_changed_cards (
                scryfall_id TEXT PRIMARY KEY,
                mtgjson_uuid TEXT,
                tcgplayer_product_id TEXT,
                cardkingdom_id TEXT,
                cardmarket_id TEXT,
                cardsphere_id TEXT
            );
            CREATE TEMP TABLE temp_identifier_changed_links (
                mtgjson_uuid TEXT PRIMARY KEY,
                scryfall_id TEXT NOT NULL
            );
            """
        )
        connection.executemany(
            """
            INSERT INTO temp_identifier_card_updates (
                scryfall_id,
                mtgjson_uuid,
                tcgplayer_product_id,
                cardkingdom_id,
                cardmarket_id,
                cardsphere_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    scryfall_id,
                    merged_row.mtgjson_uuid,
                    merged_row.tcgplayer_product_id,
                    merged_row.cardkingdom_id,
                    merged_row.cardmarket_id,
                    merged_row.cardsphere_id,
                )
                for scryfall_id, merged_row in sorted(merged_rows.items())
            ],
        )
        if link_rows:
            connection.executemany(
                """
                INSERT INTO temp_identifier_links (mtgjson_uuid, scryfall_id)
                VALUES (?, ?)
                """,
                link_rows,
            )
        connection.execute(
            f"""
            INSERT INTO temp_identifier_changed_cards (
                scryfall_id,
                mtgjson_uuid,
                tcgplayer_product_id,
                cardkingdom_id,
                cardmarket_id,
                cardsphere_id
            )
            SELECT
                updates.scryfall_id,
                updates.mtgjson_uuid,
                updates.tcgplayer_product_id,
                updates.cardkingdom_id,
                updates.cardmarket_id,
                updates.cardsphere_id
            FROM temp_identifier_card_updates AS updates
            JOIN mtg_cards AS cards
                ON cards.scryfall_id = updates.scryfall_id
            WHERE {card_change_predicate}
            """
        )
        connection.execute(
            """
            INSERT INTO temp_identifier_changed_links (mtgjson_uuid, scryfall_id)
            SELECT
                links.mtgjson_uuid,
                links.scryfall_id
            FROM temp_identifier_links AS links
            LEFT JOIN mtgjson_card_links AS existing
                ON existing.mtgjson_uuid = links.mtgjson_uuid
            WHERE existing.mtgjson_uuid IS NULL OR existing.scryfall_id <> links.scryfall_id
            """
        )

        changed_card_ids = {
            row["scryfall_id"]
            for row in connection.execute(
                """
                SELECT scryfall_id
                FROM temp_identifier_changed_cards
                UNION
                SELECT DISTINCT scryfall_id
                FROM temp_identifier_changed_links
                """
            ).fetchall()
        }
        link_rows_written = connection.execute(
            "SELECT COUNT(*) FROM temp_identifier_changed_links"
        ).fetchone()[0]
        stats.rows_written = len(changed_card_ids)
        stats.details["changed_cards"] = stats.rows_written
        stats.details["no_op_cards"] = max(len(grouped_rows) - stats.rows_written, 0)
        stats.details["link_rows_written"] = int(link_rows_written)

        if changed_card_ids or link_rows_written:
            maybe_before_write()
        if changed_card_ids:
            connection.execute(
                """
                UPDATE mtg_cards
                SET
                    mtgjson_uuid = COALESCE(
                        (
                            SELECT updates.mtgjson_uuid
                            FROM temp_identifier_changed_cards AS updates
                            WHERE updates.scryfall_id = mtg_cards.scryfall_id
                        ),
                        mtgjson_uuid
                    ),
                    tcgplayer_product_id = COALESCE(
                        (
                            SELECT updates.tcgplayer_product_id
                            FROM temp_identifier_changed_cards AS updates
                            WHERE updates.scryfall_id = mtg_cards.scryfall_id
                        ),
                        tcgplayer_product_id
                    ),
                    cardkingdom_id = COALESCE(
                        (
                            SELECT updates.cardkingdom_id
                            FROM temp_identifier_changed_cards AS updates
                            WHERE updates.scryfall_id = mtg_cards.scryfall_id
                        ),
                        cardkingdom_id
                    ),
                    cardmarket_id = COALESCE(
                        (
                            SELECT updates.cardmarket_id
                            FROM temp_identifier_changed_cards AS updates
                            WHERE updates.scryfall_id = mtg_cards.scryfall_id
                        ),
                        cardmarket_id
                    ),
                    cardsphere_id = COALESCE(
                        (
                            SELECT updates.cardsphere_id
                            FROM temp_identifier_changed_cards AS updates
                            WHERE updates.scryfall_id = mtg_cards.scryfall_id
                        ),
                        cardsphere_id
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE scryfall_id IN (
                    SELECT scryfall_id
                    FROM temp_identifier_changed_cards
                )
                """
            )
        if link_rows_written:
            connection.executemany(
                """
                INSERT INTO mtgjson_card_links (mtgjson_uuid, scryfall_id)
                VALUES (?, ?)
                ON CONFLICT(mtgjson_uuid) DO UPDATE SET
                    scryfall_id = excluded.scryfall_id
                WHERE mtgjson_card_links.scryfall_id <> excluded.scryfall_id
                """,
                [
                    (row["mtgjson_uuid"], row["scryfall_id"])
                    for row in connection.execute(
                        """
                        SELECT mtgjson_uuid, scryfall_id
                        FROM temp_identifier_changed_links
                        ORDER BY mtgjson_uuid
                        """
                    ).fetchall()
                ],
            )

        connection.commit()

    return stats


def import_mtgjson_prices(
    db_path: str | Path,
    json_path: str | Path,
    limit: int | None = None,
    source_name: str = "mtgjson_all_prices_today",
    *,
    before_write: Callable[[], Any] | None = None,
) -> ImportStats:
    payload = load_json(json_path)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("Expected MTGJSON prices to contain an object at payload['data'].")

    initialize_database(db_path)
    with connect(db_path) as connection:
        link_rows = connection.execute(
            """
            SELECT mtgjson_uuid, scryfall_id
            FROM mtgjson_card_links
            """
        ).fetchall()
        card_rows = connection.execute(
            """
            SELECT scryfall_id, mtgjson_uuid
            FROM mtg_cards
            """
        ).fetchall()
        # MTGJSON price payloads are keyed by UUID, so build the lookup once
        # instead of querying the catalog row-by-row during import.
        uuid_to_scryfall = {
            row["mtgjson_uuid"]: row["scryfall_id"]
            for row in link_rows
            if row["mtgjson_uuid"] is not None and row["scryfall_id"] is not None
        }
        preferred_uuid_by_scryfall = {
            row["scryfall_id"]: row["mtgjson_uuid"]
            for row in card_rows
            if row["scryfall_id"] is not None and row["mtgjson_uuid"] is not None
        }
        for row in card_rows:
            mtgjson_uuid = row["mtgjson_uuid"]
            scryfall_id = row["scryfall_id"]
            if mtgjson_uuid is not None and scryfall_id is not None:
                uuid_to_scryfall.setdefault(mtgjson_uuid, scryfall_id)

    stats = ImportStats()
    snapshot_taken = False

    def maybe_before_write() -> None:
        nonlocal snapshot_taken
        if before_write is not None and not snapshot_taken:
            before_write()
            snapshot_taken = True

    sql = """
    INSERT INTO price_snapshots (
        scryfall_id,
        provider,
        price_kind,
        finish,
        currency,
        snapshot_date,
        price_value,
        source_name
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(
        scryfall_id,
        provider,
        price_kind,
        finish,
        currency,
        snapshot_date,
        source_name
    ) DO UPDATE SET
        price_value = excluded.price_value
    """

    merged_price_rows: dict[
        tuple[str, str, str, str, str, str, str],
        tuple[Any, str],
    ] = {}

    for index, (uuid, price_formats) in enumerate(data.items(), start=1):
        if limit is not None and index > limit:
            break

        stats.rows_seen += 1
        if not isinstance(price_formats, dict):
            stats.rows_skipped += 1
            continue

        mtgjson_uuid = str(uuid)
        scryfall_id = uuid_to_scryfall.get(mtgjson_uuid)
        if scryfall_id is None:
            stats.rows_skipped += 1
            continue

        wrote_for_card = False
        for channel_payload in price_formats.values():
            if not isinstance(channel_payload, dict):
                continue

            for provider, provider_payload in channel_payload.items():
                if not isinstance(provider_payload, dict):
                    continue

                currency = str(first_non_empty(provider_payload.get("currency"), DEFAULT_PRICE_CURRENCY)).upper()
                # Step 2 intentionally constrains imported market data to a
                # single currency so downstream pricing reads stay
                # unambiguous. Non-USD snapshots are ignored for now.
                if currency != DEFAULT_PRICE_CURRENCY:
                    continue
                for price_kind in ("retail", "buylist"):
                    price_points = provider_payload.get(price_kind)
                    if not isinstance(price_points, dict):
                        continue

                    for finish, dated_points in price_points.items():
                        normalized_finish = normalize_price_snapshot_finish(str(finish))
                        if normalized_finish is None:
                            continue
                        if isinstance(dated_points, dict):
                            items = dated_points.items()
                        else:
                            items = []

                        for snapshot_date, price_value in items:
                            decimal_price = coerce_decimal(price_value)
                            if decimal_price is None:
                                continue

                            wrote_for_card = True
                            key = (
                                scryfall_id,
                                provider,
                                price_kind,
                                normalized_finish,
                                currency,
                                str(snapshot_date),
                                source_name,
                            )
                            existing_entry = merged_price_rows.get(key)
                            if existing_entry is None:
                                merged_price_rows[key] = (decimal_price, mtgjson_uuid)
                                continue

                            existing_price, existing_uuid = existing_entry
                            preferred_uuid = preferred_uuid_by_scryfall.get(scryfall_id)
                            if (
                                decimal_price == existing_price
                                and _price_uuid_preference(mtgjson_uuid, preferred_uuid=preferred_uuid)
                                < _price_uuid_preference(existing_uuid, preferred_uuid=preferred_uuid)
                            ):
                                merged_price_rows[key] = (decimal_price, mtgjson_uuid)
                            elif (
                                decimal_price != existing_price
                                and _price_uuid_preference(mtgjson_uuid, preferred_uuid=preferred_uuid)
                                < _price_uuid_preference(existing_uuid, preferred_uuid=preferred_uuid)
                            ):
                                merged_price_rows[key] = (decimal_price, mtgjson_uuid)

        if not wrote_for_card:
            stats.rows_skipped += 1

    with connect(db_path) as connection:
        if merged_price_rows:
            maybe_before_write()
            connection.executemany(
                sql,
                [
                    (
                        scryfall_id,
                        provider,
                        price_kind,
                        finish,
                        currency,
                        snapshot_date,
                        price_value,
                        row_source_name,
                    )
                    for (
                        scryfall_id,
                        provider,
                        price_kind,
                        finish,
                        currency,
                        snapshot_date,
                        row_source_name,
                    ), (price_value, _source_uuid) in sorted(merged_price_rows.items())
                ],
            )
            stats.rows_written = len(merged_price_rows)

        connection.commit()

    return stats
