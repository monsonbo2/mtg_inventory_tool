from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from ..db.connection import connect
from ..db.schema import initialize_database
from .service import ImportStats, compact_json, first_non_empty, load_json, text_or_none


def pick_image_uris(card: dict[str, Any]) -> dict[str, Any] | None:
    image_uris = card.get("image_uris")
    if isinstance(image_uris, dict):
        return image_uris

    card_faces = card.get("card_faces")
    if isinstance(card_faces, list):
        for face in card_faces:
            if isinstance(face, dict) and isinstance(face.get("image_uris"), dict):
                return face["image_uris"]
    return None


def pick_oracle_id(card: dict[str, Any]) -> str | None:
    oracle_id = text_or_none(card.get("oracle_id"))
    if oracle_id is not None:
        return oracle_id

    card_faces = card.get("card_faces")
    if isinstance(card_faces, list):
        for face in card_faces:
            if isinstance(face, dict):
                oracle_id = text_or_none(face.get("oracle_id"))
                if oracle_id is not None:
                    return oracle_id
    return None


def iter_scryfall_cards(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [item for item in payload["data"] if isinstance(item, dict)]
    raise ValueError("Expected Scryfall bulk data to be a JSON list or an object with a data list.")


def import_scryfall_cards(
    db_path: str | Path,
    json_path: str | Path,
    limit: int | None = None,
    *,
    before_write: Callable[[], Any] | None = None,
) -> ImportStats:
    payload = load_json(json_path)
    cards = iter_scryfall_cards(payload)
    stats = ImportStats()
    initialize_database(db_path)
    snapshot_taken = False

    def maybe_before_write() -> None:
        nonlocal snapshot_taken
        if before_write is not None and not snapshot_taken:
            before_write()
            snapshot_taken = True

    sql = """
    INSERT INTO mtg_cards (
        scryfall_id,
        oracle_id,
        mtgjson_uuid,
        name,
        set_code,
        set_name,
        collector_number,
        lang,
        rarity,
        released_at,
        mana_cost,
        type_line,
        oracle_text,
        colors_json,
        color_identity_json,
        finishes_json,
        image_uris_json,
        legalities_json,
        purchase_uris_json,
        tcgplayer_product_id,
        cardkingdom_id,
        cardmarket_id,
        cardsphere_id
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(scryfall_id) DO UPDATE SET
        oracle_id = excluded.oracle_id,
        name = excluded.name,
        set_code = excluded.set_code,
        set_name = excluded.set_name,
        collector_number = excluded.collector_number,
        lang = excluded.lang,
        rarity = excluded.rarity,
        released_at = excluded.released_at,
        mana_cost = excluded.mana_cost,
        type_line = excluded.type_line,
        oracle_text = excluded.oracle_text,
        colors_json = excluded.colors_json,
        color_identity_json = excluded.color_identity_json,
        finishes_json = excluded.finishes_json,
        image_uris_json = excluded.image_uris_json,
        legalities_json = excluded.legalities_json,
        purchase_uris_json = excluded.purchase_uris_json,
        mtgjson_uuid = COALESCE(excluded.mtgjson_uuid, mtg_cards.mtgjson_uuid),
        tcgplayer_product_id = COALESCE(excluded.tcgplayer_product_id, mtg_cards.tcgplayer_product_id),
        cardkingdom_id = COALESCE(excluded.cardkingdom_id, mtg_cards.cardkingdom_id),
        cardmarket_id = COALESCE(excluded.cardmarket_id, mtg_cards.cardmarket_id),
        cardsphere_id = COALESCE(excluded.cardsphere_id, mtg_cards.cardsphere_id),
        updated_at = CURRENT_TIMESTAMP
    """

    with connect(db_path) as connection:
        for index, card in enumerate(cards, start=1):
            if limit is not None and index > limit:
                break

            stats.rows_seen += 1
            scryfall_id = text_or_none(card.get("id"))
            oracle_id = pick_oracle_id(card)
            set_code = text_or_none(card.get("set"))
            set_name = text_or_none(card.get("set_name"))
            collector_number = text_or_none(card.get("collector_number"))
            name = text_or_none(card.get("name"))

            if not all([scryfall_id, oracle_id, set_code, set_name, collector_number, name]):
                stats.rows_skipped += 1
                continue

            maybe_before_write()
            connection.execute(
                sql,
                (
                    scryfall_id,
                    oracle_id,
                    None,
                    name,
                    set_code,
                    set_name,
                    collector_number,
                    first_non_empty(card.get("lang"), "en"),
                    text_or_none(card.get("rarity")),
                    text_or_none(card.get("released_at")),
                    text_or_none(card.get("mana_cost")),
                    text_or_none(card.get("type_line")),
                    text_or_none(card.get("oracle_text")),
                    compact_json(card.get("colors") or []),
                    compact_json(card.get("color_identity") or []),
                    compact_json(card.get("finishes") or []),
                    compact_json(pick_image_uris(card)),
                    compact_json(card.get("legalities") or {}),
                    compact_json(card.get("purchase_uris") or {}),
                    text_or_none(card.get("tcgplayer_id")),
                    None,
                    text_or_none(card.get("cardmarket_id")),
                    None,
                ),
            )
            stats.rows_written += 1

        connection.commit()

    return stats
