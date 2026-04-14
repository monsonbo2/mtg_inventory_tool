#!/usr/bin/env python3
"""Create a small, repeatable local dataset for frontend demo work."""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import NotFoundError, ValidationError
from mtg_source_stack.importer.mtgjson import import_mtgjson_identifiers, import_mtgjson_prices
from mtg_source_stack.importer.scryfall import import_scryfall_cards
from mtg_source_stack.inventory.normalize import normalize_finish, validate_supported_finish
from mtg_source_stack.inventory.service import (
    add_card,
    add_card_with_connection,
    create_inventory,
    remove_card,
    resolve_card_row,
    set_acquisition,
    set_condition,
    set_finish,
    set_location,
    set_notes,
    set_quantity,
    set_tags,
)


DEFAULT_DB_PATH = Path("var/db/frontend_demo.db")
ACTOR_TYPE = "seed"
ACTOR_ID = "frontend-bootstrap"


def seed_price_snapshots(db_path: Path, rows: list[tuple[str, str, str, str, str, str, float, str]]) -> None:
    with connect(db_path) as connection:
        connection.executemany(
            """
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
            """,
            rows,
        )
        connection.commit()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap a local demo dataset for frontend work.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path to create.")
    parser.add_argument(
        "--full-catalog",
        action="store_true",
        help="Import a real Scryfall-backed mtg_cards catalog instead of the tiny built-in demo catalog.",
    )
    parser.add_argument(
        "--scryfall-json",
        help="Path to local Scryfall bulk JSON for --full-catalog mode.",
    )
    parser.add_argument(
        "--identifiers-json",
        help="Path to local MTGJSON AllIdentifiers JSON for importing real vendor links in --full-catalog mode.",
    )
    parser.add_argument(
        "--prices-json",
        help="Path to local MTGJSON AllPricesToday JSON for importing real price snapshots in --full-catalog mode.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target database file if it already exists.",
    )
    return parser


