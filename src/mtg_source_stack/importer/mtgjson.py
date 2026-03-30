from __future__ import annotations

from pathlib import Path

from ..db.connection import connect
from .service import ImportStats, first_non_empty, load_json, text_or_none


def import_mtgjson_identifiers(db_path: str | Path, json_path: str | Path, limit: int | None = None) -> ImportStats:
    payload = load_json(json_path)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("Expected MTGJSON identifiers to contain an object at payload['data'].")

    stats = ImportStats()

    with connect(db_path) as connection:
        for index, (uuid, identifier_record) in enumerate(data.items(), start=1):
            if limit is not None and index > limit:
                break

            stats.rows_seen += 1
            if not isinstance(identifier_record, dict):
                stats.rows_skipped += 1
                continue

            identifiers = identifier_record.get("identifiers")
            if not isinstance(identifiers, dict):
                identifiers = identifier_record

            scryfall_id = text_or_none(identifiers.get("scryfallId"))
            mtgjson_uuid = text_or_none(uuid)

            if scryfall_id is not None:
                cursor = connection.execute(
                    """
                    UPDATE mtg_cards
                    SET
                        mtgjson_uuid = COALESCE(?, mtgjson_uuid),
                        tcgplayer_product_id = COALESCE(?, tcgplayer_product_id),
                        cardkingdom_id = COALESCE(?, cardkingdom_id),
                        cardmarket_id = COALESCE(?, cardmarket_id),
                        cardsphere_id = COALESCE(?, cardsphere_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE scryfall_id = ?
                    """,
                    (
                        mtgjson_uuid,
                        first_non_empty(
                            identifiers.get("tcgplayerProductId"),
                            identifiers.get("tcgplayerEtchedProductId"),
                            identifiers.get("tcgplayerAlternativeFoilProductId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardKingdomId"),
                            identifiers.get("cardKingdomFoilId"),
                            identifiers.get("cardKingdomEtchedId"),
                        ),
                        first_non_empty(
                            identifiers.get("mcmId"),
                            identifiers.get("mcmMetaId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardsphereId"),
                            identifiers.get("cardsphereFoilId"),
                        ),
                        scryfall_id,
                    ),
                )
                if cursor.rowcount:
                    stats.rows_written += 1
                else:
                    stats.rows_skipped += 1
                continue

            if mtgjson_uuid is not None:
                cursor = connection.execute(
                    """
                    UPDATE mtg_cards
                    SET
                        tcgplayer_product_id = COALESCE(?, tcgplayer_product_id),
                        cardkingdom_id = COALESCE(?, cardkingdom_id),
                        cardmarket_id = COALESCE(?, cardmarket_id),
                        cardsphere_id = COALESCE(?, cardsphere_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE mtgjson_uuid = ?
                    """,
                    (
                        first_non_empty(
                            identifiers.get("tcgplayerProductId"),
                            identifiers.get("tcgplayerEtchedProductId"),
                            identifiers.get("tcgplayerAlternativeFoilProductId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardKingdomId"),
                            identifiers.get("cardKingdomFoilId"),
                            identifiers.get("cardKingdomEtchedId"),
                        ),
                        first_non_empty(
                            identifiers.get("mcmId"),
                            identifiers.get("mcmMetaId"),
                        ),
                        first_non_empty(
                            identifiers.get("cardsphereId"),
                            identifiers.get("cardsphereFoilId"),
                        ),
                        mtgjson_uuid,
                    ),
                )
                if cursor.rowcount:
                    stats.rows_written += 1
                else:
                    stats.rows_skipped += 1
                continue

            stats.rows_skipped += 1

        connection.commit()

    return stats


def import_mtgjson_prices(
    db_path: str | Path,
    json_path: str | Path,
    limit: int | None = None,
    source_name: str = "mtgjson_all_prices_today",
) -> ImportStats:
    payload = load_json(json_path)
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        raise ValueError("Expected MTGJSON prices to contain an object at payload['data'].")

    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT mtgjson_uuid, scryfall_id
            FROM mtg_cards
            WHERE mtgjson_uuid IS NOT NULL
            """
        ).fetchall()
        uuid_to_scryfall = {row["mtgjson_uuid"]: row["scryfall_id"] for row in rows}

    stats = ImportStats()

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

    with connect(db_path) as connection:
        for index, (uuid, price_formats) in enumerate(data.items(), start=1):
            if limit is not None and index > limit:
                break

            stats.rows_seen += 1
            if not isinstance(price_formats, dict):
                stats.rows_skipped += 1
                continue

            scryfall_id = uuid_to_scryfall.get(str(uuid))
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

                    currency = first_non_empty(provider_payload.get("currency"), "USD")
                    for price_kind in ("retail", "buylist"):
                        price_points = provider_payload.get(price_kind)
                        if not isinstance(price_points, dict):
                            continue

                        for finish, dated_points in price_points.items():
                            if isinstance(dated_points, dict):
                                items = dated_points.items()
                            else:
                                items = []

                            for snapshot_date, price_value in items:
                                if not isinstance(price_value, (int, float)):
                                    continue

                                connection.execute(
                                    sql,
                                    (
                                        scryfall_id,
                                        provider,
                                        price_kind,
                                        str(finish),
                                        currency,
                                        str(snapshot_date),
                                        float(price_value),
                                        source_name,
                                    ),
                                )
                                wrote_for_card = True
                                stats.rows_written += 1

            if not wrote_for_card:
                stats.rows_skipped += 1

        connection.commit()

    return stats

