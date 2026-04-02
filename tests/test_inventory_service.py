"""Service-level workflow tests for inventory maintenance and reporting."""

from __future__ import annotations

from decimal import Decimal
import json
import sqlite3
import tempfile
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import ConflictError, NotFoundError, ValidationError
from mtg_source_stack.inventory.response_models import (
    AddCardResult,
    MergeRowsResult,
    RemoveCardResult,
    SetAcquisitionResult,
    SetConditionResult,
    SetFinishResult,
    SetLocationResult,
    SetNotesResult,
    SetQuantityResult,
    SetTagsResult,
    SplitRowResult,
    serialize_response,
)
from mtg_source_stack.inventory.service import (
    add_card,
    create_inventory,
    inventory_report,
    list_owned_filtered,
    list_price_gaps,
    merge_rows,
    reconcile_prices,
    remove_card,
    search_cards,
    set_acquisition,
    set_condition,
    set_finish,
    set_location,
    set_notes,
    set_quantity,
    set_tags,
    split_row,
    valuation_filtered,
)
from tests.common import RepoSmokeTestCase, materialize_fixture_bundle


class InventoryServiceTest(RepoSmokeTestCase):
    def test_search_cards_returns_list_typed_catalog_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        lang,
                        finishes_json,
                        image_uris_json
                    )
                    VALUES (
                        'search-card-1',
                        'oracle-search-1',
                        'Search Test Card',
                        'tst',
                        'Test Set',
                        '9',
                        'en',
                        '["nonfoil","foil"]',
                        '{"small":"https://example.test/cards/search-card-1-small.jpg","normal":"https://example.test/cards/search-card-1-normal.jpg"}'
                    )
                    """
                )
                connection.commit()

            rows = search_cards(db_path, query="Search Test", exact=False, limit=10)

            # The service layer should keep catalog finishes machine-friendly so
            # the API can return a real list and let formatters decide how to
            # display it later.
            self.assertEqual(1, len(rows))
            self.assertEqual(["normal", "foil"], rows[0].finishes)
            self.assertEqual("https://example.test/cards/search-card-1-small.jpg", rows[0].image_uri_small)
            self.assertEqual("https://example.test/cards/search-card-1-normal.jpg", rows[0].image_uri_normal)
            self.assertEqual(["normal", "foil"], serialize_response(rows)[0]["finishes"])
            self.assertEqual(
                "https://example.test/cards/search-card-1-small.jpg",
                serialize_response(rows)[0]["image_uri_small"],
            )

    def test_create_inventory_returns_typed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            result = create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description="Main binder inventory",
            )

            self.assertEqual(1, result.inventory_id)
            self.assertEqual("personal", result.slug)
            self.assertEqual("Personal Collection", result.display_name)
            self.assertEqual("Main binder inventory", result.description)
            self.assertEqual(
                {
                    "inventory_id": 1,
                    "slug": "personal",
                    "display_name": "Personal Collection",
                    "description": "Main binder inventory",
                },
                serialize_response(result),
            )

    def test_write_services_require_prepared_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"

            with self.assertRaisesRegex(NotFoundError, "does not exist"):
                create_inventory(
                    db_path,
                    slug="personal",
                    display_name="Personal Collection",
                    description=None,
                )

    def test_finish_changes_must_match_supported_card_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        finishes_json
                    )
                    VALUES ('finish-guard-1', 'finish-guard-oracle-1', 'Finish Guard Card', 'tst', 'Test Set', '18', '["normal"]')
                    """
                )
                connection.commit()

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            with self.assertRaisesRegex(ValidationError, "Available finishes: normal"):
                add_card(
                    db_path,
                    inventory_slug="personal",
                    inventory_display_name=None,
                    scryfall_id="finish-guard-1",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    quantity=1,
                    condition_code="NM",
                    finish="foil",
                    language_code="en",
                    location="Binder A",
                    acquisition_price=None,
                    acquisition_currency=None,
                    notes=None,
                    tags=None,
                )

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="finish-guard-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=2,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )

            with self.assertRaisesRegex(ValidationError, "Available finishes: normal"):
                set_finish(
                    db_path,
                    inventory_slug="personal",
                    item_id=added.item_id,
                    finish="foil",
                )

            with self.assertRaisesRegex(ValidationError, "Available finishes: normal"):
                split_row(
                    db_path,
                    inventory_slug="personal",
                    item_id=added.item_id,
                    quantity=1,
                    condition_code=None,
                    finish="foil",
                    language_code=None,
                    location="Binder B",
                )

    def test_mutation_services_return_typed_results_for_direct_api_use(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        finishes_json
                    )
                    VALUES ('typed-edit-1', 'typed-edit-oracle-1', 'Typed Edit Card', 'tst', 'Test Set', '17', '["normal","foil"]')
                    """
                )
                connection.commit()

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            # Walk one row through the main mutation surface so the typed write
            # contract is checked as a cohesive API-facing workflow, not just
            # one method at a time in isolation.
            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="typed-edit-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=4,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags="deck",
            )

            quantity_result = set_quantity(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                quantity=3,
            )
            self.assertIsInstance(quantity_result, SetQuantityResult)
            self.assertEqual("set_quantity", quantity_result.operation)
            self.assertEqual(4, quantity_result.old_quantity)
            self.assertEqual(3, quantity_result.quantity)
            self.assertEqual(4, serialize_response(quantity_result)["old_quantity"])
            self.assertEqual("set_quantity", serialize_response(quantity_result)["operation"])

            finish_result = set_finish(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                finish="foil",
            )
            self.assertIsInstance(finish_result, SetFinishResult)
            self.assertEqual("set_finish", finish_result.operation)
            self.assertEqual("normal", finish_result.old_finish)
            self.assertEqual("foil", finish_result.finish)

            location_result = set_location(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                location="Deck Box",
            )
            self.assertIsInstance(location_result, SetLocationResult)
            self.assertEqual("set_location", location_result.operation)
            self.assertEqual("Binder A", location_result.old_location)
            self.assertEqual("Deck Box", location_result.location)
            self.assertFalse(location_result.merged)

            condition_result = set_condition(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                condition_code="LP",
            )
            self.assertIsInstance(condition_result, SetConditionResult)
            self.assertEqual("set_condition", condition_result.operation)
            self.assertEqual("NM", condition_result.old_condition_code)
            self.assertEqual("LP", condition_result.condition_code)
            self.assertFalse(condition_result.merged)

            notes_result = set_notes(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                notes="Feature row for the demo",
            )
            self.assertIsInstance(notes_result, SetNotesResult)
            self.assertEqual("set_notes", notes_result.operation)
            self.assertIsNone(notes_result.old_notes)
            self.assertEqual("Feature row for the demo", notes_result.notes)

            tags_result = set_tags(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                tags="trade, staple",
            )
            self.assertIsInstance(tags_result, SetTagsResult)
            self.assertEqual("set_tags", tags_result.operation)
            self.assertEqual(["deck"], tags_result.old_tags)
            self.assertEqual(["trade", "staple"], tags_result.tags)
            self.assertEqual(["trade", "staple"], serialize_response(tags_result)["tags"])

            acquisition_result = set_acquisition(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                acquisition_price=Decimal("2.50"),
                acquisition_currency="USD",
            )
            self.assertIsInstance(acquisition_result, SetAcquisitionResult)
            self.assertEqual("set_acquisition", acquisition_result.operation)
            self.assertIsNone(acquisition_result.old_acquisition_price)
            self.assertIsNone(acquisition_result.old_acquisition_currency)
            self.assertEqual("2.5", serialize_response(acquisition_result)["acquisition_price"])

            split_result = split_row(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                quantity=1,
                condition_code=None,
                finish=None,
                language_code=None,
                location="Binder B",
            )
            self.assertIsInstance(split_result, SplitRowResult)
            self.assertFalse(split_result.merged_into_existing)
            self.assertEqual(1, split_result.moved_quantity)
            self.assertEqual(3, split_result.source_old_quantity)
            self.assertEqual(2, split_result.source_quantity)
            self.assertFalse(split_result.source_deleted)

            merge_result = merge_rows(
                db_path,
                inventory_slug="personal",
                source_item_id=split_result.item_id,
                target_item_id=added.item_id,
            )
            self.assertIsInstance(merge_result, MergeRowsResult)
            self.assertEqual(split_result.item_id, merge_result.merged_source_item_id)
            self.assertEqual(1, merge_result.source_quantity)
            self.assertEqual(2, merge_result.target_old_quantity)
            self.assertEqual(3, merge_result.quantity)

            remove_result = remove_card(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
            )
            self.assertIsInstance(remove_result, RemoveCardResult)
            self.assertEqual(added.item_id, remove_result.item_id)
            self.assertEqual(3, remove_result.quantity)
            self.assertEqual("foil", remove_result.finish)
            self.assertEqual("LP", remove_result.condition_code)
            self.assertEqual("Deck Box", remove_result.location)

            with connect(db_path) as connection:
                remaining = connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
            self.assertEqual(0, remaining)

    def test_service_facade_raises_domain_errors_for_not_found_validation_and_conflict_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

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
                        finishes_json
                    )
                    VALUES (?, ?, 'Conflict Test Card', 'tst', 'Test Set', ?, '["normal","foil"]')
                    """,
                    [
                        ("conflict-card-1", "conflict-oracle-1", "21"),
                    ],
                )
                connection.commit()

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            first_row = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="conflict-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )
            add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="conflict-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder B",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )

            # These are the main failure categories the future HTTP layer will
            # map onto 404 / 400 / 409 style responses.
            with self.assertRaises(NotFoundError):
                set_notes(
                    db_path,
                    inventory_slug="personal",
                    item_id=99,
                    notes="Missing row",
                )

            with self.assertRaises(ValidationError):
                set_finish(
                    db_path,
                    inventory_slug="personal",
                    item_id=first_row.item_id,
                    finish="sparkly",
                )

            with self.assertRaises(ConflictError):
                set_location(
                    db_path,
                    inventory_slug="personal",
                    item_id=first_row.item_id,
                    location="Binder B",
                )

    def test_write_services_return_typed_models_and_capture_audit_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        finishes_json
                    )
                    VALUES ('typed-card-1', 'oracle-typed-1', 'Typed Test Card', 'tst', 'Test Set', '7', '["normal"]')
                    """
                )
                connection.commit()

            add_result = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name="Personal Collection",
                scryfall_id="typed-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=2,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Binder 1",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags="commander,trade",
                actor_type="user",
                actor_id="demo-user",
                request_id="req-add",
            )

            self.assertIsInstance(add_result, AddCardResult)
            self.assertEqual(["commander", "trade"], add_result.tags)

            # The direct service API should accept actor/request metadata once
            # and preserve it all the way into the audit table.
            set_notes_result = set_notes(
                db_path,
                inventory_slug="personal",
                item_id=add_result.item_id,
                notes="Front binder copy",
                actor_type="user",
                actor_id="demo-user",
                request_id="req-notes",
            )

            self.assertIsInstance(set_notes_result, SetNotesResult)
            self.assertIsNone(set_notes_result.old_notes)
            self.assertEqual("Front binder copy", set_notes_result.notes)
            self.assertEqual("Front binder copy", serialize_response(set_notes_result)["notes"])

            with connect(db_path) as connection:
                audit_rows = connection.execute(
                    """
                    SELECT action, actor_type, actor_id, request_id
                    FROM inventory_audit_log
                    ORDER BY id
                    """
                ).fetchall()

            self.assertEqual(
                [
                    ("add_card", "user", "demo-user", "req-add"),
                    ("set_notes", "user", "demo-user", "req-notes"),
                ],
                [
                    (row["action"], row["actor_type"], row["actor_id"], row["request_id"])
                    for row in audit_rows
                ],
            )

    def test_price_gaps_and_reconcile_use_latest_snapshot_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        finishes_json
                    )
                    VALUES ('gap-card-1', 'oracle-1', 'Gap Test Card', 'tst', 'Test Set', '1', '["normal","foil"]')
                    """
                )
                inventory_id = connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name)
                    VALUES ('personal', 'Personal Collection')
                    RETURNING id
                    """
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO inventory_items (
                        inventory_id,
                        scryfall_id,
                        quantity,
                        condition_code,
                        finish,
                        language_code,
                        location,
                        tags_json
                    )
                    VALUES (?, 'gap-card-1', 1, 'NM', 'normal', 'en', 'Binder', '[]')
                    """,
                    (inventory_id,),
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
                        ("gap-card-1", "tcgplayer", "retail", "normal", "USD", "2026-03-01", 1.50, "test"),
                        ("gap-card-1", "tcgplayer", "retail", "foil", "USD", "2026-03-29", 5.00, "test"),
                    ],
                )

            gap_rows = list_price_gaps(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=None,
            )
            reconcile_preview = reconcile_prices(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                apply_changes=False,
            )

            self.assertEqual(1, len(gap_rows))
            self.assertEqual("gap-card-1", gap_rows[0].scryfall_id)
            self.assertEqual(["foil"], gap_rows[0].available_finishes)
            self.assertEqual("foil", gap_rows[0].suggested_finish)
            self.assertEqual("single priced finish", gap_rows[0].reconcile_status)

            self.assertEqual(1, reconcile_preview.rows_seen)
            self.assertEqual(1, reconcile_preview.rows_fixable)
            self.assertEqual(["foil"], reconcile_preview.suggested_rows[0].available_finishes)

            with self.assertRaisesRegex(ValueError, "suggestion-only"):
                reconcile_prices(
                    db_path,
                    inventory_slug="personal",
                    provider="tcgplayer",
                    apply_changes=True,
                )

    def test_latest_price_queries_ignore_non_usd_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number,
                        image_uris_json
                    )
                    VALUES (
                        'price-card-1',
                        'oracle-1',
                        'Price Test Card',
                        'tst',
                        'Test Set',
                        '1',
                        '{"small":"https://example.test/cards/price-card-1-small.jpg","normal":"https://example.test/cards/price-card-1-normal.jpg"}'
                    )
                    """
                )
                inventory_id = connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name)
                    VALUES ('personal', 'Personal Collection')
                    RETURNING id
                    """
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO inventory_items (
                        inventory_id,
                        scryfall_id,
                        quantity,
                        condition_code,
                        finish,
                        language_code,
                        location,
                        tags_json
                    )
                    VALUES (?, 'price-card-1', 2, 'NM', 'normal', 'en', 'Binder', '[]')
                    """,
                    (inventory_id,),
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
                        ("price-card-1", "tcgplayer", "retail", "normal", "USD", "2026-03-27", 2.00, "test"),
                        ("price-card-1", "tcgplayer", "retail", "normal", "EUR", "2026-03-28", 9.99, "legacy"),
                        ("price-card-1", "tcgplayer", "retail", "normal", "USD", "2026-03-29", 2.50, "test"),
                    ],
                )

            owned_rows = list_owned_filtered(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=None,
                query=None,
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
            )
            valuation_rows = valuation_filtered(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                query=None,
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
            )

            self.assertEqual(1, len(owned_rows))
            self.assertEqual("USD", owned_rows[0].currency)
            self.assertEqual("https://example.test/cards/price-card-1-small.jpg", owned_rows[0].image_uri_small)
            self.assertEqual("https://example.test/cards/price-card-1-normal.jpg", owned_rows[0].image_uri_normal)
            self.assertEqual(Decimal("2.5"), owned_rows[0].unit_price)
            self.assertEqual(Decimal("5.0"), owned_rows[0].est_value)
            self.assertIsNone(owned_rows[0].acquisition_price)
            self.assertIsNone(owned_rows[0].acquisition_currency)
            self.assertIsNone(owned_rows[0].notes)
            self.assertEqual([], owned_rows[0].tags)

            self.assertEqual(
                [
                    {
                        "provider": "tcgplayer",
                        "currency": "USD",
                        "item_rows": 1,
                        "total_cards": 2,
                        "total_value": "5.0",
                    }
                ],
                serialize_response(valuation_rows),
            )

    def test_latest_price_queries_treat_nonfoil_snapshots_as_normal_finish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with connect(db_path) as connection:
                connection.execute(
                    """
                    INSERT INTO mtg_cards (
                        scryfall_id,
                        oracle_id,
                        name,
                        set_code,
                        set_name,
                        collector_number
                    )
                    VALUES ('price-card-2', 'oracle-2', 'Finish Alias Test', 'tst', 'Test Set', '2')
                    """
                )
                inventory_id = connection.execute(
                    """
                    INSERT INTO inventories (slug, display_name)
                    VALUES ('personal', 'Personal Collection')
                    RETURNING id
                    """
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO inventory_items (
                        inventory_id,
                        scryfall_id,
                        quantity,
                        condition_code,
                        finish,
                        language_code,
                        location,
                        tags_json
                    )
                    VALUES (?, 'price-card-2', 1, 'NM', 'normal', 'en', 'Binder', '[]')
                    """,
                    (inventory_id,),
                )
                connection.execute(
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
                    VALUES ('price-card-2', 'tcgplayer', 'retail', 'nonfoil', 'USD', '2026-03-30', 4.25, 'legacy')
                    """
                )
                connection.commit()

            owned_rows = list_owned_filtered(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=None,
                query=None,
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
            )
            gap_rows = list_price_gaps(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=None,
            )

            self.assertEqual(1, len(owned_rows))
            self.assertEqual(Decimal("4.25"), owned_rows[0].unit_price)
            self.assertEqual([], gap_rows)

    def test_reconcile_prices_only_suggests_finish_when_one_priced_finish_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "shiny_bird_foil_only",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )
            scryfall_path = bundle["scryfall.json"]
            identifiers_path = bundle["identifiers.json"]
            prices_path = bundle["prices.json"]

            # The fixture only has a foil-priced version, which forces the
            # reconcile flow to detect and fix a historically mismatched
            # inventory finish.
            import_output = self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.assertIn("import-prices: seen=1 written=1 skipped=0", import_output)

            create_output = self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.assertIn("Created inventory 'personal'", create_output)

            with connect(db_path) as connection:
                inventory_id = connection.execute(
                    "SELECT id FROM inventories WHERE slug = 'personal'"
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO inventory_items (
                        inventory_id,
                        scryfall_id,
                        quantity,
                        condition_code,
                        finish,
                        language_code,
                        location,
                        tags_json
                    )
                    VALUES (?, 'foil-only-1', 1, 'NM', 'normal', 'en', '', '[]')
                    """,
                    (inventory_id,),
                )
                connection.commit()

            gap_output = self.run_cli(
                "price-gaps",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Shiny Bird", gap_output)
            self.assertIn("foil", gap_output)
            self.assertIn("single priced finish", gap_output)

            # Reconciliation should now stay suggestion-only even when it can
            # see a single likely finish from current pricing data.
            preview_output = self.run_cli(
                "reconcile-prices",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Mode: suggestion only (no changes applied)", preview_output)
            self.assertIn("Suggested rows", preview_output)
            self.assertIn("Shiny Bird", preview_output)

            reconcile_output = self.run_failing_cli(
                "reconcile-prices",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--apply",
            )
            self.assertEqual(2, reconcile_output.returncode)
            self.assertIn("suggestion-only", reconcile_output.stderr)

            owned_output = self.run_cli(
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Shiny Bird", owned_output)
            self.assertIn("normal", owned_output)

    def test_inventory_health_reports_missing_data_and_stale_prices(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "health-card-1",
                    "oracle_id": "health-oracle-1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                },
                {
                    "id": "health-card-2",
                    "oracle_id": "health-oracle-2",
                    "name": "Shiny Bird",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "7",
                    "lang": "en",
                    "rarity": "rare",
                    "released_at": "2026-01-01",
                    "colors": ["G"],
                    "color_identity": ["G"],
                    "finishes": ["nonfoil", "foil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 222,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-health-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "health-card-1",
                            "tcgplayerProductId": "534658",
                        },
                    },
                    "uuid-health-2": {
                        "name": "Shiny Bird",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "health-card-2",
                            "tcgplayerProductId": "222",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-health-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2020-01-01": 2.92}},
                            }
                        }
                    },
                    "uuid-health-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"foil": {"2026-03-27": 5.00}},
                            }
                        }
                    },
                }
            }

            # Seed deliberately messy rows so the report has examples for every
            # health bucket: missing prices, missing metadata, stale prices, and
            # duplicate-like holdings.
            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "health-card-1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--notes",
                "Merged source acquisition from item 99: 1.5 USD",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "health-card-1",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "health-card-2",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Deck Box",
                "--tags",
                "foil project",
            )

            health_output = self.run_cli(
                "inventory-health",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--stale-days",
                "30",
                "--limit",
                "5",
            )
            self.assertIn("Inventory health report", health_output)
            self.assertIn("Rows missing current prices: 1", health_output)
            self.assertIn("Rows missing location: 1", health_output)
            self.assertIn("Rows missing tags: 2", health_output)
            self.assertIn("Rows with merged acquisition notes: 1", health_output)
            self.assertIn("Rows with stale prices: 2", health_output)
            self.assertIn("Duplicate-like groups: 1", health_output)
            self.assertIn("Missing current-price matches", health_output)
            self.assertIn("Missing location", health_output)
            self.assertIn("Missing tags", health_output)
            self.assertIn("Merged acquisition notes", health_output)
            self.assertIn("Stale prices", health_output)
            self.assertIn("Duplicate-like groups", health_output)
            self.assertIn("Lightning Bolt", health_output)
            self.assertIn("Shiny Bird", health_output)
            self.assertIn("2020-01-01", health_output)

    def test_set_acquisition_split_row_and_merge_rows_flow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "edit-card-1",
                    "oracle_id": "edit-oracle-1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                },
                {
                    "id": "edit-card-2",
                    "oracle_id": "edit-oracle-2",
                    "name": "Counterspell",
                    "set": "7ed",
                    "set_name": "Seventh Edition",
                    "collector_number": "73",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2001-04-11",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 123456,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-edit-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "edit-card-1",
                            "tcgplayerProductId": "534658",
                        },
                    },
                    "uuid-edit-2": {
                        "name": "Counterspell",
                        "setCode": "7ed",
                        "identifiers": {
                            "scryfallId": "edit-card-2",
                            "tcgplayerProductId": "123456",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-edit-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.92}},
                            }
                        }
                    },
                    "uuid-edit-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.10}},
                            }
                        }
                    },
                }
            }

            # Set up one editable row plus a second printing so the test can
            # cover both successful row surgery and a guarded merge failure.
            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "edit-card-1",
                "--quantity",
                "4",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Binder A",
                "--notes",
                "Main playset",
                "--tags",
                "deck",
            )

            set_acquisition_output = self.run_cli(
                "set-acquisition",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--price",
                "1.75",
                "--currency",
                "usd",
            )
            self.assertIn("Safety snapshot created", set_acquisition_output)
            self.assertIn("Updated card acquisition", set_acquisition_output)
            self.assertIn("Previous acquisition: (none)", set_acquisition_output)
            self.assertIn("Acquisition now: 1.75 USD", set_acquisition_output)

            split_output = self.run_cli(
                "split-row",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--item-id",
                "1",
                "--quantity",
                "1",
                "--location",
                "Deck Box",
            )
            self.assertIn("Safety snapshot created", split_output)
            self.assertIn("Split inventory row", split_output)
            self.assertIn("Moved quantity: 1", split_output)
            self.assertIn("Source quantity now: 3", split_output)
            self.assertIn("Target item ID: 2", split_output)
            self.assertIn("Target quantity now: 1", split_output)
            self.assertIn("Merged into existing row: no", split_output)

            # The split should leave two independently addressable rows before
            # the explicit merge command recombines them.
            owned_after_split = self.run_cli(
                "list-owned",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
            )
            self.assertIn("Binder A", owned_after_split)
            self.assertIn("Deck Box", owned_after_split)

            merge_output = self.run_cli(
                "merge-rows",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--source-item-id",
                "2",
                "--target-item-id",
                "1",
            )
            self.assertIn("Safety snapshot created", merge_output)
            self.assertIn("Merged inventory rows", merge_output)
            self.assertIn("Source item ID: 2", merge_output)
            self.assertIn("Source quantity removed: 1", merge_output)
            self.assertIn("Target item ID: 1", merge_output)
            self.assertIn("Target previous quantity: 3", merge_output)
            self.assertIn("Quantity now: 4", merge_output)
            self.assertIn("Acquisition: 1.75 USD", merge_output)

            connection = sqlite3.connect(db_path)
            rows = connection.execute(
                """
                SELECT id, quantity, location, acquisition_price, acquisition_currency
                FROM inventory_items
                WHERE scryfall_id = 'edit-card-1'
                ORDER BY id
                """
            ).fetchall()
            connection.close()

            # Inspecting the table directly keeps the test focused on stored
            # state, not just formatted CLI output.
            self.assertEqual([(1, 4, "Binder A", 1.75, "USD")], rows)

            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "edit-card-2",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Blue Binder",
            )

            merge_failure = self.run_failing_cli(
                "merge-rows",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--source-item-id",
                "3",
                "--target-item-id",
                "1",
            )
            self.assertNotEqual(0, merge_failure.returncode)
            self.assertIn("same printing", merge_failure.stderr)

    def test_add_card_normalizes_identity_fields_before_merging_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            bundle = materialize_fixture_bundle(
                tmp,
                "lightning_bolt",
                "scryfall.json",
                "identifiers.json",
                "prices.json",
            )

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(bundle["scryfall.json"]),
                "--identifiers-json",
                str(bundle["identifiers.json"]),
                "--prices-json",
                str(bundle["prices.json"]),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )

            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--language-code",
                "en",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "s1",
                "--quantity",
                "1",
                "--condition",
                "nm",
                "--language-code",
                "EN",
                "--finish",
                "nonfoil",
            )

            # Case and alias normalization should collapse these into the same
            # logical row instead of creating near-duplicate entries.
            connection = sqlite3.connect(db_path)
            rows = connection.execute(
                """
                SELECT quantity, condition_code, language_code
                FROM inventory_items
                """
            ).fetchall()
            connection.close()

            self.assertEqual([(2, "NM", "en")], rows)

    def test_inventory_report_filters_health_payload_to_matching_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"

            scryfall_payload = [
                {
                    "id": "report-filter-a",
                    "oracle_id": "report-filter-oracle-a",
                    "name": "Alpha",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "1",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2026-01-01",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 1001,
                },
                {
                    "id": "report-filter-b",
                    "oracle_id": "report-filter-oracle-b",
                    "name": "Beta",
                    "set": "abc",
                    "set_name": "Example Set",
                    "collector_number": "2",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2026-01-01",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 1002,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-report-filter-a": {
                        "name": "Alpha",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "report-filter-a",
                            "tcgplayerProductId": "1001",
                        },
                    },
                    "uuid-report-filter-b": {
                        "name": "Beta",
                        "setCode": "abc",
                        "identifiers": {
                            "scryfallId": "report-filter-b",
                            "tcgplayerProductId": "1002",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-report-filter-a": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.00}},
                            }
                        }
                    },
                    "uuid-report-filter-b": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.00}},
                            }
                        }
                    },
                }
            }

            # Add one duplicate-like group and one unrelated row, then call the
            # service function directly to verify health data is filtered to the
            # report query instead of being computed globally and sliced later.
            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-filter-a",
                "--quantity",
                "1",
                "--location",
                "Box 1",
                "--tags",
                "dup",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-filter-a",
                "--quantity",
                "1",
                "--location",
                "Box 2",
                "--tags",
                "dup",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-filter-b",
                "--quantity",
                "1",
                "--location",
                "Box 3",
                "--tags",
                "solo",
            )

            report = inventory_report(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                query="Beta",
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
                limit=5,
                stale_days=30,
            )

            self.assertEqual(1, report.summary.item_rows)
            self.assertEqual(0, report.health.summary.duplicate_groups)
            self.assertEqual([], report.health.duplicate_groups)

            # Filtering down to one row from a duplicate-like group should also
            # clear the duplicate warning instead of inheriting the full-group
            # result from the inventory-wide health scan.
            one_side_report = inventory_report(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                query=None,
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location="Box 1",
                tags=None,
                limit=5,
                stale_days=30,
            )

            self.assertEqual(1, one_side_report.summary.item_rows)
            self.assertEqual(0, one_side_report.health.summary.duplicate_groups)
            self.assertEqual([], one_side_report.health.duplicate_groups)

    def test_export_csv_and_inventory_report_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            db_path = tmp / "collection.db"
            scryfall_path = tmp / "scryfall.json"
            identifiers_path = tmp / "identifiers.json"
            prices_path = tmp / "prices.json"
            export_path = tmp / "exports" / "lightning_only.csv"
            report_text_path = tmp / "reports" / "inventory_report.txt"
            report_json_path = tmp / "reports" / "inventory_report.json"
            report_csv_path = tmp / "reports" / "inventory_report_rows.csv"

            scryfall_payload = [
                {
                    "id": "report-card-1",
                    "oracle_id": "report-oracle-1",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "1993-08-05",
                    "colors": ["R"],
                    "color_identity": ["R"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 534658,
                },
                {
                    "id": "report-card-2",
                    "oracle_id": "report-oracle-2",
                    "name": "Counterspell",
                    "set": "7ed",
                    "set_name": "Seventh Edition",
                    "collector_number": "73",
                    "lang": "en",
                    "rarity": "common",
                    "released_at": "2001-04-11",
                    "colors": ["U"],
                    "color_identity": ["U"],
                    "finishes": ["nonfoil"],
                    "legalities": {"commander": "legal"},
                    "purchase_uris": {"tcgplayer": "https://example.test/tcg"},
                    "tcgplayer_id": 123456,
                },
            ]
            identifiers_payload = {
                "data": {
                    "uuid-report-1": {
                        "name": "Lightning Bolt",
                        "setCode": "lea",
                        "identifiers": {
                            "scryfallId": "report-card-1",
                            "tcgplayerProductId": "534658",
                        },
                    },
                    "uuid-report-2": {
                        "name": "Counterspell",
                        "setCode": "7ed",
                        "identifiers": {
                            "scryfallId": "report-card-2",
                            "tcgplayerProductId": "123456",
                        },
                    },
                }
            }
            prices_payload = {
                "data": {
                    "uuid-report-1": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 2.92}},
                            }
                        }
                    },
                    "uuid-report-2": {
                        "paper": {
                            "tcgplayer": {
                                "currency": "USD",
                                "retail": {"normal": {"2026-03-27": 1.10}},
                            }
                        }
                    },
                }
            }

            # Seed one fully annotated row and one intentionally incomplete row
            # so the exported reports contain both valuation data and health
            # warnings.
            scryfall_path.write_text(json.dumps(scryfall_payload), encoding="utf-8")
            identifiers_path.write_text(json.dumps(identifiers_payload), encoding="utf-8")
            prices_path.write_text(json.dumps(prices_payload), encoding="utf-8")

            self.run_importer(
                "import-all",
                "--db",
                str(db_path),
                "--scryfall-json",
                str(scryfall_path),
                "--identifiers-json",
                str(identifiers_path),
                "--prices-json",
                str(prices_path),
            )
            self.run_cli(
                "create-inventory",
                "--db",
                str(db_path),
                "--slug",
                "personal",
                "--display-name",
                "Personal Collection",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-card-1",
                "--quantity",
                "2",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "Red Binder",
                "--tags",
                "burn",
                "--acquisition-price",
                "1.25",
                "--acquisition-currency",
                "USD",
            )
            self.run_cli(
                "add-card",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--scryfall-id",
                "report-card-2",
                "--quantity",
                "1",
                "--condition",
                "NM",
                "--finish",
                "normal",
                "--location",
                "",
            )

            export_output = self.run_cli(
                "export-csv",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--query",
                "Lightning",
                "--output",
                str(export_path),
            )
            self.assertIn("Exported inventory rows to CSV", export_output)
            self.assertIn("Rows exported: 1", export_output)
            self.assertIn(str(export_path), export_output)
            export_text = export_path.read_text(encoding="utf-8")
            self.assertIn("inventory,provider,item_id,scryfall_id,card_name", export_text)
            self.assertIn("Lightning Bolt", export_text)
            self.assertNotIn("Counterspell", export_text)

            # The inventory report command emits the human-readable summary plus
            # machine-readable JSON/CSV artifacts for downstream tooling.
            report_output = self.run_cli(
                "inventory-report",
                "--db",
                str(db_path),
                "--inventory",
                "personal",
                "--provider",
                "tcgplayer",
                "--limit",
                "5",
                "--report-out",
                str(report_text_path),
                "--report-out-json",
                str(report_json_path),
                "--report-out-csv",
                str(report_csv_path),
            )
            self.assertIn("Inventory report", report_output)
            self.assertIn("Valuation totals", report_output)
            self.assertIn("Tracked acquisition totals", report_output)
            self.assertIn("Top holdings by estimated value", report_output)
            self.assertIn("Health summary", report_output)
            self.assertIn("Text report saved to:", report_output)
            self.assertIn("JSON report saved to:", report_output)
            self.assertIn("CSV report saved to:", report_output)
            self.assertTrue(report_text_path.exists())
            self.assertTrue(report_json_path.exists())
            self.assertTrue(report_csv_path.exists())

            report_text = report_text_path.read_text(encoding="utf-8")
            self.assertIn("Item rows: 2", report_text)
            self.assertIn("Total cards: 3", report_text)
            self.assertIn("Missing location rows: 1", report_text)
            self.assertIn("Missing tag rows: 1", report_text)

            report_json = json.loads(report_json_path.read_text(encoding="utf-8"))
            self.assertEqual("personal", report_json["inventory"])
            self.assertEqual("tcgplayer", report_json["provider"])
            self.assertEqual(2, report_json["summary"]["item_rows"])
            self.assertEqual(3, report_json["summary"]["total_cards"])
            self.assertEqual(2, len(report_json["rows"]))

            report_csv_text = report_csv_path.read_text(encoding="utf-8")
            self.assertIn("Lightning Bolt", report_csv_text)
            self.assertIn("Counterspell", report_csv_text)