def seed_small_demo_catalog_and_prices(db_path: Path) -> None:
    with connect(db_path) as connection:
        connection.executemany(
            """
            INSERT INTO mtg_cards (
                scryfall_id,
                oracle_id,
                name,
                set_code,
                set_name,
                collector_number,
                lang,
                rarity,
                finishes_json,
                image_uris_json,
                tcgplayer_product_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "demo-bolt",
                    "oracle-bolt",
                    "Lightning Bolt",
                    "lea",
                    "Limited Edition Alpha",
                    "161",
                    "en",
                    "common",
                    '["normal","foil"]',
                    '{"small":"https://cards.scryfall.io/small/front/d/5/d573ef03-4730-45aa-93dd-e45ac1dbaf4a.jpg?1559591645","normal":"https://cards.scryfall.io/normal/front/d/5/d573ef03-4730-45aa-93dd-e45ac1dbaf4a.jpg?1559591645"}',
                    "1001",
                ),
                (
                    "demo-counterspell",
                    "oracle-counterspell",
                    "Counterspell",
                    "7ed",
                    "Seventh Edition",
                    "67",
                    "en",
                    "uncommon",
                    '["normal","foil"]',
                    '{"small":"https://cards.scryfall.io/small/front/2/9/29bb1b85-9444-4bfa-b622-092a6873631c.jpg?1562234566","normal":"https://cards.scryfall.io/normal/front/2/9/29bb1b85-9444-4bfa-b622-092a6873631c.jpg?1562234566"}',
                    "1002",
                ),
                (
                    "demo-forest",
                    "oracle-forest",
                    "Forest",
                    "m10",
                    "Magic 2010",
                    "246",
                    "en",
                    "common",
                    '["normal"]',
                    '{"small":"https://cards.scryfall.io/small/front/3/3/3394d804-c0e5-4901-a8ff-c1a765cc1e21.jpg?1561975836","normal":"https://cards.scryfall.io/normal/front/3/3/3394d804-c0e5-4901-a8ff-c1a765cc1e21.jpg?1561975836"}',
                    "1003",
                ),
                (
                    "demo-swords",
                    "oracle-swords",
                    "Swords to Plowshares",
                    "ice",
                    "Ice Age",
                    "54",
                    "en",
                    "uncommon",
                    '["normal"]',
                    '{"small":"https://cards.scryfall.io/small/front/3/7/375fd2cb-443b-4be4-ad60-6d1a8e74f510.jpg?1562905275","normal":"https://cards.scryfall.io/normal/front/3/7/375fd2cb-443b-4be4-ad60-6d1a8e74f510.jpg?1562905275"}',
                    "1004",
                ),
                (
                    "demo-swords-ja",
                    "oracle-swords",
                    "Swords to Plowshares",
                    "sta",
                    "Strixhaven Mystical Archive",
                    "10",
                    "ja",
                    "uncommon",
                    '["normal"]',
                    '{"small":"https://cards.scryfall.io/small/front/3/7/375fd2cb-443b-4be4-ad60-6d1a8e74f510.jpg?1562905275","normal":"https://cards.scryfall.io/normal/front/3/7/375fd2cb-443b-4be4-ad60-6d1a8e74f510.jpg?1562905275"}',
                    "1006",
                ),
                (
                    "demo-sol-ring",
                    "oracle-sol-ring",
                    "Sol Ring",
                    "cmr",
                    "Commander Legends",
                    "334",
                    "en",
                    "uncommon",
                    '["normal","etched"]',
                    '{"small":"https://cards.scryfall.io/small/front/5/8/58b26011-e103-45c4-a253-900f4e6b2eeb.jpg?1627501347","normal":"https://cards.scryfall.io/normal/front/5/8/58b26011-e103-45c4-a253-900f4e6b2eeb.jpg?1627501347"}',
                    "1005",
                ),
            ],
        )
        connection.commit()
    seed_price_snapshots(
        db_path,
        [
            ("demo-bolt", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 2.50, "demo-seed"),
            ("demo-bolt", "tcgplayer", "retail", "foil", "USD", "2026-04-01", 6.75, "demo-seed"),
            ("demo-counterspell", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 1.25, "demo-seed"),
            ("demo-counterspell", "tcgplayer", "retail", "foil", "USD", "2026-04-01", 4.25, "demo-seed"),
            ("demo-forest", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 0.15, "demo-seed"),
            ("demo-swords", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 3.50, "demo-seed"),
            ("demo-swords-ja", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 3.50, "demo-seed"),
            ("demo-sol-ring", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 1.75, "demo-seed"),
            ("demo-sol-ring", "tcgplayer", "retail", "etched", "USD", "2026-04-01", 4.75, "demo-seed"),
        ],
    )


def seed_demo_inventories(db_path: Path) -> None:
    create_inventory(
        db_path,
        slug="personal",
        display_name="Personal Collection",
        description="Frontend demo inventory",
    )
    create_inventory(
        db_path,
        slug="trade-binder",
        display_name="Trade Binder",
        description="Intentionally empty inventory for frontend empty states",
    )


def _resolve_full_catalog_demo_oracle_id(db_path: Path, *, card_name: str) -> str:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT DISTINCT oracle_id
            FROM mtg_cards
            WHERE LOWER(name) = LOWER(?)
              AND COALESCE(is_default_add_searchable, 1) = 1
            ORDER BY oracle_id
            """,
            (card_name,),
        ).fetchall()
    if not rows:
        raise ValidationError(
            f"Could not seed full-catalog demo row for '{card_name}': "
            "no default-scope oracle match was found."
        )
    if len(rows) > 1:
        raise ValidationError(
            f"Could not seed full-catalog demo row for '{card_name}': "
            "multiple oracle IDs matched the exact card name."
        )
    return str(rows[0]["oracle_id"])


def _add_full_catalog_demo_card(
    db_path: Path,
    *,
    inventory_slug: str,
    card_name: str,
    lang: str | None,
    quantity: int,
    condition_code: str,
    initial_finish: str,
    required_finish: str,
    location: str,
    acquisition_price: Decimal | None,
    acquisition_currency: str | None,
    notes: str | None,
    tags: str | None,
    request_id: str,
) -> Any:
    oracle_id = _resolve_full_catalog_demo_oracle_id(db_path, card_name=card_name)
    normalized_initial_finish = normalize_finish(initial_finish)
    normalized_required_finish = normalize_finish(required_finish)
    try:
        with connect(db_path) as connection:
            resolved_card = resolve_card_row(
                connection,
                scryfall_id=None,
                oracle_id=oracle_id,
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=lang,
                finish=required_finish,
            )
            try:
                validate_supported_finish(resolved_card["finishes_json"], normalized_initial_finish)
                seeded_initial_finish = initial_finish
            except ValidationError:
                # Full-catalog demo rows should follow the live oracle-resolution
                # policy rather than assuming the chosen printing still supports a
                # separate "initial" finish state.
                validate_supported_finish(resolved_card["finishes_json"], normalized_required_finish)
                seeded_initial_finish = required_finish
            result = add_card_with_connection(
                connection,
                inventory_slug=inventory_slug,
                inventory_display_name=None,
                scryfall_id=None,
                oracle_id=oracle_id,
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=lang,
                quantity=quantity,
                condition_code=condition_code,
                finish=seeded_initial_finish,
                language_code=None,
                location=location,
                acquisition_price=acquisition_price,
                acquisition_currency=acquisition_currency,
                notes=notes,
                tags=tags,
                resolved_card=resolved_card,
                actor_type=ACTOR_TYPE,
                actor_id=ACTOR_ID,
                request_id=request_id,
            )
            connection.commit()
            return result
    except (NotFoundError, ValidationError) as exc:
        raise ValidationError(
            f"Could not seed full-catalog demo row for '{card_name}': {exc}"
        ) from exc


