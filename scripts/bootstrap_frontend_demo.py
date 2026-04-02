#!/usr/bin/env python3
"""Create a small, repeatable local dataset for frontend demo work."""

from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.inventory.service import (
    add_card,
    create_inventory,
    remove_card,
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap a local demo dataset for frontend work.")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite database path to create.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the target database file if it already exists.",
    )
    return parser


def seed_catalog_and_prices(db_path: Path) -> None:
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
            VALUES (?, ?, ?, ?, ?, ?, 'en', ?, ?, ?, ?)
            """,
            [
                (
                    "demo-bolt",
                    "oracle-bolt",
                    "Lightning Bolt",
                    "lea",
                    "Limited Edition Alpha",
                    "161",
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
                    "uncommon",
                    '["normal"]',
                    '{"small":"https://cards.scryfall.io/small/front/3/7/375fd2cb-443b-4be4-ad60-6d1a8e74f510.jpg?1562905275","normal":"https://cards.scryfall.io/normal/front/3/7/375fd2cb-443b-4be4-ad60-6d1a8e74f510.jpg?1562905275"}',
                    "1004",
                ),
                (
                    "demo-sol-ring",
                    "oracle-sol-ring",
                    "Sol Ring",
                    "cmr",
                    "Commander Legends",
                    "334",
                    "uncommon",
                    '["normal","etched"]',
                    '{"small":"https://cards.scryfall.io/small/front/5/8/58b26011-e103-45c4-a253-900f4e6b2eeb.jpg?1627501347","normal":"https://cards.scryfall.io/normal/front/5/8/58b26011-e103-45c4-a253-900f4e6b2eeb.jpg?1627501347"}',
                    "1005",
                ),
            ],
        )
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
            [
                ("demo-bolt", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 2.50, "demo-seed"),
                ("demo-bolt", "tcgplayer", "retail", "foil", "USD", "2026-04-01", 6.75, "demo-seed"),
                ("demo-counterspell", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 1.25, "demo-seed"),
                ("demo-counterspell", "tcgplayer", "retail", "foil", "USD", "2026-04-01", 4.25, "demo-seed"),
                ("demo-forest", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 0.15, "demo-seed"),
                ("demo-swords", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 3.50, "demo-seed"),
                ("demo-sol-ring", "tcgplayer", "retail", "normal", "USD", "2026-04-01", 1.75, "demo-seed"),
                ("demo-sol-ring", "tcgplayer", "retail", "etched", "USD", "2026-04-01", 4.75, "demo-seed"),
            ],
        )
        connection.commit()


def bootstrap_demo_data(db_path: Path) -> None:
    initialize_database(db_path)
    seed_catalog_and_prices(db_path)

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
        scryfall_id="demo-swords",
        tcgplayer_product_id=None,
        name=None,
        set_code=None,
        collector_number=None,
        lang=None,
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


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    db_path = Path(args.db)

    if db_path.exists():
        if not args.force:
            raise SystemExit(
                f"Database '{db_path}' already exists. Re-run with --force to overwrite it."
            )
        db_path.unlink()

    bootstrap_demo_data(db_path)
    print(f"Bootstrapped frontend demo data at {db_path}")
    print("Inventories seeded: personal, trade-binder")
    print("Cards seeded for search: Lightning Bolt, Counterspell, Swords to Plowshares, Sol Ring, Forest")
    print("Suggested API start command:")
    print(f"  mtg-web-api --db {db_path}")


if __name__ == "__main__":
    main()
