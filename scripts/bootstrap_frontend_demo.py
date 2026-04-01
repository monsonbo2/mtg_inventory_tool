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
                tcgplayer_product_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 'en', ?, ?, ?)
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
                    "1003",
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
    print("Inventory slug: personal")
    print("Cards seeded for search: Lightning Bolt, Counterspell, Forest")
    print("Suggested API start command:")
    print(f"  mtg-web-api --db {db_path}")


if __name__ == "__main__":
    main()