def seed_small_demo_inventory_items(db_path: Path) -> None:
    bolt = add_card(
        db_path,
        inventory_slug="personal",
        inventory_display_name=None,
        scryfall_id="demo-bolt",
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
        quantity=2,
        condition_code="NM",
        finish="normal",
        language_code="en",
        location="Red Binder",
        acquisition_price=Decimal("2.25"),
        acquisition_currency="USD",
        notes=None,
        tags="burn,trade",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-add-bolt",
    )
    set_finish(
        db_path,
        inventory_slug="personal",
        item_id=bolt.item_id,
        finish="foil",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-finish-bolt",
    )
    set_notes(
        db_path,
        inventory_slug="personal",
        item_id=bolt.item_id,
        notes="Showcase card for the demo UI.",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-notes-bolt",
    )

    counterspell = add_card(
        db_path,
        inventory_slug="personal",
        inventory_display_name=None,
        scryfall_id="demo-counterspell",
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
        quantity=2,
        condition_code="NM",
        finish="normal",
        language_code="en",
        location="Blue Binder",
        acquisition_price=Decimal("1.10"),
        acquisition_currency="USD",
        notes=None,
        tags="control",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-add-counterspell",
    )
    set_tags(
        db_path,
        inventory_slug="personal",
        item_id=counterspell.item_id,
        tags="control,blue",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-tags-counterspell",
    )
    set_location(
        db_path,
        inventory_slug="personal",
        item_id=counterspell.item_id,
        location="Deck Box",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-location-counterspell",
    )
    set_quantity(
        db_path,
        inventory_slug="personal",
        item_id=counterspell.item_id,
        quantity=3,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-quantity-counterspell",
    )

    swords = add_card(
        db_path,
        inventory_slug="personal",
        inventory_display_name=None,
        scryfall_id=None,
        oracle_id="oracle-swords",
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang="ja",
        quantity=1,
        condition_code="NM",
        finish="normal",
        language_code="ja",
        location="Commander Case",
        acquisition_price=Decimal("3.00"),
        acquisition_currency="USD",
        notes=None,
        tags=None,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-add-swords",
    )
    set_condition(
        db_path,
        inventory_slug="personal",
        item_id=swords.item_id,
        condition_code="LP",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-condition-swords",
    )

    sol_ring = add_card(
        db_path,
        inventory_slug="personal",
        inventory_display_name=None,
        scryfall_id="demo-sol-ring",
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
        quantity=1,
        condition_code="NM",
        finish="normal",
        language_code="en",
        location="Commander Staples",
        acquisition_price=Decimal("5.00"),
        acquisition_currency="USD",
        notes=None,
        tags="commander,trade",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-add-sol-ring",
    )
    set_finish(
        db_path,
        inventory_slug="personal",
        item_id=sol_ring.item_id,
        finish="etched",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-finish-sol-ring",
    )
    set_tags(
        db_path,
        inventory_slug="personal",
        item_id=sol_ring.item_id,
        tags=None,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-clear-tags-sol-ring",
    )
    set_acquisition(
        db_path,
        inventory_slug="personal",
        item_id=sol_ring.item_id,
        acquisition_price=None,
        acquisition_currency=None,
        clear=True,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-clear-acquisition-sol-ring",
    )

    forest = add_card(
        db_path,
        inventory_slug="personal",
        inventory_display_name=None,
        scryfall_id="demo-forest",
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
        quantity=10,
        condition_code="NM",
        finish="normal",
        language_code="en",
        location="Land Box",
        acquisition_price=None,
        acquisition_currency=None,
        notes=None,
        tags="bulk",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-add-forest",
    )
    remove_card(
        db_path,
        inventory_slug="personal",
        item_id=forest.item_id,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-remove-forest",
    )


def seed_full_catalog_demo_inventory_items(db_path: Path, *, seed_demo_prices: bool) -> None:
    bolt = _add_full_catalog_demo_card(
        db_path,
        inventory_slug="personal",
        card_name="Lightning Bolt",
        lang=None,
        quantity=2,
        condition_code="NM",
        initial_finish="normal",
        required_finish="foil",
        location="Red Binder",
        acquisition_price=Decimal("2.25"),
        acquisition_currency="USD",
        notes=None,
        tags="burn,trade",
        request_id="seed-add-bolt",
    )
    set_finish(
        db_path,
        inventory_slug="personal",
        item_id=bolt.item_id,
        finish="foil",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-finish-bolt",
    )
    set_notes(
        db_path,
        inventory_slug="personal",
        item_id=bolt.item_id,
        notes="Showcase card for the demo UI.",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-notes-bolt",
    )

    counterspell = _add_full_catalog_demo_card(
        db_path,
        inventory_slug="personal",
        card_name="Counterspell",
        lang=None,
        quantity=2,
        condition_code="NM",
        initial_finish="normal",
        required_finish="normal",
        location="Blue Binder",
        acquisition_price=Decimal("1.10"),
        acquisition_currency="USD",
        notes=None,
        tags="control",
        request_id="seed-add-counterspell",
    )
    set_tags(
        db_path,
        inventory_slug="personal",
        item_id=counterspell.item_id,
        tags="control,blue",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-tags-counterspell",
    )
    set_location(
        db_path,
        inventory_slug="personal",
        item_id=counterspell.item_id,
        location="Deck Box",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-location-counterspell",
    )
    set_quantity(
        db_path,
        inventory_slug="personal",
        item_id=counterspell.item_id,
        quantity=3,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-quantity-counterspell",
    )

    swords = _add_full_catalog_demo_card(
        db_path,
        inventory_slug="personal",
        card_name="Swords to Plowshares",
        lang="ja",
        quantity=1,
        condition_code="NM",
        initial_finish="normal",
        required_finish="normal",
        location="Commander Case",
        acquisition_price=Decimal("3.00"),
        acquisition_currency="USD",
        notes=None,
        tags=None,
        request_id="seed-add-swords",
    )
    set_condition(
        db_path,
        inventory_slug="personal",
        item_id=swords.item_id,
        condition_code="LP",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-condition-swords",
    )

    sol_ring = _add_full_catalog_demo_card(
        db_path,
        inventory_slug="personal",
        card_name="Sol Ring",
        lang=None,
        quantity=1,
        condition_code="NM",
        initial_finish="normal",
        required_finish="etched",
        location="Commander Staples",
        acquisition_price=Decimal("5.00"),
        acquisition_currency="USD",
        notes=None,
        tags="commander,trade",
        request_id="seed-add-sol-ring",
    )
    set_finish(
        db_path,
        inventory_slug="personal",
        item_id=sol_ring.item_id,
        finish="etched",
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-finish-sol-ring",
    )
    set_tags(
        db_path,
        inventory_slug="personal",
        item_id=sol_ring.item_id,
        tags=None,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-clear-tags-sol-ring",
    )
    set_acquisition(
        db_path,
        inventory_slug="personal",
        item_id=sol_ring.item_id,
        acquisition_price=None,
        acquisition_currency=None,
        clear=True,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-clear-acquisition-sol-ring",
    )

    forest = _add_full_catalog_demo_card(
        db_path,
        inventory_slug="personal",
        card_name="Forest",
        lang=None,
        quantity=10,
        condition_code="NM",
        initial_finish="normal",
        required_finish="normal",
        location="Land Box",
        acquisition_price=None,
        acquisition_currency=None,
        notes=None,
        tags="bulk",
        request_id="seed-add-forest",
    )
    remove_card(
        db_path,
        inventory_slug="personal",
        item_id=forest.item_id,
        actor_type=ACTOR_TYPE,
        actor_id=ACTOR_ID,
        request_id="seed-remove-forest",
    )

    if seed_demo_prices:
        seed_price_snapshots(
            db_path,
            [
                (bolt.scryfall_id, "tcgplayer", "retail", "normal", "USD", "2026-04-01", 2.50, "demo-seed"),
                (bolt.scryfall_id, "tcgplayer", "retail", "foil", "USD", "2026-04-01", 6.75, "demo-seed"),
                (
                    counterspell.scryfall_id,
                    "tcgplayer",
                    "retail",
                    "normal",
                    "USD",
                    "2026-04-01",
                    1.25,
                    "demo-seed",
                ),
                (
                    swords.scryfall_id,
                    "tcgplayer",
                    "retail",
                    "normal",
                    "USD",
                    "2026-04-01",
                    3.50,
                    "demo-seed",
                ),
                (
                    sol_ring.scryfall_id,
                    "tcgplayer",
                    "retail",
                    "normal",
                    "USD",
                    "2026-04-01",
                    1.75,
                    "demo-seed",
                ),
                (
                    sol_ring.scryfall_id,
                    "tcgplayer",
                    "retail",
                    "etched",
                    "USD",
                    "2026-04-01",
                    4.75,
                    "demo-seed",
                ),
                (
                    forest.scryfall_id,
                    "tcgplayer",
                    "retail",
                    "normal",
                    "USD",
                    "2026-04-01",
                    0.15,
                    "demo-seed",
                ),
            ],
        )


def import_full_demo_catalog(db_path: Path, *, scryfall_json: Path) -> int:
    stats = import_scryfall_cards(db_path, scryfall_json)
    return int(stats.rows_written)


def bootstrap_demo_data(
    db_path: Path,
    *,
    full_catalog: bool = False,
    scryfall_json: Path | None = None,
    identifiers_json: Path | None = None,
    prices_json: Path | None = None,
) -> dict[str, int | str]:
    initialize_database(db_path)

    if full_catalog:
        if scryfall_json is None:
            raise ValueError("scryfall_json is required when full_catalog is enabled.")
        catalog_rows = import_full_demo_catalog(db_path, scryfall_json=scryfall_json)
        identifiers_rows = 0
        imported_price_rows = 0
        price_mode = "demo_seed"
        if identifiers_json is not None and prices_json is not None:
            identifiers_rows = int(import_mtgjson_identifiers(db_path, identifiers_json).rows_written)
            imported_price_rows = int(import_mtgjson_prices(db_path, prices_json).rows_written)
            price_mode = "imported"
        seed_demo_inventories(db_path)
        seed_full_catalog_demo_inventory_items(
            db_path,
            seed_demo_prices=(price_mode != "imported"),
        )
        return {
            "catalog_mode": "full",
            "catalog_rows": catalog_rows,
            "identifiers_rows": identifiers_rows,
            "price_rows": imported_price_rows if price_mode == "imported" else 7,
            "price_mode": price_mode,
        }

    seed_small_demo_catalog_and_prices(db_path)
    seed_demo_inventories(db_path)
    seed_small_demo_inventory_items(db_path)
    return {
        "catalog_mode": "small",
        "catalog_rows": 6,
    }


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)
    scryfall_json = Path(args.scryfall_json) if args.scryfall_json is not None else None
    identifiers_json = Path(args.identifiers_json) if args.identifiers_json is not None else None
    prices_json = Path(args.prices_json) if args.prices_json is not None else None

    if args.full_catalog and scryfall_json is None:
        parser.error("--scryfall-json is required with --full-catalog.")
    if not args.full_catalog and scryfall_json is not None:
        parser.error("--scryfall-json is only used with --full-catalog.")
    if args.full_catalog and (identifiers_json is None) != (prices_json is None):
        parser.error("--identifiers-json and --prices-json must be provided together with --full-catalog.")
    if not args.full_catalog and identifiers_json is not None:
        parser.error("--identifiers-json is only used with --full-catalog.")
    if not args.full_catalog and prices_json is not None:
        parser.error("--prices-json is only used with --full-catalog.")

    if db_path.exists():
        if not args.force:
            raise SystemExit(
                f"Database '{db_path}' already exists. Re-run with --force to overwrite it."
            )
        db_path.unlink()

    try:
        summary = bootstrap_demo_data(
            db_path,
            full_catalog=args.full_catalog,
            scryfall_json=scryfall_json,
            identifiers_json=identifiers_json,
            prices_json=prices_json,
        )
    except (NotFoundError, ValidationError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Bootstrapped frontend demo data at {db_path}")
    print(f"Catalog mode: {summary['catalog_mode']}")
    print("Inventories seeded: personal, trade-binder")
    if args.full_catalog:
        print(f"Scryfall cards imported: {summary['catalog_rows']}")
        if summary["price_mode"] == "imported":
            print(f"MTGJSON identifier links imported: {summary['identifiers_rows']}")
            print(f"MTGJSON price snapshots imported: {summary['price_rows']}")
            print("Price mode: imported MTGJSON pricing.")
        else:
            print("Price mode: curated demo seed pricing.")
        print("Curated owned-item demo rows resolved from imported catalog printings.")
    else:
        print("Cards seeded for search: Lightning Bolt, Counterspell, Swords to Plowshares, Sol Ring, Forest")
    print("Suggested API start command:")
    print(f"  (cd frontend && npm run backend:demo -- --db {db_path})")


if __name__ == "__main__":
    main()
