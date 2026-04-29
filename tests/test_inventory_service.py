"""Service-level workflow tests for inventory maintenance and reporting."""

from __future__ import annotations

from decimal import Decimal
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.errors import ConflictError, NotFoundError, ValidationError
from mtg_source_stack.inventory.normalize import MERGED_ACQUISITION_NOTE_MARKER
from mtg_source_stack.inventory.response_models import (
    AddCardResult,
    BulkInventoryItemMutationResult,
    InventoryDuplicateResult,
    InventoryTransferResult,
    MergeRowsResult,
    RemoveCardResult,
    OwnedInventoryPageResult,
    SetAcquisitionResult,
    SetConditionResult,
    SetFinishResult,
    SetLocationResult,
    SetNotesResult,
    SetPrintingResult,
    SetQuantityResult,
    SetTagsResult,
    SplitRowResult,
    serialize_response,
)
from mtg_source_stack.inventory.service import (
    add_card,
    bulk_mutate_inventory_items,
    create_inventory,
    create_inventory_share_link,
    duplicate_inventory,
    export_inventory_csv,
    get_inventory_share_link_status,
    get_public_inventory_share,
    inventory_health,
    inventory_report,
    list_card_printings_for_oracle,
    list_inventory_audit_events,
    list_inventory_memberships,
    list_inventories,
    list_owned_filtered,
    list_owned_filtered_page,
    list_price_gaps,
    merge_rows,
    reconcile_prices,
    remove_card,
    render_inventory_csv_export,
    resolve_card_row,
    revoke_inventory_share_link,
    rotate_inventory_share_link,
    search_card_names,
    search_cards,
    set_acquisition,
    set_condition,
    set_finish,
    set_location,
    set_notes,
    set_printing,
    set_quantity,
    set_tags,
    split_row,
    summarize_card_printings_for_oracle,
    transfer_inventory_items,
    valuation_filtered,
)
from tests.common import RepoSmokeTestCase, materialize_fixture_bundle


TEST_SHARE_TOKEN_SECRET = "test-share-token-secret"


class InventoryServiceTest(RepoSmokeTestCase):
    def _insert_test_card(
        self,
        db_path: Path,
        *,
        scryfall_id: str = "race-card-1",
        oracle_id: str = "race-oracle-1",
        name: str = "Race Test Card",
        set_code: str = "tst",
        set_name: str = "Test Set",
        collector_number: str = "1",
        finishes_json: str = '["normal"]',
    ) -> None:
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
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (scryfall_id, oracle_id, name, set_code, set_name, collector_number, finishes_json),
            )
            connection.commit()

    def _insert_catalog_card(
        self,
        db_path: Path,
        *,
        scryfall_id: str,
        oracle_id: str,
        name: str,
        set_code: str = "tst",
        set_name: str = "Test Set",
        collector_number: str = "1",
        lang: str = "en",
        released_at: str = "2026-04-01",
        finishes_json: str = '["nonfoil","foil"]',
        image_uris_json: str | None = None,
        layout: str = "normal",
        set_type: str | None = None,
        booster: int = 0,
        promo_types_json: str = "[]",
        edhrec_rank: int | None = None,
        is_default_add_searchable: int = 1,
    ) -> None:
        if image_uris_json is None:
            image_uris_json = (
                '{"small":"https://example.test/cards/'
                f'{scryfall_id}'
                '-small.jpg","normal":"https://example.test/cards/'
                f'{scryfall_id}'
                '-normal.jpg"}'
            )

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
                    released_at,
                    finishes_json,
                    image_uris_json,
                    layout,
                    set_type,
                    booster,
                    promo_types_json,
                    edhrec_rank,
                    is_default_add_searchable
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scryfall_id,
                    oracle_id,
                    name,
                    set_code,
                    set_name,
                    collector_number,
                    lang,
                    released_at,
                    finishes_json,
                    image_uris_json,
                    layout,
                    set_type,
                    booster,
                    promo_types_json,
                    edhrec_rank,
                    is_default_add_searchable,
                ),
            )
            connection.commit()

    def _insert_inventory_item(
        self,
        db_path: Path,
        *,
        inventory_slug: str,
        scryfall_id: str,
        quantity: int = 1,
        condition_code: str = "NM",
        finish: str = "normal",
        language_code: str = "en",
        location: str = "",
        acquisition_price: str | None = None,
        acquisition_currency: str | None = None,
        notes: str | None = None,
        tags_json: str = "[]",
        printing_selection_mode: str = "explicit",
    ) -> None:
        with connect(db_path) as connection:
            inventory = connection.execute(
                "SELECT id FROM inventories WHERE slug = ?",
                (inventory_slug,),
            ).fetchone()
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
                    acquisition_price,
                    acquisition_currency,
                    notes,
                    tags_json,
                    printing_selection_mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    inventory["id"],
                    scryfall_id,
                    quantity,
                    condition_code,
                    finish,
                    language_code,
                    location,
                    acquisition_price,
                    acquisition_currency,
                    notes,
                    tags_json,
                    printing_selection_mode,
                ),
            )
            connection.commit()

    def _insert_price_snapshot(
        self,
        db_path: Path,
        *,
        scryfall_id: str,
        provider: str = "tcgplayer",
        price_kind: str = "retail",
        finish: str,
        currency: str = "USD",
        snapshot_date: str,
        price_value: float,
        source_name: str = "test",
    ) -> None:
        with connect(db_path) as connection:
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scryfall_id,
                    provider,
                    price_kind,
                    finish,
                    currency,
                    snapshot_date,
                    price_value,
                    source_name,
                ),
            )
            connection.commit()

    def test_list_owned_filtered_page_counts_filters_and_paginates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            for scryfall_id, oracle_id, name, collector_number in [
                ("page-alpha", "page-oracle-alpha", "Alpha Bolt", "1"),
                ("page-beta", "page-oracle-beta", "Beta Bolt", "2"),
                ("page-gamma", "page-oracle-gamma", "Gamma Bolt", "3"),
                ("page-side", "page-oracle-side", "Side Card", "4"),
            ]:
                self._insert_test_card(
                    db_path,
                    scryfall_id=scryfall_id,
                    oracle_id=oracle_id,
                    name=name,
                    collector_number=collector_number,
                    finishes_json='["normal","foil"]',
                )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            for scryfall_id, quantity, finish, condition_code, location, tags_json in [
                ("page-alpha", 5, "normal", "NM", "Binder A", '["deck","trade"]'),
                ("page-beta", 2, "foil", "LP", "Binder B", '["deck"]'),
                ("page-gamma", 1, "normal", "HP", "Binder C", '["deck"]'),
                ("page-side", 9, "normal", "NM", "Box", '["deck"]'),
            ]:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id=scryfall_id,
                    quantity=quantity,
                    finish=finish,
                    condition_code=condition_code,
                    location=location,
                    tags_json=tags_json,
                )

            first_page = list_owned_filtered_page(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=2,
                offset=0,
                sort_key="name",
                sort_direction="asc",
                query="Bolt",
                location="Binder",
                tags=["deck"],
            )

            self.assertIsInstance(first_page, OwnedInventoryPageResult)
            self.assertEqual("personal", first_page.inventory)
            self.assertEqual(3, first_page.total_count)
            self.assertEqual(2, first_page.limit)
            self.assertEqual(0, first_page.offset)
            self.assertTrue(first_page.has_more)
            self.assertEqual("name", first_page.sort_key)
            self.assertEqual("asc", first_page.sort_direction)
            self.assertEqual(["Alpha Bolt", "Beta Bolt"], [item.name for item in first_page.items])

            second_page = list_owned_filtered_page(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=2,
                offset=2,
                sort_key="name",
                sort_direction="asc",
                query="Bolt",
                location="Binder",
                tags=["deck"],
            )
            self.assertEqual(3, second_page.total_count)
            self.assertFalse(second_page.has_more)
            self.assertEqual(["Gamma Bolt"], [item.name for item in second_page.items])

    def test_list_owned_filtered_page_sorts_deterministically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            for scryfall_id, oracle_id, name, collector_number in [
                ("sort-alpha", "sort-oracle-alpha", "Alpha Sort", "1"),
                ("sort-beta", "sort-oracle-beta", "Beta Sort", "2"),
                ("sort-gamma", "sort-oracle-gamma", "Gamma Sort", "3"),
            ]:
                self._insert_test_card(
                    db_path,
                    scryfall_id=scryfall_id,
                    oracle_id=oracle_id,
                    name=name,
                    collector_number=collector_number,
                )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            for scryfall_id, quantity in [
                ("sort-alpha", 5),
                ("sort-beta", 5),
                ("sort-gamma", 2),
            ]:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id=scryfall_id,
                    quantity=quantity,
                )

            page = list_owned_filtered_page(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                limit=10,
                offset=0,
                sort_key="quantity",
                sort_direction="desc",
            )

            self.assertEqual("quantity", page.sort_key)
            self.assertEqual("desc", page.sort_direction)
            self.assertEqual(
                [("Alpha Sort", 5), ("Beta Sort", 5), ("Gamma Sort", 2)],
                [(item.name, item.quantity) for item in page.items],
            )

    def test_list_owned_filtered_page_rejects_invalid_paging_and_sort_values(self) -> None:
        with self.assertRaisesRegex(ValidationError, "--limit must be a positive integer"):
            list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                limit=0,
            )
        with self.assertRaisesRegex(ValidationError, "--offset must be zero or a positive integer"):
            list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                offset=-1,
            )
        with self.assertRaisesRegex(ValidationError, "sort_key must be one of"):
            list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                sort_key="unsafe_sql",
            )
        with self.assertRaisesRegex(ValidationError, "sort_direction must be one of"):
            list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                sort_direction="sideways",
            )

    def test_resolve_card_row_prefers_latest_english_printing_for_oracle_id(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json
                    )
                    VALUES (?, 'resolve-oracle-1', 'Resolver Card', ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "resolve-en-new",
                            "mkm",
                            "Murders at Karlov Manor",
                            "11",
                            "en",
                            "2024-02-09",
                            '["nonfoil","foil"]',
                        ),
                        (
                            "resolve-ja-newer",
                            "mkm",
                            "Murders at Karlov Manor",
                            "12",
                            "ja",
                            "2024-03-01",
                            '["nonfoil","foil"]',
                        ),
                        (
                            "resolve-en-old",
                            "woe",
                            "Wilds of Eldraine",
                            "13",
                            "en",
                            "2023-09-01",
                            '["nonfoil"]',
                        ),
                    ],
                )

                resolved = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id="resolve-oracle-1",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish=None,
                )

            self.assertEqual("resolve-en-new", resolved["scryfall_id"])

    def test_resolve_card_row_for_oracle_id_respects_explicit_language_and_finish(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json
                    )
                    VALUES (?, 'resolve-oracle-2', 'Resolver Card', ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "resolve-two-en",
                            "bro",
                            "The Brothers' War",
                            "22",
                            "en",
                            "2022-11-18",
                            '["nonfoil"]',
                        ),
                        (
                            "resolve-two-ja",
                            "bro",
                            "The Brothers' War",
                            "23",
                            "ja",
                            "2022-12-01",
                            '["nonfoil","foil"]',
                        ),
                    ],
                )

                resolved_japanese = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id="resolve-oracle-2",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang="ja",
                    finish=None,
                )
                resolved_foil = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id="resolve-oracle-2",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish="foil",
                )

            self.assertEqual("resolve-two-ja", resolved_japanese["scryfall_id"])
            self.assertEqual("resolve-two-ja", resolved_foil["scryfall_id"])

    def test_resolve_card_row_for_oracle_id_falls_back_when_no_english_exists(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json
                    )
                    VALUES (?, 'resolve-oracle-3', 'Resolver Card', ?, ?, ?, ?, ?, '["nonfoil"]')
                    """,
                    [
                        (
                            "resolve-three-ja",
                            "mom",
                            "March of the Machine",
                            "31",
                            "ja",
                            "2023-04-21",
                        ),
                        (
                            "resolve-three-de",
                            "mom",
                            "March of the Machine",
                            "32",
                            "de",
                            "2023-03-21",
                        ),
                    ],
                )

                resolved = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id="resolve-oracle-3",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish=None,
                )

            self.assertEqual("resolve-three-ja", resolved["scryfall_id"])

    def test_resolve_card_row_for_oracle_id_prefers_mainstream_english_over_newer_promo_and_newer_non_english(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="resolve-policy-mainstream-en",
                oracle_id="resolve-policy-oracle",
                name="Resolver Policy Card",
                set_code="bro",
                set_name="The Brothers' War",
                collector_number="101",
                lang="en",
                released_at="2023-11-18",
                finishes_json='["nonfoil"]',
                set_type="expansion",
                booster=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="resolve-policy-mainstream-ja",
                oracle_id="resolve-policy-oracle",
                name="Resolver Policy Card",
                set_code="mkm",
                set_name="Murders at Karlov Manor",
                collector_number="102",
                lang="ja",
                released_at="2024-02-09",
                finishes_json='["nonfoil"]',
                set_type="expansion",
                booster=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="resolve-policy-promo-en",
                oracle_id="resolve-policy-oracle",
                name="Resolver Policy Card",
                set_code="pneo",
                set_name="Kamigawa: Neon Dynasty Promos",
                collector_number="103",
                lang="en",
                released_at="2024-03-01",
                finishes_json='["nonfoil"]',
                set_type="expansion",
                booster=0,
                promo_types_json='["promo_pack"]',
            )

            with connect(db_path) as connection:
                resolved = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id="resolve-policy-oracle",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish=None,
                )

            self.assertEqual("resolve-policy-mainstream-en", resolved["scryfall_id"])

    def test_resolve_card_row_for_oracle_id_uses_default_add_scope_before_ranking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="resolve-scope-mainstream-ja",
                oracle_id="resolve-scope-oracle",
                name="Resolver Scope Card",
                set_code="mkm",
                set_name="Murders at Karlov Manor",
                collector_number="111",
                lang="ja",
                released_at="2024-02-09",
                finishes_json='["nonfoil"]',
                set_type="expansion",
                booster=1,
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="resolve-scope-token-en",
                oracle_id="resolve-scope-oracle",
                name="Resolver Scope Card",
                set_code="tmkm",
                set_name="Murders at Karlov Manor Tokens",
                collector_number="112",
                lang="en",
                released_at="2024-03-01",
                finishes_json='["nonfoil"]',
                layout="token",
                set_type="token",
                booster=0,
                is_default_add_searchable=0,
            )

            with connect(db_path) as connection:
                resolved = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id="resolve-scope-oracle",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish=None,
                )

            self.assertEqual("resolve-scope-mainstream-ja", resolved["scryfall_id"])

    def test_resolve_card_row_can_use_finish_to_break_name_ties(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json
                    )
                    VALUES (?, ?, 'Resolver Tie Card', ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "resolve-tie-normal",
                            "resolve-tie-oracle-1",
                            "neo",
                            "Kamigawa: Neon Dynasty",
                            "41",
                            "en",
                            "2022-02-18",
                            '["nonfoil"]',
                        ),
                        (
                            "resolve-tie-foil",
                            "resolve-tie-oracle-2",
                            "bro",
                            "The Brothers' War",
                            "42",
                            "en",
                            "2022-11-18",
                            '["foil"]',
                        ),
                    ],
                )

                resolved = resolve_card_row(
                    connection,
                    scryfall_id=None,
                    oracle_id=None,
                    tcgplayer_product_id=None,
                    name="Resolver Tie Card",
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    finish="foil",
                )

                with self.assertRaisesRegex(
                    ValidationError,
                    "No printing found for oracle_id 'resolve-tie-oracle-2' with finish 'etched'.",
                ):
                    resolve_card_row(
                        connection,
                        scryfall_id=None,
                        oracle_id="resolve-tie-oracle-2",
                        tcgplayer_product_id=None,
                        name=None,
                        set_code=None,
                        collector_number=None,
                        lang=None,
                        finish="etched",
                    )

            self.assertEqual("resolve-tie-foil", resolved["scryfall_id"])

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

    def test_add_card_can_resolve_oracle_id_and_inherit_printing_language(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json
                    )
                    VALUES (?, 'add-oracle-1', 'Oracle Add Card', ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            "add-oracle-ja",
                            "neo",
                            "Kamigawa: Neon Dynasty",
                            "51",
                            "ja",
                            "2024-02-01",
                            '["foil"]',
                        ),
                        (
                            "add-oracle-en",
                            "neo",
                            "Kamigawa: Neon Dynasty",
                            "52",
                            "en",
                            "2024-01-01",
                            '["nonfoil","foil"]',
                        ),
                    ],
                )
                connection.commit()

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id=None,
                oracle_id="add-oracle-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang="ja",
                quantity=1,
                condition_code="NM",
                finish="foil",
                language_code=None,
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )

            self.assertEqual("add-oracle-ja", added.scryfall_id)
            self.assertEqual("ja", added.language_code)
            self.assertEqual("explicit", added.printing_selection_mode)

    def test_add_card_with_oracle_id_prefers_mainstream_default_printing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="add-policy-mainstream-en",
                oracle_id="add-policy-oracle",
                name="Oracle Policy Add Card",
                set_code="bro",
                set_name="The Brothers' War",
                collector_number="121",
                lang="en",
                released_at="2023-11-18",
                finishes_json='["nonfoil","foil"]',
                set_type="expansion",
                booster=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="add-policy-mainstream-ja",
                oracle_id="add-policy-oracle",
                name="Oracle Policy Add Card",
                set_code="mkm",
                set_name="Murders at Karlov Manor",
                collector_number="122",
                lang="ja",
                released_at="2024-02-09",
                finishes_json='["nonfoil","foil"]',
                set_type="expansion",
                booster=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="add-policy-promo-en",
                oracle_id="add-policy-oracle",
                name="Oracle Policy Add Card",
                set_code="pneo",
                set_name="Kamigawa: Neon Dynasty Promos",
                collector_number="123",
                lang="en",
                released_at="2024-03-01",
                finishes_json='["nonfoil","foil"]',
                set_type="expansion",
                booster=0,
                promo_types_json='["promo_pack"]',
            )

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id=None,
                oracle_id="add-policy-oracle",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code=None,
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )

            self.assertEqual("add-policy-mainstream-en", added.scryfall_id)
            self.assertEqual("en", added.language_code)
            self.assertEqual("defaulted", added.printing_selection_mode)

    def test_add_card_promotes_defaulted_row_to_explicit_when_readded_by_printing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="promotion-mainstream-en",
                oracle_id="promotion-oracle",
                name="Promotion Policy Card",
                set_code="bro",
                set_name="The Brothers' War",
                collector_number="141",
                lang="en",
                released_at="2023-11-18",
                finishes_json='["nonfoil","foil"]',
                set_type="expansion",
                booster=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="promotion-promo-en",
                oracle_id="promotion-oracle",
                name="Promotion Policy Card",
                set_code="pneo",
                set_name="Kamigawa: Neon Dynasty Promos",
                collector_number="142",
                lang="en",
                released_at="2024-03-01",
                finishes_json='["nonfoil","foil"]',
                set_type="expansion",
                booster=0,
                promo_types_json='["promo_pack"]',
            )

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            defaulted = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id=None,
                oracle_id="promotion-oracle",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code=None,
                location="Binder A",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )
            self.assertEqual("defaulted", defaulted.printing_selection_mode)

            explicit = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="promotion-mainstream-en",
                oracle_id=None,
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

            self.assertEqual(defaulted.item_id, explicit.item_id)
            self.assertEqual(2, explicit.quantity)
            self.assertEqual("explicit", explicit.printing_selection_mode)

            with connect(db_path) as connection:
                row = connection.execute(
                    "SELECT quantity, printing_selection_mode FROM inventory_items WHERE id = ?",
                    (explicit.item_id,),
                ).fetchone()

            self.assertEqual(2, row["quantity"])
            self.assertEqual("explicit", row["printing_selection_mode"])

    def test_add_card_with_oracle_id_rejects_default_normal_when_only_foil_candidates_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="add-foil-only",
                oracle_id="add-foil-only-oracle",
                name="Oracle Foil Only Card",
                set_code="neo",
                set_name="Kamigawa: Neon Dynasty",
                collector_number="131",
                lang="en",
                released_at="2024-02-01",
                finishes_json='["foil"]',
                set_type="expansion",
                booster=1,
            )

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            with self.assertRaisesRegex(
                ValidationError,
                "No printing found for oracle_id 'add-foil-only-oracle' with finish 'normal'.",
            ):
                add_card(
                    db_path,
                    inventory_slug="personal",
                    inventory_display_name=None,
                    scryfall_id=None,
                    oracle_id="add-foil-only-oracle",
                    tcgplayer_product_id=None,
                    name=None,
                    set_code=None,
                    collector_number=None,
                    lang=None,
                    quantity=1,
                    condition_code="NM",
                    finish="normal",
                    language_code=None,
                    location="Binder A",
                    acquisition_price=None,
                    acquisition_currency=None,
                    notes=None,
                    tags=None,
                )

    def test_add_card_rejects_explicit_language_code_that_conflicts_with_resolved_printing(self) -> None:
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
                        released_at,
                        finishes_json
                    )
                    VALUES (
                        'conflict-language-ja',
                        'conflict-language-oracle',
                        'Language Conflict Card',
                        'neo',
                        'Kamigawa: Neon Dynasty',
                        '61',
                        'ja',
                        '2024-02-01',
                        '["foil"]'
                    )
                    """
                )
                connection.commit()

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            with self.assertRaisesRegex(
                ValidationError,
                "language_code must match the resolved printing language. Printing language: ja; requested language_code: en.",
            ):
                add_card(
                    db_path,
                    inventory_slug="personal",
                    inventory_display_name=None,
                    scryfall_id=None,
                    oracle_id="conflict-language-oracle",
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

    def test_search_cards_rejects_blank_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            with self.assertRaisesRegex(ValidationError, "query is required"):
                search_cards(db_path, query="", exact=False, limit=10)

            with self.assertRaisesRegex(ValidationError, "query is required"):
                search_cards(db_path, query="   ", exact=False, limit=10)

    def test_search_cards_filters_to_default_add_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            for scryfall_id, layout, allowed in (
                ("scope-augment", "augment", 1),
                ("scope-host", "host", 1),
                ("scope-reversible", "reversible_card", 1),
                ("scope-token", "token", 0),
                ("scope-emblem", "emblem", 0),
                ("scope-art", "art_series", 0),
            ):
                self._insert_catalog_card(
                    db_path,
                    scryfall_id=scryfall_id,
                    oracle_id=f"{scryfall_id}-oracle",
                    name=f"Scope Probe {layout}",
                    collector_number=scryfall_id,
                    layout=layout,
                    is_default_add_searchable=allowed,
                )

            rows = search_cards(db_path, query="Scope Probe", exact=False, limit=20)

            self.assertEqual(
                ["scope-augment", "scope-host", "scope-reversible"],
                [row.scryfall_id for row in rows],
            )

    def test_search_cards_scope_all_includes_auxiliary_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            for scryfall_id, layout, allowed in (
                ("scope-augment", "augment", 1),
                ("scope-host", "host", 1),
                ("scope-reversible", "reversible_card", 1),
                ("scope-token", "token", 0),
                ("scope-emblem", "emblem", 0),
                ("scope-art", "art_series", 0),
            ):
                self._insert_catalog_card(
                    db_path,
                    scryfall_id=scryfall_id,
                    oracle_id=f"{scryfall_id}-oracle",
                    name=f"Scope Probe {layout}",
                    collector_number=scryfall_id,
                    layout=layout,
                    is_default_add_searchable=allowed,
                )

            rows = search_cards(db_path, query="Scope Probe", exact=False, limit=20, scope="all")

            self.assertCountEqual(
                [
                    "scope-augment",
                    "scope-art",
                    "scope-emblem",
                    "scope-host",
                    "scope-reversible",
                    "scope-token",
                ],
                [row.scryfall_id for row in rows],
            )

    def test_search_card_names_groups_by_oracle_id_and_surfaces_languages(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json,
                        image_uris_json
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, '["nonfoil","foil"]', ?)
                    """,
                    [
                        (
                            "grouped-search-en",
                            "grouped-search-oracle",
                            "Search Group Card",
                            "neo",
                            "Neon Dynasty",
                            "15",
                            "en",
                            "2024-01-01",
                            '{"small":"https://example.test/cards/grouped-search-en-small.jpg","normal":"https://example.test/cards/grouped-search-en-normal.jpg"}',
                        ),
                        (
                            "grouped-search-ja",
                            "grouped-search-oracle",
                            "Search Group Card",
                            "neo",
                            "Neon Dynasty",
                            "16",
                            "ja",
                            "2024-02-01",
                            '{"small":"https://example.test/cards/grouped-search-ja-small.jpg","normal":"https://example.test/cards/grouped-search-ja-normal.jpg"}',
                        ),
                        (
                            "grouped-search-de",
                            "grouped-search-oracle",
                            "Search Group Card",
                            "neo",
                            "Neon Dynasty",
                            "17",
                            "de",
                            "2023-12-01",
                            '{"small":"https://example.test/cards/grouped-search-de-small.jpg","normal":"https://example.test/cards/grouped-search-de-normal.jpg"}',
                        ),
                    ],
                )
                connection.commit()

            result = search_card_names(db_path, query="Search Group", exact=False, limit=10)

            self.assertEqual(1, result.total_count)
            self.assertFalse(result.has_more)
            self.assertEqual(1, len(result.items))
            self.assertEqual("grouped-search-oracle", result.items[0].oracle_id)
            self.assertEqual("Search Group Card", result.items[0].name)
            self.assertEqual(3, result.items[0].printings_count)
            self.assertEqual(["en", "ja", "de"], result.items[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/grouped-search-en-small.jpg",
                result.items[0].image_uri_small,
            )
            self.assertEqual(
                "https://example.test/cards/grouped-search-en-normal.jpg",
                result.items[0].image_uri_normal,
            )

    def test_search_card_names_filters_group_counts_languages_and_representative_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="scoped-group-ja",
                oracle_id="scoped-group-oracle",
                name="Scoped Group Card",
                collector_number="21",
                lang="ja",
                released_at="2026-04-01",
                image_uris_json='{"small":"https://example.test/cards/scoped-group-ja-small.jpg","normal":"https://example.test/cards/scoped-group-ja-normal.jpg"}',
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="scoped-group-en-excluded",
                oracle_id="scoped-group-oracle",
                name="Scoped Group Card",
                collector_number="22",
                lang="en",
                released_at="2026-05-01",
                image_uris_json='{"small":"https://example.test/cards/scoped-group-en-small.jpg","normal":"https://example.test/cards/scoped-group-en-normal.jpg"}',
                is_default_add_searchable=0,
            )

            result = search_card_names(db_path, query="Scoped Group", exact=False, limit=10)

            self.assertEqual(1, result.total_count)
            self.assertFalse(result.has_more)
            self.assertEqual(1, len(result.items))
            self.assertEqual("scoped-group-oracle", result.items[0].oracle_id)
            self.assertEqual("Scoped Group Card", result.items[0].name)
            self.assertEqual(1, result.items[0].printings_count)
            self.assertEqual(["ja"], result.items[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/scoped-group-ja-small.jpg",
                result.items[0].image_uri_small,
            )
            self.assertEqual(
                "https://example.test/cards/scoped-group-ja-normal.jpg",
                result.items[0].image_uri_normal,
            )

    def test_search_card_names_exact_query_returns_grouped_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="exact-group-en",
                oracle_id="exact-group-oracle",
                name="Exact Group Card",
                collector_number="31",
                lang="en",
                released_at="2026-04-01",
                image_uris_json='{"small":"https://example.test/cards/exact-group-en-small.jpg","normal":"https://example.test/cards/exact-group-en-normal.jpg"}',
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="exact-group-ja",
                oracle_id="exact-group-oracle",
                name="Exact Group Card",
                collector_number="32",
                lang="ja",
                released_at="2026-05-01",
                image_uris_json='{"small":"https://example.test/cards/exact-group-ja-small.jpg","normal":"https://example.test/cards/exact-group-ja-normal.jpg"}',
                is_default_add_searchable=1,
            )

            result = search_card_names(db_path, query="Exact Group Card", exact=True, limit=10)

            self.assertEqual(1, result.total_count)
            self.assertFalse(result.has_more)
            self.assertEqual(1, len(result.items))
            self.assertEqual("exact-group-oracle", result.items[0].oracle_id)
            self.assertEqual("Exact Group Card", result.items[0].name)
            self.assertEqual(2, result.items[0].printings_count)
            self.assertEqual(["en", "ja"], result.items[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/exact-group-en-small.jpg",
                result.items[0].image_uri_small,
            )

    def test_search_card_names_substring_query_falls_back_to_like_matching_for_long_single_token_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="substring-group-en",
                oracle_id="substring-group-oracle",
                name="Lightning Bolt",
                collector_number="41",
                lang="en",
                released_at="2026-04-01",
                is_default_add_searchable=1,
            )

            result = search_card_names(db_path, query="ightn", exact=False, limit=10)

            self.assertEqual(1, result.total_count)
            self.assertFalse(result.has_more)
            self.assertEqual(1, len(result.items))
            self.assertEqual("substring-group-oracle", result.items[0].oracle_id)
            self.assertEqual("Lightning Bolt", result.items[0].name)

    def test_search_card_names_short_substring_query_does_not_fall_back_to_like_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="substring-short-en",
                oracle_id="substring-short-oracle",
                name="Lightning Bolt",
                collector_number="41",
                lang="en",
                released_at="2026-04-01",
                is_default_add_searchable=1,
            )

            result = search_card_names(db_path, query="ning", exact=False, limit=10)

            self.assertEqual(0, result.total_count)
            self.assertFalse(result.has_more)
            self.assertEqual([], result.items)

    def test_search_card_names_substring_fallback_respects_requested_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            for index in range(12):
                self._insert_catalog_card(
                    db_path,
                    scryfall_id=f"substring-limit-{index}",
                    oracle_id=f"substring-limit-oracle-{index}",
                    name=f"AlphaXYZBeta Card {index}",
                    collector_number=str(80 + index),
                    is_default_add_searchable=1,
                )

            result = search_card_names(db_path, query="haxyzbe", exact=False, limit=11)

            self.assertEqual(12, result.total_count)
            self.assertTrue(result.has_more)
            self.assertEqual(11, len(result.items))

    def test_search_card_names_does_not_broaden_to_infix_matches_when_fts_already_found_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="bolt-token-match",
                oracle_id="bolt-token-oracle",
                name="Lightning Bolt",
                collector_number="42",
                lang="en",
                released_at="2026-04-01",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="bolt-infix-only",
                oracle_id="bolt-infix-oracle",
                name="Thunderbolt",
                collector_number="43",
                lang="en",
                released_at="2026-04-02",
                is_default_add_searchable=1,
            )

            result = search_card_names(db_path, query="bolt", exact=False, limit=10)

            self.assertEqual(1, result.total_count)
            self.assertFalse(result.has_more)
            self.assertEqual(1, len(result.items))
            self.assertEqual("bolt-token-oracle", result.items[0].oracle_id)
            self.assertEqual("Lightning Bolt", result.items[0].name)

    def test_search_card_names_prefers_popular_prefix_matches_within_lexical_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="lightning-angel",
                oracle_id="lightning-angel-oracle",
                name="Lightning Angel",
                collector_number="51",
                edhrec_rank=5000,
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="lightning-bolt",
                oracle_id="lightning-bolt-oracle",
                name="Lightning Bolt",
                collector_number="52",
                edhrec_rank=100,
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="lightning-cloud",
                oracle_id="lightning-cloud-oracle",
                name="Lightning Cloud",
                collector_number="53",
                edhrec_rank=None,
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="thunder-lightning",
                oracle_id="thunder-lightning-oracle",
                name="Thunder Lightning",
                collector_number="54",
                edhrec_rank=1,
                is_default_add_searchable=1,
            )

            result = search_card_names(db_path, query="lightn", exact=False, limit=10)

            self.assertEqual(
                [
                    "Lightning Bolt",
                    "Lightning Angel",
                    "Lightning Cloud",
                    "Thunder Lightning",
                ],
                [row.name for row in result.items],
            )
            self.assertEqual(4, result.total_count)
            self.assertFalse(result.has_more)

    def test_search_card_names_prefers_exact_leading_name_boundary_before_popularity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="cloud-key",
                oracle_id="cloud-key-oracle",
                name="Cloud Key",
                collector_number="61",
                edhrec_rank=657,
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="cloud-midgar-mercenary",
                oracle_id="cloud-midgar-mercenary-oracle",
                name="Cloud, Midgar Mercenary",
                collector_number="62",
                edhrec_rank=2010,
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="cloud-manta",
                oracle_id="cloud-manta-oracle",
                name="Cloud Manta",
                collector_number="63",
                edhrec_rank=100,
                is_default_add_searchable=1,
            )

            result = search_card_names(db_path, query="cloud", exact=False, limit=10)

            self.assertEqual(
                [
                    "Cloud, Midgar Mercenary",
                    "Cloud Manta",
                    "Cloud Key",
                ],
                [row.name for row in result.items],
            )
            self.assertEqual(3, result.total_count)
            self.assertFalse(result.has_more)

    def test_search_card_names_scope_all_includes_auxiliary_group_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="scoped-group-ja",
                oracle_id="scoped-group-oracle",
                name="Scoped Group Card",
                collector_number="21",
                lang="ja",
                released_at="2026-04-01",
                image_uris_json='{"small":"https://example.test/cards/scoped-group-ja-small.jpg","normal":"https://example.test/cards/scoped-group-ja-normal.jpg"}',
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="scoped-group-en-excluded",
                oracle_id="scoped-group-oracle",
                name="Scoped Group Card",
                collector_number="22",
                lang="en",
                released_at="2026-05-01",
                image_uris_json='{"small":"https://example.test/cards/scoped-group-en-small.jpg","normal":"https://example.test/cards/scoped-group-en-normal.jpg"}',
                is_default_add_searchable=0,
            )

            result = search_card_names(db_path, query="Scoped Group", exact=False, limit=10, scope="all")

            self.assertEqual(1, result.total_count)
            self.assertFalse(result.has_more)
            self.assertEqual(1, len(result.items))
            self.assertEqual("scoped-group-oracle", result.items[0].oracle_id)
            self.assertEqual(2, result.items[0].printings_count)
            self.assertEqual(["en", "ja"], result.items[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/scoped-group-en-small.jpg",
                result.items[0].image_uri_small,
            )
            self.assertEqual(
                "https://example.test/cards/scoped-group-en-normal.jpg",
                result.items[0].image_uri_normal,
            )

    def test_search_card_names_reports_total_count_and_has_more_when_results_exceed_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            for index in range(3):
                self._insert_catalog_card(
                    db_path,
                    scryfall_id=f"total-search-{index}",
                    oracle_id=f"total-search-oracle-{index}",
                    name=f"Cloud Card {index}",
                    collector_number=str(60 + index),
                    is_default_add_searchable=1,
                )

            result = search_card_names(db_path, query="Cloud Card", exact=False, limit=2)

            self.assertEqual(3, result.total_count)
            self.assertTrue(result.has_more)
            self.assertEqual(2, len(result.items))
            self.assertEqual(
                ["Cloud Card 0", "Cloud Card 1"],
                [row.name for row in result.items],
            )

    def test_list_card_printings_for_oracle_defaults_to_english_but_supports_language_expansion(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json,
                        image_uris_json
                    )
                    VALUES (?, 'lookup-oracle', ?, ?, ?, ?, ?, ?, '["nonfoil","foil"]', ?)
                    """,
                    [
                        (
                            "lookup-en-new",
                            "Lookup Card",
                            "mkm",
                            "Murders at Karlov Manor",
                            "41",
                            "en",
                            "2024-02-09",
                            '{"small":"https://example.test/cards/lookup-en-new-small.jpg","normal":"https://example.test/cards/lookup-en-new-normal.jpg"}',
                        ),
                        (
                            "lookup-ja",
                            "Lookup Card",
                            "mkm",
                            "Murders at Karlov Manor",
                            "42",
                            "ja",
                            "2024-03-01",
                            '{"small":"https://example.test/cards/lookup-ja-small.jpg","normal":"https://example.test/cards/lookup-ja-normal.jpg"}',
                        ),
                        (
                            "lookup-en-old",
                            "Lookup Card",
                            "woe",
                            "Wilds of Eldraine",
                            "12",
                            "en",
                            "2023-09-01",
                            '{"small":"https://example.test/cards/lookup-en-old-small.jpg","normal":"https://example.test/cards/lookup-en-old-normal.jpg"}',
                        ),
                    ],
                )
                connection.commit()

            default_rows = list_card_printings_for_oracle(db_path, "lookup-oracle")
            self.assertEqual(["lookup-en-new", "lookup-en-old"], [row.scryfall_id for row in default_rows])
            self.assertEqual([True, False], [row.is_default_add_choice for row in default_rows])

            all_rows = list_card_printings_for_oracle(db_path, "lookup-oracle", lang="all")
            self.assertEqual(["lookup-en-new", "lookup-en-old", "lookup-ja"], [row.scryfall_id for row in all_rows])
            self.assertEqual([True, False, False], [row.is_default_add_choice for row in all_rows])

            japanese_rows = list_card_printings_for_oracle(db_path, "lookup-oracle", lang="ja")
            self.assertEqual(["lookup-ja"], [row.scryfall_id for row in japanese_rows])
            self.assertEqual([True], [row.is_default_add_choice for row in japanese_rows])

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
                        released_at,
                        finishes_json,
                        image_uris_json
                    )
                    VALUES (?, 'lookup-no-english', 'Foreign Only Card', 'fdn', 'Foundations', ?, ?, ?, '["nonfoil"]', ?)
                    """,
                    [
                        (
                            "lookup-no-english-ja",
                            "77",
                            "ja",
                            "2024-01-01",
                            '{"small":"https://example.test/cards/lookup-no-english-ja-small.jpg","normal":"https://example.test/cards/lookup-no-english-ja-normal.jpg"}',
                        ),
                        (
                            "lookup-no-english-de",
                            "78",
                            "de",
                            "2023-12-01",
                            '{"small":"https://example.test/cards/lookup-no-english-de-small.jpg","normal":"https://example.test/cards/lookup-no-english-de-normal.jpg"}',
                        ),
                    ],
                )
                connection.commit()

            fallback_rows = list_card_printings_for_oracle(db_path, "lookup-no-english")
            self.assertEqual(
                ["lookup-no-english-ja", "lookup-no-english-de"],
                [row.scryfall_id for row in fallback_rows],
            )
            self.assertEqual([True, False], [row.is_default_add_choice for row in fallback_rows])

            with self.assertRaisesRegex(NotFoundError, "No printings found for oracle_id 'missing-oracle'"):
                list_card_printings_for_oracle(db_path, "missing-oracle")

    def test_summarize_card_printings_for_oracle_returns_quick_add_metadata(self) -> None:
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
                        lang,
                        released_at,
                        finishes_json,
                        image_uris_json
                    )
                    VALUES (?, 'summary-oracle', ?, ?, ?, ?, ?, ?, '["nonfoil","foil"]', ?)
                    """,
                    [
                        (
                            "summary-en-new",
                            "Summary Card",
                            "mkm",
                            "Murders at Karlov Manor",
                            "41",
                            "en",
                            "2024-02-09",
                            '{"small":"https://example.test/cards/summary-en-new-small.jpg","normal":"https://example.test/cards/summary-en-new-normal.jpg"}',
                        ),
                        (
                            "summary-ja",
                            "Summary Card",
                            "mkm",
                            "Murders at Karlov Manor",
                            "42",
                            "ja",
                            "2024-03-01",
                            '{"small":"https://example.test/cards/summary-ja-small.jpg","normal":"https://example.test/cards/summary-ja-normal.jpg"}',
                        ),
                        (
                            "summary-en-old",
                            "Summary Card",
                            "woe",
                            "Wilds of Eldraine",
                            "12",
                            "en",
                            "2023-09-01",
                            '{"small":"https://example.test/cards/summary-en-old-small.jpg","normal":"https://example.test/cards/summary-en-old-normal.jpg"}',
                        ),
                    ],
                )
                connection.commit()

            summary = summarize_card_printings_for_oracle(db_path, "summary-oracle")

            self.assertEqual("summary-oracle", summary.oracle_id)
            self.assertIsNotNone(summary.default_printing)
            self.assertEqual("summary-en-new", summary.default_printing.scryfall_id)
            self.assertEqual(["en", "ja"], summary.available_languages)
            self.assertEqual(3, summary.printings_count)
            self.assertTrue(summary.has_more_printings)
            self.assertEqual(["summary-en-new", "summary-en-old"], [row.scryfall_id for row in summary.printings])
            self.assertEqual([True, False], [row.is_default_add_choice for row in summary.printings])

            with self.assertRaisesRegex(NotFoundError, "No printings found for oracle_id 'missing-oracle'"):
                summarize_card_printings_for_oracle(db_path, "missing-oracle")

    def test_summarize_card_printings_for_oracle_handles_foreign_only_and_missing_default_choice(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="summary-foreign-ja",
                oracle_id="summary-foreign-oracle",
                name="Foreign Summary Card",
                collector_number="77",
                lang="ja",
                released_at="2024-01-01",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="summary-foreign-de",
                oracle_id="summary-foreign-oracle",
                name="Foreign Summary Card",
                collector_number="78",
                lang="de",
                released_at="2023-12-01",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="summary-foil-only-en",
                oracle_id="summary-foil-only-oracle",
                name="Foil Only Summary Card",
                collector_number="79",
                lang="en",
                finishes_json='["foil"]',
                is_default_add_searchable=1,
            )

            foreign_summary = summarize_card_printings_for_oracle(db_path, "summary-foreign-oracle")
            self.assertEqual(["ja", "de"], [row.lang for row in foreign_summary.printings])
            self.assertEqual(["ja", "de"], foreign_summary.available_languages)
            self.assertFalse(foreign_summary.has_more_printings)
            self.assertIsNotNone(foreign_summary.default_printing)
            self.assertEqual("summary-foreign-ja", foreign_summary.default_printing.scryfall_id)

            foil_only_summary = summarize_card_printings_for_oracle(db_path, "summary-foil-only-oracle")
            self.assertIsNone(foil_only_summary.default_printing)
            self.assertEqual(["summary-foil-only-en"], [row.scryfall_id for row in foil_only_summary.printings])
            self.assertEqual([False], [row.is_default_add_choice for row in foil_only_summary.printings])

    def test_summarize_card_printings_for_oracle_respects_catalog_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="summary-scope-ja",
                oracle_id="summary-scope-oracle",
                name="Scoped Summary Card",
                collector_number="31",
                lang="ja",
                released_at="2026-04-01",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="summary-scope-en-excluded",
                oracle_id="summary-scope-oracle",
                name="Scoped Summary Card",
                collector_number="32",
                lang="en",
                released_at="2026-05-01",
                is_default_add_searchable=0,
            )

            default_summary = summarize_card_printings_for_oracle(db_path, "summary-scope-oracle")
            self.assertEqual(["summary-scope-ja"], [row.scryfall_id for row in default_summary.printings])
            self.assertEqual(["ja"], default_summary.available_languages)
            self.assertEqual(1, default_summary.printings_count)

            all_summary = summarize_card_printings_for_oracle(
                db_path,
                "summary-scope-oracle",
                scope="all",
            )
            self.assertEqual(["summary-scope-en-excluded"], [row.scryfall_id for row in all_summary.printings])
            self.assertEqual(["en", "ja"], all_summary.available_languages)
            self.assertEqual(2, all_summary.printings_count)
            self.assertTrue(all_summary.has_more_printings)

    def test_list_card_printings_for_oracle_matches_default_add_policy_and_marks_one_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-policy-mainstream-en",
                oracle_id="lookup-policy-oracle",
                name="Lookup Policy Card",
                collector_number="61",
                lang="en",
                released_at="2024-01-01",
                booster=1,
                promo_types_json="[]",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-policy-mainstream-ja",
                oracle_id="lookup-policy-oracle",
                name="Lookup Policy Card",
                collector_number="62",
                lang="ja",
                released_at="2024-03-01",
                booster=1,
                promo_types_json="[]",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-policy-promo-en",
                oracle_id="lookup-policy-oracle",
                name="Lookup Policy Card",
                collector_number="63",
                lang="en",
                released_at="2024-04-01",
                booster=0,
                promo_types_json='["promo-pack"]',
                is_default_add_searchable=1,
            )

            default_rows = list_card_printings_for_oracle(db_path, "lookup-policy-oracle")
            self.assertEqual(
                ["lookup-policy-mainstream-en", "lookup-policy-promo-en"],
                [row.scryfall_id for row in default_rows],
            )
            self.assertEqual([True, False], [row.is_default_add_choice for row in default_rows])

            all_rows = list_card_printings_for_oracle(db_path, "lookup-policy-oracle", lang="all")
            self.assertEqual(
                [
                    "lookup-policy-mainstream-en",
                    "lookup-policy-promo-en",
                    "lookup-policy-mainstream-ja",
                ],
                [row.scryfall_id for row in all_rows],
            )
            self.assertEqual([True, False, False], [row.is_default_add_choice for row in all_rows])

            resolved = resolve_card_row(
                connect(db_path),
                scryfall_id=None,
                oracle_id="lookup-policy-oracle",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                finish="normal",
            )
            self.assertEqual("lookup-policy-mainstream-en", resolved["scryfall_id"])

    def test_list_card_printings_for_oracle_has_no_default_when_normal_would_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-foil-only-en",
                oracle_id="lookup-foil-only-oracle",
                name="Lookup Foil Only Card",
                collector_number="71",
                lang="en",
                finishes_json='["foil"]',
                is_default_add_searchable=1,
            )

            rows = list_card_printings_for_oracle(db_path, "lookup-foil-only-oracle")
            self.assertEqual(["lookup-foil-only-en"], [row.scryfall_id for row in rows])
            self.assertEqual([False], [row.is_default_add_choice for row in rows])

    def test_list_card_printings_for_oracle_filters_to_default_add_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-scope-ja",
                oracle_id="lookup-scope-oracle",
                name="Scoped Lookup Card",
                collector_number="31",
                lang="ja",
                released_at="2026-04-01",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-scope-en-excluded",
                oracle_id="lookup-scope-oracle",
                name="Scoped Lookup Card",
                collector_number="32",
                lang="en",
                released_at="2026-05-01",
                is_default_add_searchable=0,
            )

            default_rows = list_card_printings_for_oracle(db_path, "lookup-scope-oracle")
            self.assertEqual(["lookup-scope-ja"], [row.scryfall_id for row in default_rows])

            all_rows = list_card_printings_for_oracle(db_path, "lookup-scope-oracle", lang="all")
            self.assertEqual(["lookup-scope-ja"], [row.scryfall_id for row in all_rows])

            english_rows = list_card_printings_for_oracle(db_path, "lookup-scope-oracle", lang="en")
            self.assertEqual([], [row.scryfall_id for row in english_rows])

    def test_list_card_printings_for_oracle_scope_all_includes_auxiliary_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-scope-ja",
                oracle_id="lookup-scope-oracle",
                name="Scoped Lookup Card",
                collector_number="31",
                lang="ja",
                released_at="2026-04-01",
                is_default_add_searchable=1,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-scope-en-excluded",
                oracle_id="lookup-scope-oracle",
                name="Scoped Lookup Card",
                collector_number="32",
                lang="en",
                released_at="2026-05-01",
                is_default_add_searchable=0,
            )

            default_rows = list_card_printings_for_oracle(db_path, "lookup-scope-oracle", scope="all")
            self.assertEqual(["lookup-scope-en-excluded"], [row.scryfall_id for row in default_rows])

            all_rows = list_card_printings_for_oracle(
                db_path,
                "lookup-scope-oracle",
                lang="all",
                scope="all",
            )
            self.assertEqual(
                ["lookup-scope-en-excluded", "lookup-scope-ja"],
                [row.scryfall_id for row in all_rows],
            )

            english_rows = list_card_printings_for_oracle(
                db_path,
                "lookup-scope-oracle",
                lang="en",
                scope="all",
            )
            self.assertEqual(["lookup-scope-en-excluded"], [row.scryfall_id for row in english_rows])

    def test_list_card_printings_for_oracle_raises_not_found_when_all_rows_are_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            self._insert_catalog_card(
                db_path,
                scryfall_id="lookup-excluded-token",
                oracle_id="lookup-excluded-oracle",
                name="Excluded Lookup Card",
                collector_number="41",
                layout="token",
                is_default_add_searchable=0,
            )

            with self.assertRaisesRegex(NotFoundError, "No printings found for oracle_id 'lookup-excluded-oracle'"):
                list_card_printings_for_oracle(db_path, "lookup-excluded-oracle")

            all_rows = list_card_printings_for_oracle(
                db_path,
                "lookup-excluded-oracle",
                scope="all",
            )
            self.assertEqual(["lookup-excluded-token"], [row.scryfall_id for row in all_rows])

    def test_create_inventory_returns_typed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            result = create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description="Main binder inventory",
                default_location=" Binder A ",
                default_tags="Burn,  Modern, burn",
                notes=" Main collection notes ",
                acquisition_price="12.50",
                acquisition_currency="usd",
            )

            self.assertEqual(1, result.inventory_id)
            self.assertEqual("personal", result.slug)
            self.assertEqual("Personal Collection", result.display_name)
            self.assertEqual("Main binder inventory", result.description)
            self.assertEqual("Binder A", result.default_location)
            self.assertEqual("burn, modern", result.default_tags)
            self.assertEqual("Main collection notes", result.notes)
            self.assertEqual(Decimal("12.50"), result.acquisition_price)
            self.assertEqual("USD", result.acquisition_currency)
            self.assertEqual(
                {
                    "inventory_id": 1,
                    "slug": "personal",
                    "display_name": "Personal Collection",
                    "description": "Main binder inventory",
                    "default_location": "Binder A",
                    "default_tags": "burn, modern",
                    "notes": "Main collection notes",
                    "acquisition_price": "12.50",
                    "acquisition_currency": "USD",
                },
                serialize_response(result),
            )

            listed = list_inventories(db_path)
            self.assertEqual(1, len(listed))
            self.assertEqual("Binder A", listed[0].default_location)
            self.assertEqual("burn, modern", listed[0].default_tags)
            self.assertEqual("Main collection notes", listed[0].notes)
            self.assertEqual(Decimal("12.50"), listed[0].acquisition_price)
            self.assertEqual("USD", listed[0].acquisition_currency)

    def test_inventory_share_links_expose_public_read_only_projection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_catalog_card(
                db_path,
                scryfall_id="share-card-1",
                oracle_id="share-oracle-1",
                name="Shared Test Card",
                finishes_json='["normal","foil"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description="Public description",
                actor_id="owner-user",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="share-card-1",
                quantity=3,
                location="Private Binder",
                acquisition_price="1.25",
                acquisition_currency="USD",
                notes="private note",
                tags_json='["private", "trade"]',
            )

            initial_status = get_inventory_share_link_status(
                db_path,
                inventory_slug="personal",
                token_secret=TEST_SHARE_TOKEN_SECRET,
            )
            self.assertFalse(initial_status.active)
            self.assertIsNone(initial_status.public_path)
            self.assertIsNone(initial_status.created_at)

            created = create_inventory_share_link(
                db_path,
                inventory_slug="personal",
                actor_id="owner-user",
                token_secret=TEST_SHARE_TOKEN_SECRET,
                actor_type="api",
                request_id="req-create-share",
            )
            self.assertTrue(created.active)
            self.assertEqual("personal", created.inventory)
            self.assertEqual(f"/shared/inventories/{created.token}", created.public_path)
            with connect(db_path) as connection:
                share_row = connection.execute(
                    """
                    SELECT token_nonce, issued_by_actor_id
                    FROM inventory_share_links
                    WHERE inventory_id = (
                        SELECT id
                        FROM inventories
                        WHERE slug = ?
                    )
                    """,
                    ("personal",),
                ).fetchone()
            self.assertIn(share_row["token_nonce"], created.token)
            self.assertNotEqual(created.token, share_row["token_nonce"])
            self.assertEqual("owner-user", share_row["issued_by_actor_id"])
            active_status = get_inventory_share_link_status(
                db_path,
                inventory_slug="personal",
                token_secret=TEST_SHARE_TOKEN_SECRET,
            )
            self.assertEqual(created.public_path, active_status.public_path)

            with self.assertRaises(ConflictError):
                create_inventory_share_link(
                    db_path,
                    inventory_slug="personal",
                    actor_id="owner-user",
                    token_secret=TEST_SHARE_TOKEN_SECRET,
                )

            public_share = get_public_inventory_share(
                db_path,
                token=created.token,
                token_secret=TEST_SHARE_TOKEN_SECRET,
            )
            with self.assertRaises(NotFoundError):
                get_public_inventory_share(
                    db_path,
                    token=created.token,
                    token_secret="different-share-token-secret",
                )
            self.assertEqual("Personal Collection", public_share.inventory.display_name)
            self.assertEqual("Public description", public_share.inventory.description)
            self.assertEqual(1, public_share.inventory.item_rows)
            self.assertEqual(3, public_share.inventory.total_cards)
            self.assertEqual(1, len(public_share.items))
            public_item = serialize_response(public_share.items[0])
            self.assertEqual("Shared Test Card", public_item["name"])
            self.assertEqual(3, public_item["quantity"])
            self.assertEqual(["normal", "foil"], public_item["allowed_finishes"])
            for private_key in (
                "item_id",
                "location",
                "tags",
                "acquisition_price",
                "acquisition_currency",
                "unit_price",
                "est_value",
                "notes",
            ):
                self.assertNotIn(private_key, public_item)

            rotated = rotate_inventory_share_link(
                db_path,
                inventory_slug="personal",
                actor_id="owner-user",
                token_secret=TEST_SHARE_TOKEN_SECRET,
                actor_type="api",
                request_id="req-rotate-share",
            )
            self.assertNotEqual(created.token, rotated.token)
            with self.assertRaises(NotFoundError):
                get_public_inventory_share(
                    db_path,
                    token=created.token,
                    token_secret=TEST_SHARE_TOKEN_SECRET,
                )
            rotated_public_share = get_public_inventory_share(
                db_path,
                token=rotated.token,
                token_secret=TEST_SHARE_TOKEN_SECRET,
            )
            self.assertEqual("Personal Collection", rotated_public_share.inventory.display_name)

            revoked = revoke_inventory_share_link(
                db_path,
                inventory_slug="personal",
                actor_id="owner-user",
                actor_type="api",
                request_id="req-revoke-share",
            )
            self.assertFalse(revoked.active)
            self.assertIsNone(revoked.public_path)
            self.assertIsNotNone(revoked.revoked_at)
            with self.assertRaises(NotFoundError):
                get_public_inventory_share(
                    db_path,
                    token=rotated.token,
                    token_secret=TEST_SHARE_TOKEN_SECRET,
                )

            revoked_again = revoke_inventory_share_link(
                db_path,
                inventory_slug="personal",
                actor_id="owner-user",
            )
            self.assertFalse(revoked_again.active)
            self.assertEqual(revoked.revoked_at, revoked_again.revoked_at)
            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual(
                ["revoke_share_link", "rotate_share_link", "create_share_link"],
                [row.action for row in audit_rows[:3]],
            )
            self.assertEqual("req-revoke-share", audit_rows[0].request_id)
            self.assertEqual("req-rotate-share", audit_rows[1].request_id)
            self.assertEqual("req-create-share", audit_rows[2].request_id)
            self.assertTrue(all("token" not in row.metadata for row in audit_rows[:3]))

    def test_inventory_share_links_group_public_rows_by_visible_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_catalog_card(
                db_path,
                scryfall_id="share-card-1",
                oracle_id="share-oracle-1",
                name="Shared Test Card",
                finishes_json='["normal","foil"]',
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description="Public description",
                actor_id="owner-user",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="share-card-1",
                quantity=2,
                finish="normal",
                location="Private Binder A",
                acquisition_price="1.25",
                acquisition_currency="USD",
                notes="private note a",
                tags_json='["private-a"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="share-card-1",
                quantity=3,
                finish="normal",
                location="Private Binder B",
                acquisition_price="2.50",
                acquisition_currency="USD",
                notes="private note b",
                tags_json='["private-b"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="share-card-1",
                quantity=1,
                finish="foil",
                location="Private Binder C",
                acquisition_price="4.00",
                acquisition_currency="USD",
                notes="private foil note",
                tags_json='["private-c"]',
            )

            created = create_inventory_share_link(
                db_path,
                inventory_slug="personal",
                actor_id="owner-user",
                token_secret=TEST_SHARE_TOKEN_SECRET,
                actor_type="api",
                request_id="req-create-share",
            )

            public_share = get_public_inventory_share(
                db_path,
                token=created.token,
                token_secret=TEST_SHARE_TOKEN_SECRET,
            )

            self.assertEqual("Personal Collection", public_share.inventory.display_name)
            self.assertEqual("Public description", public_share.inventory.description)
            self.assertEqual(2, public_share.inventory.item_rows)
            self.assertEqual(6, public_share.inventory.total_cards)
            self.assertEqual(2, len(public_share.items))

            items_by_finish = {item.finish: serialize_response(item) for item in public_share.items}
            self.assertEqual({"normal", "foil"}, set(items_by_finish))
            self.assertEqual(5, items_by_finish["normal"]["quantity"])
            self.assertEqual(1, items_by_finish["foil"]["quantity"])
            for public_item in items_by_finish.values():
                for private_key in (
                    "item_id",
                    "location",
                    "tags",
                    "acquisition_price",
                    "acquisition_currency",
                    "unit_price",
                    "est_value",
                    "notes",
                ):
                    self.assertNotIn(private_key, public_item)

    def test_add_card_uses_inventory_default_location_and_tags_when_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                default_location="Binder A",
                default_tags="Burn, Modern",
            )

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location=None,
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )

            self.assertEqual("Binder A", added.location)
            self.assertEqual(["burn", "modern"], added.tags)

    def test_add_card_merges_inventory_default_tags_with_explicit_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                default_tags="Burn, Modern",
            )

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="Deckbox",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags="Foil, burn",
            )

            self.assertEqual("Deckbox", added.location)
            self.assertEqual(["burn", "modern", "foil"], added.tags)

    def test_add_card_blank_location_and_tags_bypass_inventory_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                default_location="Binder A",
                default_tags="Burn, Modern",
            )

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="   ",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags="   ",
            )

            self.assertIsNone(added.location)
            self.assertEqual([], added.tags)

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

    def test_bulk_mutate_inventory_items_applies_tag_operations_and_writes_grouped_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, finishes_json='["normal","foil"]')
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="normal",
                location="Binder A",
                tags_json='["deck"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="foil",
                location="Binder B",
                tags_json='["foil"]',
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            add_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="add_tags",
                item_ids=item_ids,
                tags=["trade", "deck"],
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-add",
            )
            self.assertIsInstance(add_result, BulkInventoryItemMutationResult)
            self.assertEqual("add_tags", add_result.operation)
            self.assertEqual(item_ids, add_result.requested_item_ids)
            self.assertEqual(item_ids, add_result.updated_item_ids)
            self.assertEqual(2, add_result.updated_count)

            remove_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="remove_tags",
                item_ids=item_ids,
                tags=["deck"],
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-remove",
            )
            self.assertEqual("remove_tags", remove_result.operation)
            self.assertEqual(item_ids, remove_result.updated_item_ids)

            set_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_tags",
                item_ids=[item_ids[0]],
                tags=["featured"],
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-set",
            )
            self.assertEqual([item_ids[0]], set_result.updated_item_ids)
            self.assertEqual(1, set_result.updated_count)

            clear_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="clear_tags",
                item_ids=[item_ids[1]],
                tags=None,
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-clear",
            )
            self.assertEqual("clear_tags", clear_result.operation)
            self.assertEqual([item_ids[1]], clear_result.updated_item_ids)

            rows = list_owned_filtered(
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
            row_tags = {row.item_id: row.tags for row in rows}
            self.assertEqual(["featured"], row_tags[item_ids[0]])
            self.assertEqual([], row_tags[item_ids[1]])

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual("clear_tags", audit_rows[0].action)
            self.assertEqual("set_tags", audit_rows[1].action)
            self.assertEqual("remove_tags", audit_rows[2].action)
            self.assertEqual("remove_tags", audit_rows[3].action)
            self.assertEqual("add_tags", audit_rows[4].action)
            self.assertEqual("add_tags", audit_rows[5].action)
            self.assertTrue(audit_rows[0].metadata["bulk_operation"])
            self.assertEqual("clear_tags", audit_rows[0].metadata["bulk_kind"])
            self.assertEqual(1, audit_rows[0].metadata["bulk_count"])
            self.assertEqual("req-bulk-clear", audit_rows[0].request_id)

    def test_bulk_mutate_inventory_items_applies_quantity_notes_and_acquisition_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=1,
                location="Binder A",
                notes="old note",
                acquisition_price="1.25",
                acquisition_currency="USD",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=3,
                location="Binder B",
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            quantity_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_quantity",
                item_ids=item_ids,
                tags=None,
                quantity=4,
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-quantity",
            )
            self.assertEqual("set_quantity", quantity_result.operation)
            self.assertEqual(item_ids, quantity_result.updated_item_ids)
            self.assertEqual(2, quantity_result.updated_count)

            notes_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_notes",
                item_ids=item_ids,
                tags=None,
                notes="featured",
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-notes",
            )
            self.assertEqual("set_notes", notes_result.operation)
            self.assertEqual(item_ids, notes_result.updated_item_ids)

            clear_notes_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_notes",
                item_ids=[item_ids[1]],
                tags=None,
                clear_notes=True,
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-clear-notes",
            )
            self.assertEqual([item_ids[1]], clear_notes_result.updated_item_ids)

            acquisition_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_acquisition",
                item_ids=item_ids,
                tags=None,
                acquisition_price=Decimal("2.50"),
                acquisition_currency="usd",
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-acquisition",
            )
            self.assertEqual("set_acquisition", acquisition_result.operation)
            self.assertEqual(item_ids, acquisition_result.updated_item_ids)

            clear_acquisition_result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_acquisition",
                item_ids=[item_ids[0]],
                tags=None,
                clear_acquisition=True,
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-clear-acquisition",
            )
            self.assertEqual([item_ids[0]], clear_acquisition_result.updated_item_ids)

            rows = list_owned_filtered(
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
            row_by_id = {row.item_id: row for row in rows}
            self.assertEqual(4, row_by_id[item_ids[0]].quantity)
            self.assertEqual(4, row_by_id[item_ids[1]].quantity)
            self.assertEqual("featured", row_by_id[item_ids[0]].notes)
            self.assertIsNone(row_by_id[item_ids[1]].notes)
            self.assertIsNone(row_by_id[item_ids[0]].acquisition_price)
            self.assertIsNone(row_by_id[item_ids[0]].acquisition_currency)
            self.assertEqual(Decimal("2.50"), row_by_id[item_ids[1]].acquisition_price)
            self.assertEqual("USD", row_by_id[item_ids[1]].acquisition_currency)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual("set_acquisition", audit_rows[0].action)
            self.assertTrue(audit_rows[0].metadata["bulk_operation"])
            self.assertEqual("set_acquisition", audit_rows[0].metadata["bulk_kind"])
            self.assertTrue(audit_rows[0].metadata["clear"])
            self.assertEqual("req-bulk-clear-acquisition", audit_rows[0].request_id)

    def test_bulk_mutate_inventory_items_applies_finish_and_skips_noop_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, finishes_json='["normal","foil"]')
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="normal",
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="foil",
                location="Binder B",
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_finish",
                item_ids=item_ids,
                tags=None,
                finish="foil",
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-finish",
            )
            self.assertEqual("set_finish", result.operation)
            self.assertEqual([item_ids[0]], result.updated_item_ids)
            self.assertEqual(1, result.updated_count)

            rows = list_owned_filtered(
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
            row_by_id = {row.item_id: row for row in rows}
            self.assertEqual("foil", row_by_id[item_ids[0]].finish)
            self.assertEqual("foil", row_by_id[item_ids[1]].finish)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual("set_finish", audit_rows[0].action)
            self.assertEqual("normal", audit_rows[0].metadata["old_finish"])
            self.assertEqual("foil", audit_rows[0].metadata["new_finish"])
            self.assertEqual("req-bulk-finish", audit_rows[0].request_id)

    def test_bulk_mutate_inventory_items_set_finish_conflict_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, finishes_json='["normal","foil"]')
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="normal",
                location="",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="foil",
                location="",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="normal",
                location="Binder C",
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            with self.assertRaisesRegex(ConflictError, "Changing finish would collide with an existing inventory row"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_finish",
                    item_ids=[item_ids[2], item_ids[0]],
                    tags=None,
                    finish="foil",
                )

            rows = list_owned_filtered(
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
            row_by_id = {row.item_id: row for row in rows}
            self.assertEqual("normal", row_by_id[item_ids[0]].finish)
            self.assertEqual("foil", row_by_id[item_ids[1]].finish)
            self.assertEqual("normal", row_by_id[item_ids[2]].finish)

    def test_bulk_mutate_inventory_items_set_finish_rejects_unsupported_finish(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, finishes_json='["normal"]')
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="normal",
            )
            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(
                ValidationError,
                "Finish 'foil' is not available for this card printing",
            ):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_finish",
                    item_ids=[item_id],
                    tags=None,
                    finish="foil",
                )

    def test_bulk_mutate_inventory_items_applies_location_and_skips_noop_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, finishes_json='["normal","foil"]')
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="normal",
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                finish="foil",
                location="Binder B",
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_location",
                item_ids=item_ids,
                tags=None,
                location="Binder B",
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-location",
            )
            self.assertEqual("set_location", result.operation)
            self.assertEqual([item_ids[0]], result.updated_item_ids)
            self.assertEqual(1, result.updated_count)

            rows = list_owned_filtered(
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
            row_by_id = {row.item_id: row for row in rows}
            self.assertEqual("Binder B", row_by_id[item_ids[0]].location)
            self.assertEqual("Binder B", row_by_id[item_ids[1]].location)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual("set_location", audit_rows[0].action)
            self.assertEqual("Binder A", audit_rows[0].metadata["old_location"])
            self.assertEqual("Binder B", audit_rows[0].metadata["new_location"])
            self.assertEqual("req-bulk-location", audit_rows[0].request_id)

    def test_bulk_mutate_inventory_items_clear_location_normalizes_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                location="Binder A",
            )
            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_location",
                item_ids=[item_id],
                tags=None,
                clear_location=True,
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-clear-location",
            )
            self.assertEqual([item_id], result.updated_item_ids)

            rows = list_owned_filtered(
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
            self.assertIsNone(rows[0].location)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual("Binder A", audit_rows[0].metadata["old_location"])
            self.assertIsNone(audit_rows[0].metadata["new_location"])
            self.assertEqual("Binder A", audit_rows[0].before["location"])
            self.assertIsNone(audit_rows[0].after["location"])

    def test_bulk_mutate_inventory_items_set_location_conflict_rolls_back_without_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="NM",
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="NM",
                location="Binder B",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="LP",
                location="Binder C",
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            with self.assertRaisesRegex(ConflictError, "Changing location would collide with an existing inventory row"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_location",
                    item_ids=[item_ids[2], item_ids[0]],
                    tags=None,
                    location="Binder B",
                )

            rows = list_owned_filtered(
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
            row_by_id = {row.item_id: row for row in rows}
            self.assertEqual("Binder A", row_by_id[item_ids[0]].location)
            self.assertEqual("Binder B", row_by_id[item_ids[1]].location)
            self.assertEqual("Binder C", row_by_id[item_ids[2]].location)

    def test_bulk_mutate_inventory_items_set_location_merge_succeeds_and_keeps_target_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=2,
                location="Binder A",
                acquisition_price="1.25",
                acquisition_currency="USD",
                notes="source note",
                tags_json='["deck"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=3,
                location="Binder B",
                acquisition_price="2.50",
                acquisition_currency="USD",
                notes="target note",
                tags_json='["trade"]',
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_location",
                item_ids=[item_ids[0]],
                tags=None,
                location="Binder B",
                merge=True,
                keep_acquisition="target",
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-location-merge",
            )
            self.assertEqual("set_location", result.operation)
            self.assertEqual([item_ids[0]], result.updated_item_ids)
            self.assertEqual(1, result.updated_count)

            rows = list_owned_filtered(
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
            self.assertEqual(1, len(rows))
            self.assertEqual(5, rows[0].quantity)
            self.assertEqual("Binder B", rows[0].location)
            self.assertEqual(Decimal("2.50"), rows[0].acquisition_price)
            self.assertEqual("USD", rows[0].acquisition_currency)
            self.assertCountEqual(["deck", "trade"], rows[0].tags)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            location_audits = [row for row in audit_rows if row.action == "set_location"]
            self.assertEqual(2, len(location_audits))
            self.assertTrue(all(row.metadata["merged"] for row in location_audits))
            self.assertTrue(all(row.metadata["keep_acquisition"] == "target" for row in location_audits))

    def test_bulk_mutate_inventory_items_set_location_rejects_invalid_field_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
            )
            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(ValidationError, "Use either location or clear_location for set_location"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_location",
                    item_ids=[item_id],
                    tags=None,
                    location="Binder A",
                    clear_location=True,
                )

            with self.assertRaisesRegex(
                ValidationError,
                "keep_acquisition only applies when merge is true for set_location",
            ):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_location",
                    item_ids=[item_id],
                    tags=None,
                    location="Binder A",
                    keep_acquisition="target",
                )

    def test_bulk_mutate_inventory_items_applies_condition_and_skips_noop_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, finishes_json='["normal","foil"]')
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="NM",
                finish="normal",
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="LP",
                finish="foil",
                location="Binder B",
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_condition",
                item_ids=item_ids,
                tags=None,
                condition_code="LP",
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-condition",
            )
            self.assertEqual("set_condition", result.operation)
            self.assertEqual([item_ids[0]], result.updated_item_ids)
            self.assertEqual(1, result.updated_count)

            rows = list_owned_filtered(
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
            row_by_id = {row.item_id: row for row in rows}
            self.assertEqual("LP", row_by_id[item_ids[0]].condition_code)
            self.assertEqual("LP", row_by_id[item_ids[1]].condition_code)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual("set_condition", audit_rows[0].action)
            self.assertEqual("NM", audit_rows[0].metadata["old_condition_code"])
            self.assertEqual("LP", audit_rows[0].metadata["new_condition_code"])
            self.assertEqual("req-bulk-condition", audit_rows[0].request_id)

    def test_bulk_mutate_inventory_items_set_condition_conflict_rolls_back_without_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="NM",
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="LP",
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                condition_code="NM",
                location="Binder B",
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            with self.assertRaisesRegex(ConflictError, "Changing condition would collide with an existing inventory row"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_condition",
                    item_ids=[item_ids[2], item_ids[0]],
                    tags=None,
                    condition_code="LP",
                )

            rows = list_owned_filtered(
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
            row_by_id = {row.item_id: row for row in rows}
            self.assertEqual("NM", row_by_id[item_ids[0]].condition_code)
            self.assertEqual("LP", row_by_id[item_ids[1]].condition_code)
            self.assertEqual("NM", row_by_id[item_ids[2]].condition_code)

    def test_bulk_mutate_inventory_items_set_condition_merge_succeeds_and_keeps_source_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=2,
                condition_code="NM",
                location="Binder A",
                acquisition_price="1.25",
                acquisition_currency="USD",
                tags_json='["deck"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=3,
                condition_code="LP",
                location="Binder A",
                acquisition_price="2.50",
                acquisition_currency="USD",
                tags_json='["trade"]',
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            result = bulk_mutate_inventory_items(
                db_path,
                inventory_slug="personal",
                operation="set_condition",
                item_ids=[item_ids[0]],
                tags=None,
                condition_code="LP",
                merge=True,
                keep_acquisition="source",
                actor_type="api",
                actor_id="bulk-user",
                request_id="req-bulk-condition-merge",
            )
            self.assertEqual("set_condition", result.operation)
            self.assertEqual([item_ids[0]], result.updated_item_ids)
            self.assertEqual(1, result.updated_count)

            rows = list_owned_filtered(
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
            self.assertEqual(1, len(rows))
            self.assertEqual(5, rows[0].quantity)
            self.assertEqual("LP", rows[0].condition_code)
            self.assertEqual(Decimal("1.25"), rows[0].acquisition_price)
            self.assertEqual("USD", rows[0].acquisition_currency)
            self.assertCountEqual(["deck", "trade"], rows[0].tags)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            condition_audits = [row for row in audit_rows if row.action == "set_condition"]
            self.assertEqual(2, len(condition_audits))
            self.assertTrue(all(row.metadata["merged"] for row in condition_audits))
            self.assertTrue(all(row.metadata["keep_acquisition"] == "source" for row in condition_audits))

    def test_bulk_mutate_inventory_items_set_condition_rejects_invalid_field_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
            )
            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(ValidationError, "condition_code is required for set_condition"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_condition",
                    item_ids=[item_id],
                    tags=None,
                )

            with self.assertRaisesRegex(
                ValidationError,
                "keep_acquisition only applies when merge is true for set_condition",
            ):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_condition",
                    item_ids=[item_id],
                    tags=None,
                    condition_code="LP",
                    keep_acquisition="target",
                )

    def test_transfer_inventory_items_dry_run_reports_copy_merge_and_failure_without_mutating_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            self._insert_test_card(db_path, scryfall_id="merge-card", collector_number="2")
            self._insert_test_card(db_path, scryfall_id="fail-card", collector_number="3")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)

            self._insert_inventory_item(
                db_path,
                inventory_slug="source",
                scryfall_id="copy-card",
                quantity=2,
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="source",
                scryfall_id="merge-card",
                quantity=1,
                location="Binder B",
                acquisition_price="1.00",
                acquisition_currency="USD",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="source",
                scryfall_id="fail-card",
                quantity=1,
                location="Binder C",
                acquisition_price="5.00",
                acquisition_currency="USD",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="target",
                scryfall_id="merge-card",
                quantity=3,
                location="Binder B",
                acquisition_price="1.00",
                acquisition_currency="USD",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="target",
                scryfall_id="fail-card",
                quantity=4,
                location="Binder C",
                acquisition_price="7.50",
                acquisition_currency="USD",
            )
            with connect(db_path) as connection:
                source_item_ids = [
                    int(row["id"])
                    for row in connection.execute(
                        """
                        SELECT ii.id
                        FROM inventory_items ii
                        JOIN inventories i ON i.id = ii.inventory_id
                        WHERE i.slug = 'source'
                        ORDER BY ii.id
                        """
                    ).fetchall()
                ]

            result = transfer_inventory_items(
                db_path,
                source_inventory_slug="source",
                target_inventory_slug="target",
                mode="move",
                item_ids=source_item_ids,
                on_conflict="merge",
                dry_run=True,
            )
            self.assertIsInstance(result, InventoryTransferResult)
            self.assertTrue(result.dry_run)
            self.assertEqual("items", result.selection_kind)
            self.assertEqual(source_item_ids, result.requested_item_ids)
            self.assertEqual(0, result.copied_count)
            self.assertEqual(1, result.moved_count)
            self.assertEqual(1, result.merged_count)
            self.assertEqual(1, result.failed_count)
            self.assertEqual(3, result.results_returned)
            self.assertFalse(result.results_truncated)
            self.assertEqual(
                ["would_move", "would_merge", "would_fail"],
                [row.status for row in result.results],
            )

            source_rows = list_owned_filtered(
                db_path,
                inventory_slug="source",
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
            target_rows = list_owned_filtered(
                db_path,
                inventory_slug="target",
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
            self.assertEqual(3, len(source_rows))
            self.assertEqual(2, len(target_rows))

    def test_transfer_inventory_items_copy_mode_copies_rows_and_writes_grouped_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)
            self._insert_inventory_item(
                db_path,
                inventory_slug="source",
                scryfall_id="copy-card",
                quantity=2,
                location="Binder A",
                tags_json='["deck"]',
                printing_selection_mode="defaulted",
            )
            with connect(db_path) as connection:
                source_item_id = int(
                    connection.execute(
                        """
                        SELECT ii.id
                        FROM inventory_items ii
                        JOIN inventories i ON i.id = ii.inventory_id
                        WHERE i.slug = 'source'
                        """
                    ).fetchone()["id"]
                )

            result = transfer_inventory_items(
                db_path,
                source_inventory_slug="source",
                target_inventory_slug="target",
                mode="copy",
                item_ids=[source_item_id],
                on_conflict="fail",
                actor_type="api",
                actor_id="transfer-user",
                request_id="req-transfer-copy",
            )
            self.assertEqual(1, result.copied_count)
            self.assertEqual(0, result.merged_count)
            self.assertEqual("copied", result.results[0].status)
            self.assertFalse(result.results[0].source_removed)
            self.assertIsNotNone(result.results[0].target_item_id)

            source_rows = list_owned_filtered(
                db_path,
                inventory_slug="source",
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
            target_rows = list_owned_filtered(
                db_path,
                inventory_slug="target",
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
            self.assertEqual(1, len(source_rows))
            self.assertEqual(1, len(target_rows))
            self.assertEqual(2, target_rows[0].quantity)
            self.assertEqual(["deck"], target_rows[0].tags)
            self.assertEqual("defaulted", source_rows[0].printing_selection_mode)
            self.assertEqual("defaulted", target_rows[0].printing_selection_mode)

            source_audit = list_inventory_audit_events(db_path, inventory_slug="source", limit=10)
            target_audit = list_inventory_audit_events(db_path, inventory_slug="target", limit=10)
            self.assertEqual("transfer_items", source_audit[0].action)
            self.assertEqual("transfer_items", target_audit[0].action)
            self.assertEqual("source", source_audit[0].metadata["role"])
            self.assertEqual("target", target_audit[0].metadata["role"])
            self.assertEqual("copy", source_audit[0].metadata["mode"])
            self.assertEqual("copied", target_audit[0].metadata["status"])
            self.assertEqual("req-transfer-copy", source_audit[0].request_id)
            self.assertEqual("req-transfer-copy", target_audit[0].request_id)

    def test_transfer_inventory_items_move_mode_merges_rows_and_keeps_selected_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="merge-card")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)
            self._insert_inventory_item(
                db_path,
                inventory_slug="source",
                scryfall_id="merge-card",
                quantity=2,
                location="Binder A",
                acquisition_price="1.25",
                acquisition_currency="USD",
                notes="source note",
                tags_json='["deck"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="target",
                scryfall_id="merge-card",
                quantity=3,
                location="Binder A",
                acquisition_price="2.50",
                acquisition_currency="USD",
                notes="target note",
                tags_json='["trade"]',
            )
            with connect(db_path) as connection:
                source_item_id = int(
                    connection.execute(
                        """
                        SELECT ii.id
                        FROM inventory_items ii
                        JOIN inventories i ON i.id = ii.inventory_id
                        WHERE i.slug = 'source'
                        """
                    ).fetchone()["id"]
                )

            result = transfer_inventory_items(
                db_path,
                source_inventory_slug="source",
                target_inventory_slug="target",
                mode="move",
                item_ids=[source_item_id],
                on_conflict="merge",
                keep_acquisition="target",
                actor_type="api",
                actor_id="transfer-user",
                request_id="req-transfer-merge",
            )
            self.assertEqual(1, result.merged_count)
            self.assertEqual("merged", result.results[0].status)
            self.assertTrue(result.results[0].source_removed)

            source_rows = list_owned_filtered(
                db_path,
                inventory_slug="source",
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
            target_rows = list_owned_filtered(
                db_path,
                inventory_slug="target",
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
            self.assertEqual([], source_rows)
            self.assertEqual(1, len(target_rows))
            self.assertEqual(5, target_rows[0].quantity)
            self.assertEqual(Decimal("2.50"), target_rows[0].acquisition_price)
            self.assertEqual("USD", target_rows[0].acquisition_currency)
            self.assertCountEqual(["deck", "trade"], target_rows[0].tags)
            self.assertIn("source note", target_rows[0].notes)
            self.assertIn("target note", target_rows[0].notes)
            self.assertEqual("explicit", target_rows[0].printing_selection_mode)

    def test_transfer_inventory_items_fail_conflict_rolls_back_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            self._insert_test_card(db_path, scryfall_id="conflict-card", collector_number="2")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="copy-card", location="Binder A")
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="conflict-card", location="Binder B")
            self._insert_inventory_item(db_path, inventory_slug="target", scryfall_id="conflict-card", location="Binder B")
            with connect(db_path) as connection:
                source_item_ids = [
                    int(row["id"])
                    for row in connection.execute(
                        """
                        SELECT ii.id
                        FROM inventory_items ii
                        JOIN inventories i ON i.id = ii.inventory_id
                        WHERE i.slug = 'source'
                        ORDER BY ii.id
                        """
                    ).fetchall()
                ]

            with self.assertRaisesRegex(ConflictError, "would collide with an existing row in inventory 'target'"):
                transfer_inventory_items(
                    db_path,
                    source_inventory_slug="source",
                    target_inventory_slug="target",
                    mode="move",
                    item_ids=source_item_ids,
                    on_conflict="fail",
                )

            source_rows = list_owned_filtered(
                db_path,
                inventory_slug="source",
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
            target_rows = list_owned_filtered(
                db_path,
                inventory_slug="target",
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
            self.assertEqual(2, len(source_rows))
            self.assertEqual(1, len(target_rows))
            self.assertEqual([], list_inventory_audit_events(db_path, inventory_slug="source", limit=10))
            self.assertEqual([], list_inventory_audit_events(db_path, inventory_slug="target", limit=10))

    def test_transfer_inventory_items_rejects_invalid_request_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="copy-card")
            with connect(db_path) as connection:
                source_item_id = int(
                    connection.execute(
                        """
                        SELECT ii.id
                        FROM inventory_items ii
                        JOIN inventories i ON i.id = ii.inventory_id
                        WHERE i.slug = 'source'
                        """
                    ).fetchone()["id"]
                )

            with self.assertRaisesRegex(ValidationError, "target_inventory_slug must be different"):
                transfer_inventory_items(
                    db_path,
                    source_inventory_slug="source",
                    target_inventory_slug="source",
                    mode="copy",
                    item_ids=[source_item_id],
                    on_conflict="fail",
                )

            with self.assertRaisesRegex(ValidationError, "keep_acquisition only applies when on_conflict is merge"):
                transfer_inventory_items(
                    db_path,
                    source_inventory_slug="source",
                    target_inventory_slug="target",
                    mode="copy",
                    item_ids=[source_item_id],
                    on_conflict="fail",
                    keep_acquisition="target",
                )

    def test_transfer_inventory_items_all_items_moves_entire_source_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            self._insert_test_card(db_path, scryfall_id="other-card", collector_number="2")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="copy-card", location="Binder A")
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="other-card", location="Binder B")

            result = transfer_inventory_items(
                db_path,
                source_inventory_slug="source",
                target_inventory_slug="target",
                mode="move",
                item_ids=None,
                all_items=True,
                on_conflict="fail",
            )
            self.assertEqual("all_items", result.selection_kind)
            self.assertIsNone(result.requested_item_ids)
            self.assertEqual(2, result.requested_count)
            self.assertEqual(2, result.moved_count)
            self.assertEqual(2, result.results_returned)
            self.assertFalse(result.results_truncated)

            source_rows = list_owned_filtered(
                db_path,
                inventory_slug="source",
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
            target_rows = list_owned_filtered(
                db_path,
                inventory_slug="target",
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
            self.assertEqual([], source_rows)
            self.assertEqual(2, len(target_rows))

    def test_transfer_inventory_items_all_items_dry_run_truncates_preview_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)
            for index in range(101):
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="copy-card",
                    location=f"Binder {index}",
                )

            result = transfer_inventory_items(
                db_path,
                source_inventory_slug="source",
                target_inventory_slug="target",
                mode="copy",
                item_ids=None,
                all_items=True,
                on_conflict="fail",
                dry_run=True,
            )
            self.assertEqual("all_items", result.selection_kind)
            self.assertEqual(101, result.requested_count)
            self.assertEqual(101, result.copied_count)
            self.assertEqual(100, result.results_returned)
            self.assertTrue(result.results_truncated)
            self.assertEqual("would_copy", result.results[0].status)

    def test_create_inventory_trims_slug_and_conflicts_after_trim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)

            created = create_inventory(
                db_path,
                slug=" source-copy ",
                display_name="Source Copy",
                description=None,
            )
            self.assertEqual("source-copy", created.slug)

            with self.assertRaisesRegex(ConflictError, "Inventory 'source-copy' already exists"):
                create_inventory(
                    db_path,
                    slug="source-copy",
                    display_name="Duplicate",
                    description=None,
                )

    def test_transfer_inventory_items_normalizes_padded_source_and_target_slugs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            create_inventory(db_path, slug="source", display_name="Source", description=None)
            create_inventory(db_path, slug="target", display_name="Target", description=None)
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="copy-card", location="Binder A")

            result = transfer_inventory_items(
                db_path,
                source_inventory_slug=" source ",
                target_inventory_slug=" target ",
                mode="move",
                item_ids=None,
                all_items=True,
                on_conflict="fail",
            )

            self.assertEqual("source", result.source_inventory)
            self.assertEqual("target", result.target_inventory)
            self.assertEqual(1, result.moved_count)

            source_rows = list_owned_filtered(
                db_path,
                inventory_slug="source",
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
            target_rows = list_owned_filtered(
                db_path,
                inventory_slug="target",
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
            self.assertEqual([], source_rows)
            self.assertEqual(1, len(target_rows))

    def test_duplicate_inventory_copies_all_rows_and_grants_owner_to_actor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            self._insert_test_card(db_path, scryfall_id="other-card", collector_number="2")
            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description="Original description",
                default_location="Trade Binder",
                default_tags="trade, staples",
                notes="Source inventory notes",
                acquisition_price="25.00",
                acquisition_currency="USD",
                actor_id="owner-user",
            )
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="copy-card", quantity=2)
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="other-card", quantity=1)

            result = duplicate_inventory(
                db_path,
                source_inventory_slug="source",
                target_slug="source-copy",
                target_display_name="Source Copy",
                actor_type="api",
                actor_id="duplicator-user",
                request_id="req-duplicate",
            )
            self.assertIsInstance(result, InventoryDuplicateResult)
            self.assertEqual("source", result.source_inventory)
            self.assertEqual("source-copy", result.inventory.slug)
            self.assertEqual("Original description", result.inventory.description)
            self.assertEqual("Trade Binder", result.inventory.default_location)
            self.assertEqual("trade, staples", result.inventory.default_tags)
            self.assertEqual("Source inventory notes", result.inventory.notes)
            self.assertEqual(Decimal("25.00"), result.inventory.acquisition_price)
            self.assertEqual("USD", result.inventory.acquisition_currency)
            self.assertEqual("all_items", result.transfer.selection_kind)
            self.assertEqual(2, result.transfer.copied_count)

            duplicated_rows = list_owned_filtered(
                db_path,
                inventory_slug="source-copy",
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
            self.assertEqual(2, len(duplicated_rows))
            self.assertEqual(["explicit", "explicit"], [row.printing_selection_mode for row in duplicated_rows])
            memberships = list_inventory_memberships(db_path, inventory_slug="source-copy")
            self.assertEqual(["duplicator-user"], [membership.actor_id for membership in memberships])
            self.assertEqual(["owner"], [membership.role for membership in memberships])

    def test_duplicate_inventory_preserves_defaulted_printing_selection_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description="Original description",
                actor_id="owner-user",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="source",
                scryfall_id="copy-card",
                quantity=2,
                printing_selection_mode="defaulted",
            )

            result = duplicate_inventory(
                db_path,
                source_inventory_slug="source",
                target_slug="source-copy",
                target_display_name="Source Copy",
                actor_type="api",
                actor_id="duplicator-user",
                request_id="req-duplicate",
            )

            self.assertEqual(1, result.transfer.copied_count)
            duplicated_rows = list_owned_filtered(
                db_path,
                inventory_slug="source-copy",
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
            self.assertEqual(1, len(duplicated_rows))
            self.assertEqual("defaulted", duplicated_rows[0].printing_selection_mode)

    def test_duplicate_inventory_rolls_back_new_inventory_when_target_slug_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            create_inventory(db_path, slug="source", display_name="Source Collection", description=None)
            create_inventory(db_path, slug="existing", display_name="Existing Collection", description=None)
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="copy-card", quantity=2)

            with self.assertRaisesRegex(ConflictError, "Inventory 'existing' already exists"):
                duplicate_inventory(
                    db_path,
                    source_inventory_slug="source",
                    target_slug="existing",
                    target_display_name="Existing Copy",
                )

            source_rows = list_owned_filtered(
                db_path,
                inventory_slug="source",
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
            existing_rows = list_owned_filtered(
                db_path,
                inventory_slug="existing",
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
            self.assertEqual(1, len(source_rows))
            self.assertEqual([], existing_rows)

    def test_duplicate_inventory_creates_empty_inventory_and_uses_explicit_description_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description="Original description",
                actor_id="owner-user",
            )

            result = duplicate_inventory(
                db_path,
                source_inventory_slug="source",
                target_slug="source-copy",
                target_display_name="Source Copy",
                target_description="Override description",
                actor_type="api",
                actor_id="duplicator-user",
                request_id="req-duplicate-empty",
            )

            self.assertEqual("Override description", result.inventory.description)
            self.assertEqual(0, result.transfer.requested_count)
            self.assertEqual(0, result.transfer.copied_count)
            self.assertEqual([], result.transfer.results)

            duplicated_rows = list_owned_filtered(
                db_path,
                inventory_slug="source-copy",
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
            self.assertEqual([], duplicated_rows)

    def test_duplicate_inventory_normalizes_padded_target_slug(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path, scryfall_id="copy-card", collector_number="1")
            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description="Original description",
                actor_id="owner-user",
            )
            self._insert_inventory_item(db_path, inventory_slug="source", scryfall_id="copy-card", quantity=2)

            result = duplicate_inventory(
                db_path,
                source_inventory_slug=" source ",
                target_slug=" source-copy ",
                target_display_name="Source Copy",
                actor_type="api",
                actor_id="duplicator-user",
                request_id="req-duplicate-normalized",
            )

            self.assertEqual("source", result.source_inventory)
            self.assertEqual("source-copy", result.inventory.slug)
            self.assertEqual("source-copy", result.transfer.target_inventory)

            duplicated_rows = list_owned_filtered(
                db_path,
                inventory_slug="source-copy",
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
            self.assertEqual(1, len(duplicated_rows))

    def test_bulk_mutate_inventory_items_rolls_back_when_audit_write_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                location="Binder A",
                tags_json='["deck"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                location="Binder B",
                tags_json='["trade"]',
            )
            with connect(db_path) as connection:
                item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

            with patch(
                "mtg_source_stack.inventory.operations.bulk.write_inventory_audit_event",
                side_effect=RuntimeError("audit write failed"),
            ):
                with self.assertRaisesRegex(RuntimeError, "audit write failed"):
                    bulk_mutate_inventory_items(
                        db_path,
                        inventory_slug="personal",
                        operation="add_tags",
                        item_ids=item_ids,
                        tags=["featured"],
                    )

            rows = list_owned_filtered(
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
            row_tags = {row.item_id: row.tags for row in rows}
            self.assertEqual(["deck"], row_tags[item_ids[0]])
            self.assertEqual(["trade"], row_tags[item_ids[1]])

    def test_bulk_mutate_inventory_items_rejects_item_ids_outside_the_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            create_inventory(
                db_path,
                slug="trade-binder",
                display_name="Trade Binder",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="trade-binder",
                scryfall_id="race-card-1",
                location="Binder A",
            )
            with connect(db_path) as connection:
                foreign_item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(NotFoundError, "One or more item_ids were not found in inventory 'personal'"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="add_tags",
                    item_ids=[foreign_item_id],
                    tags=["trade"],
                )

    def test_bulk_mutate_inventory_items_validates_quantity_and_acquisition_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
            )
            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(ValidationError, "quantity is required for set_quantity"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_quantity",
                    item_ids=[item_id],
                    tags=None,
                )

            with self.assertRaisesRegex(
                ValidationError,
                "Cannot store an acquisition currency without an acquisition price",
            ):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="set_acquisition",
                    item_ids=[item_id],
                    tags=None,
                    acquisition_currency="USD",
                )

    def test_bulk_mutate_inventory_items_rejects_unrelated_fields_for_tag_operations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                tags_json='["deck"]',
            )
            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(ValidationError, "quantity is not valid for add_tags"):
                bulk_mutate_inventory_items(
                    db_path,
                    inventory_slug="personal",
                    operation="add_tags",
                    item_ids=[item_id],
                    tags=["trade"],
                    quantity=2,
                )

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

    def test_add_card_concurrent_identity_collision_returns_conflict_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            def insert_conflicting_row() -> None:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="race-card-1",
                    quantity=1,
                    location="Binder A",
                )

            with self.assertRaisesRegex(
                ConflictError,
                "Adding card would collide with an existing inventory row due to a concurrent write",
            ):
                add_card(
                    db_path,
                    inventory_slug="personal",
                    inventory_display_name=None,
                    scryfall_id="race-card-1",
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
                    before_write=insert_conflicting_row,
                )

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT quantity, location
                    FROM inventory_items
                    ORDER BY id
                    """
                ).fetchall()

            self.assertEqual(1, len(rows))
            self.assertEqual(1, rows[0]["quantity"])
            self.assertEqual("Binder A", rows[0]["location"])

    def test_set_location_concurrent_identity_collision_returns_conflict_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            source = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
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

            def insert_conflicting_row() -> None:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="race-card-1",
                    quantity=1,
                    location="Binder B",
                )

            with self.assertRaisesRegex(
                ConflictError,
                "Changing location would collide with an existing inventory row",
            ):
                set_location(
                    db_path,
                    inventory_slug="personal",
                    item_id=source.item_id,
                    location="Binder B",
                    before_write=insert_conflicting_row,
                )

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT quantity, location
                    FROM inventory_items
                    ORDER BY location
                    """
                ).fetchall()

            self.assertEqual(
                [(2, "Binder A"), (1, "Binder B")],
                [(row["quantity"], row["location"]) for row in rows],
            )

    def test_set_location_concurrent_identity_collision_merges_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            source = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
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

            def insert_conflicting_row() -> None:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="race-card-1",
                    quantity=3,
                    location="Binder B",
                )

            result = set_location(
                db_path,
                inventory_slug="personal",
                item_id=source.item_id,
                location="Binder B",
                merge=True,
                before_write=insert_conflicting_row,
            )

            self.assertTrue(result.merged)
            self.assertEqual(5, result.quantity)
            self.assertEqual("Binder B", result.location)

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT quantity, location
                    FROM inventory_items
                    ORDER BY id
                    """
                ).fetchall()

            self.assertEqual([(5, "Binder B")], [(row["quantity"], row["location"]) for row in rows])

    def test_set_condition_concurrent_identity_collision_returns_conflict_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            source = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
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

            def insert_conflicting_row() -> None:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="race-card-1",
                    quantity=1,
                    condition_code="LP",
                    location="Binder A",
                )

            with self.assertRaisesRegex(
                ConflictError,
                "Changing condition would collide with an existing inventory row",
            ):
                set_condition(
                    db_path,
                    inventory_slug="personal",
                    item_id=source.item_id,
                    condition_code="LP",
                    before_write=insert_conflicting_row,
                )

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT quantity, condition_code
                    FROM inventory_items
                    ORDER BY condition_code
                    """
                ).fetchall()

            self.assertEqual(
                [(1, "LP"), (2, "NM")],
                [(row["quantity"], row["condition_code"]) for row in rows],
            )

    def test_set_condition_concurrent_identity_collision_merges_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            source = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
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

            def insert_conflicting_row() -> None:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="race-card-1",
                    quantity=4,
                    condition_code="LP",
                    location="Binder A",
                )

            result = set_condition(
                db_path,
                inventory_slug="personal",
                item_id=source.item_id,
                condition_code="LP",
                merge=True,
                before_write=insert_conflicting_row,
            )

            self.assertTrue(result.merged)
            self.assertEqual(6, result.quantity)
            self.assertEqual("LP", result.condition_code)

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT quantity, condition_code
                    FROM inventory_items
                    ORDER BY id
                    """
                ).fetchall()

            self.assertEqual([(6, "LP")], [(row["quantity"], row["condition_code"]) for row in rows])

    def test_split_row_concurrent_identity_collision_returns_conflict_error_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            source = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
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

            def insert_conflicting_row() -> None:
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="race-card-1",
                    quantity=1,
                    location="Binder B",
                )

            with self.assertRaisesRegex(
                ConflictError,
                "Splitting row would collide with an existing inventory row due to a concurrent write",
            ):
                split_row(
                    db_path,
                    inventory_slug="personal",
                    item_id=source.item_id,
                    quantity=1,
                    condition_code=None,
                    finish=None,
                    language_code=None,
                    location="Binder B",
                    before_write=insert_conflicting_row,
                )

            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT quantity, location
                    FROM inventory_items
                    ORDER BY location
                    """
                ).fetchall()

            self.assertEqual(
                [(2, "Binder A"), (1, "Binder B")],
                [(row["quantity"], row["location"]) for row in rows],
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
            self.assertEqual("oracle-typed-1", add_result.oracle_id)
            self.assertEqual("explicit", add_result.printing_selection_mode)

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

    def test_split_row_preserves_printing_selection_mode_and_merge_rows_promotes_to_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=3,
                location="Binder A",
                printing_selection_mode="defaulted",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="race-card-1",
                quantity=1,
                location="Binder C",
                printing_selection_mode="explicit",
            )
            with connect(db_path) as connection:
                rows = connection.execute(
                    """
                    SELECT id, location, printing_selection_mode
                    FROM inventory_items
                    ORDER BY location
                    """
                ).fetchall()
            source_item_id = int(rows[0]["id"])
            explicit_target_id = int(rows[1]["id"])

            split_result = split_row(
                db_path,
                inventory_slug="personal",
                item_id=source_item_id,
                quantity=1,
                condition_code=None,
                finish=None,
                language_code=None,
                location="Binder B",
            )

            self.assertEqual("defaulted", split_result.printing_selection_mode)

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
            modes_by_location = {row.location: row.printing_selection_mode for row in owned_rows}
            self.assertEqual("defaulted", modes_by_location["Binder A"])
            self.assertEqual("defaulted", modes_by_location["Binder B"])
            self.assertEqual("explicit", modes_by_location["Binder C"])

            merge_result = merge_rows(
                db_path,
                inventory_slug="personal",
                source_item_id=split_result.item_id,
                target_item_id=explicit_target_id,
            )

            self.assertEqual("explicit", merge_result.printing_selection_mode)
            with connect(db_path) as connection:
                merged_row = connection.execute(
                    "SELECT printing_selection_mode FROM inventory_items WHERE id = ?",
                    (explicit_target_id,),
                ).fetchone()

            self.assertEqual("explicit", merged_row["printing_selection_mode"])

    def test_set_printing_updates_to_sibling_printing_and_preserves_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-old-en",
                oracle_id="printing-oracle-1",
                name="Printing Test Card",
                set_code="old",
                set_name="Old Set",
                collector_number="7",
                lang="en",
                finishes_json='["normal","foil"]',
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-new-ja",
                oracle_id="printing-oracle-1",
                name="Printing Test Card",
                set_code="neo",
                set_name="New Set",
                collector_number="8",
                lang="ja",
                finishes_json='["normal","foil"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-old-en",
                quantity=2,
                finish="normal",
                language_code="en",
                location="Binder A",
                acquisition_price="1.50",
                acquisition_currency="USD",
                notes="Signed copy",
                tags_json='["favorite"]',
                printing_selection_mode="defaulted",
            )

            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            result = set_printing(
                db_path,
                inventory_slug="personal",
                item_id=item_id,
                scryfall_id="printing-new-ja",
                request_id="req-set-printing",
            )

            self.assertIsInstance(result, SetPrintingResult)
            self.assertEqual("set_printing", result.operation)
            self.assertEqual("printing-old-en", result.old_scryfall_id)
            self.assertEqual("normal", result.old_finish)
            self.assertEqual("en", result.old_language_code)
            self.assertEqual("printing-new-ja", result.scryfall_id)
            self.assertEqual("printing-oracle-1", result.oracle_id)
            self.assertEqual("normal", result.finish)
            self.assertEqual("ja", result.language_code)
            self.assertEqual(2, result.quantity)
            self.assertEqual("Binder A", result.location)
            self.assertEqual(Decimal("1.50"), result.acquisition_price)
            self.assertEqual("USD", result.acquisition_currency)
            self.assertEqual("Signed copy", result.notes)
            self.assertEqual(["favorite"], result.tags)
            self.assertEqual("explicit", result.printing_selection_mode)
            self.assertFalse(result.merged)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual("set_printing", audit_rows[0].action)
            self.assertEqual("printing-old-en", audit_rows[0].metadata["old_scryfall_id"])
            self.assertEqual("printing-new-ja", audit_rows[0].metadata["new_scryfall_id"])
            self.assertEqual("normal", audit_rows[0].metadata["new_finish"])
            self.assertEqual("ja", audit_rows[0].metadata["new_language_code"])

    def test_set_printing_auto_selects_a_supported_finish_when_current_finish_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-old-normal",
                oracle_id="printing-oracle-2",
                name="Finish Drift Card",
                set_code="old",
                set_name="Old Set",
                collector_number="10",
                lang="en",
                finishes_json='["normal"]',
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-new-foil",
                oracle_id="printing-oracle-2",
                name="Finish Drift Card",
                set_code="sld",
                set_name="Secret Lair",
                collector_number="11",
                lang="en",
                finishes_json='["foil"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-old-normal",
                finish="normal",
                language_code="en",
            )

            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            result = set_printing(
                db_path,
                inventory_slug="personal",
                item_id=item_id,
                scryfall_id="printing-new-foil",
            )

            self.assertEqual("printing-new-foil", result.scryfall_id)
            self.assertEqual("foil", result.finish)
            self.assertEqual("normal", result.old_finish)
            self.assertEqual("explicit", result.printing_selection_mode)

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertTrue(audit_rows[0].metadata["auto_selected_finish"])

    def test_set_printing_rejects_non_sibling_printings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-current",
                oracle_id="printing-oracle-3",
                name="Sibling Card",
                finishes_json='["normal"]',
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-other-card",
                oracle_id="printing-oracle-4",
                name="Different Card",
                set_code="oth",
                collector_number="2",
                finishes_json='["normal"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-current",
            )

            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(
                ValidationError,
                "Target printing must belong to the same oracle card",
            ):
                set_printing(
                    db_path,
                    inventory_slug="personal",
                    item_id=item_id,
                    scryfall_id="printing-other-card",
                )

    def test_set_printing_conflict_requires_merge_and_merge_promotes_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-source",
                oracle_id="printing-oracle-5",
                name="Merge Printing Card",
                set_code="old",
                collector_number="1",
                lang="en",
                finishes_json='["normal"]',
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-target",
                oracle_id="printing-oracle-5",
                name="Merge Printing Card",
                set_code="new",
                collector_number="2",
                lang="en",
                finishes_json='["normal"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-source",
                quantity=2,
                location="Binder A",
                printing_selection_mode="defaulted",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-target",
                quantity=1,
                location="Binder A",
                printing_selection_mode="defaulted",
            )

            with connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT id, scryfall_id FROM inventory_items ORDER BY id"
                ).fetchall()
            source_item_id = int(rows[0]["id"])

            with self.assertRaisesRegex(ConflictError, "Changing printing would collide"):
                set_printing(
                    db_path,
                    inventory_slug="personal",
                    item_id=source_item_id,
                    scryfall_id="printing-target",
                )

            result = set_printing(
                db_path,
                inventory_slug="personal",
                item_id=source_item_id,
                scryfall_id="printing-target",
                merge=True,
            )

            self.assertTrue(result.merged)
            self.assertEqual(source_item_id, result.merged_source_item_id)
            self.assertEqual(3, result.quantity)
            self.assertEqual("printing-target", result.scryfall_id)
            self.assertEqual("explicit", result.printing_selection_mode)

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
            self.assertEqual(1, len(owned_rows))
            self.assertEqual("explicit", owned_rows[0].printing_selection_mode)

    def test_set_printing_can_confirm_a_defaulted_row_without_changing_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-confirm",
                oracle_id="printing-oracle-6",
                name="Confirm Printing Card",
                finishes_json='["normal","foil"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-confirm",
                finish="normal",
                language_code="en",
                printing_selection_mode="defaulted",
            )

            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            result = set_printing(
                db_path,
                inventory_slug="personal",
                item_id=item_id,
                scryfall_id="printing-confirm",
            )

            self.assertEqual("printing-confirm", result.scryfall_id)
            self.assertEqual("normal", result.finish)
            self.assertEqual("explicit", result.printing_selection_mode)
            self.assertFalse(result.merged)

    def test_set_printing_rejects_same_printing_finish_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-same-id",
                oracle_id="printing-oracle-7",
                name="Same Printing Card",
                finishes_json='["normal","foil"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-same-id",
                finish="normal",
                language_code="en",
                printing_selection_mode="defaulted",
            )

            with connect(db_path) as connection:
                item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

            with self.assertRaisesRegex(
                ValidationError,
                "finish and language stay unchanged",
            ):
                set_printing(
                    db_path,
                    inventory_slug="personal",
                    item_id=item_id,
                    scryfall_id="printing-same-id",
                    finish="foil",
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
            self.assertEqual(1, len(owned_rows))
            self.assertEqual("normal", owned_rows[0].finish)
            self.assertEqual("defaulted", owned_rows[0].printing_selection_mode)

    def test_set_printing_rejects_same_printing_finish_changes_even_with_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_catalog_card(
                db_path,
                scryfall_id="printing-same-id-merge",
                oracle_id="printing-oracle-8",
                name="Same Printing Merge Card",
                finishes_json='["normal","foil"]',
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-same-id-merge",
                quantity=2,
                finish="normal",
                language_code="en",
                location="Binder A",
                printing_selection_mode="defaulted",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="printing-same-id-merge",
                quantity=1,
                finish="foil",
                language_code="en",
                location="Binder A",
                printing_selection_mode="explicit",
            )

            with connect(db_path) as connection:
                rows = connection.execute(
                    "SELECT id FROM inventory_items WHERE finish = 'normal'"
                ).fetchall()
            source_item_id = int(rows[0]["id"])

            with self.assertRaisesRegex(
                ValidationError,
                "finish and language stay unchanged",
            ):
                set_printing(
                    db_path,
                    inventory_slug="personal",
                    item_id=source_item_id,
                    scryfall_id="printing-same-id-merge",
                    finish="foil",
                    merge=True,
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
            self.assertEqual(2, len(owned_rows))
            rows_by_finish = {row.finish: row.quantity for row in owned_rows}
            self.assertEqual({"normal": 2, "foil": 1}, rows_by_finish)

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
                        finishes_json,
                        image_uris_json
                    )
                    VALUES (
                        'price-card-1',
                        'oracle-1',
                        'Price Test Card',
                        'tst',
                        'Test Set',
                        '1',
                        '["normal","foil"]',
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
            self.assertEqual("oracle-1", owned_rows[0].oracle_id)
            self.assertEqual("USD", owned_rows[0].currency)
            self.assertEqual("https://example.test/cards/price-card-1-small.jpg", owned_rows[0].image_uri_small)
            self.assertEqual("https://example.test/cards/price-card-1-normal.jpg", owned_rows[0].image_uri_normal)
            self.assertEqual(["normal", "foil"], owned_rows[0].allowed_finishes)
            self.assertEqual(Decimal("2.5"), owned_rows[0].unit_price)
            self.assertEqual(Decimal("5.0"), owned_rows[0].est_value)
            self.assertEqual("explicit", owned_rows[0].printing_selection_mode)
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

    def test_inventory_health_preview_limit_truncates_each_preview_bucket_without_changing_summary_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            self._insert_test_card(
                db_path,
                scryfall_id="preview-card-alpha",
                oracle_id="preview-oracle-alpha",
                name="Alpha Preview Card",
                set_code="prv",
                set_name="Preview Set",
                collector_number="1",
                finishes_json='["normal","foil"]',
            )
            self._insert_test_card(
                db_path,
                scryfall_id="preview-card-beta",
                oracle_id="preview-oracle-beta",
                name="Beta Preview Card",
                set_code="prv",
                set_name="Preview Set",
                collector_number="2",
                finishes_json='["normal","foil"]',
            )

            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="preview-card-alpha",
                quantity=1,
                location="",
                notes=f"{MERGED_ACQUISITION_NOTE_MARKER}91: 1.00 USD",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="preview-card-alpha",
                quantity=2,
                location="Binder A",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="preview-card-beta",
                quantity=1,
                location="",
                notes=f"{MERGED_ACQUISITION_NOTE_MARKER}92: 2.00 USD",
            )
            self._insert_inventory_item(
                db_path,
                inventory_slug="personal",
                scryfall_id="preview-card-beta",
                quantity=2,
                location="Binder B",
            )

            self._insert_price_snapshot(
                db_path,
                scryfall_id="preview-card-alpha",
                finish="normal",
                snapshot_date="2026-01-01",
                price_value=1.25,
            )
            self._insert_price_snapshot(
                db_path,
                scryfall_id="preview-card-alpha",
                finish="foil",
                snapshot_date="2026-03-30",
                price_value=4.50,
            )
            self._insert_price_snapshot(
                db_path,
                scryfall_id="preview-card-beta",
                finish="normal",
                snapshot_date="2026-01-02",
                price_value=2.25,
            )
            self._insert_price_snapshot(
                db_path,
                scryfall_id="preview-card-beta",
                finish="foil",
                snapshot_date="2026-03-31",
                price_value=5.50,
            )

            result = inventory_health(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                stale_days=30,
                preview_limit=1,
            )

            self.assertEqual(1, result.preview_limit)
            self.assertEqual(4, result.summary.item_rows)
            self.assertEqual(6, result.summary.total_cards)
            self.assertEqual(4, result.summary.missing_price_rows)
            self.assertEqual(2, result.summary.missing_location_rows)
            self.assertEqual(4, result.summary.missing_tag_rows)
            self.assertEqual(2, result.summary.merge_note_rows)
            self.assertEqual(4, result.summary.stale_price_rows)
            self.assertEqual(2, result.summary.duplicate_groups)

            self.assertEqual(1, len(result.missing_price_rows))
            self.assertEqual(1, len(result.missing_location_rows))
            self.assertEqual(1, len(result.missing_tag_rows))
            self.assertEqual(1, len(result.merge_note_rows))
            self.assertEqual(1, len(result.stale_price_rows))
            self.assertEqual(1, len(result.duplicate_groups))

    def test_blank_location_is_normalized_to_none_in_add_owned_and_audit_responses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
                tcgplayer_product_id=None,
                name=None,
                set_code=None,
                collector_number=None,
                lang=None,
                quantity=1,
                condition_code="NM",
                finish="normal",
                language_code="en",
                location="",
                acquisition_price=None,
                acquisition_currency=None,
                notes=None,
                tags=None,
            )

            self.assertIsNone(added.location)

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
            self.assertEqual(1, len(owned_rows))
            self.assertIsNone(owned_rows[0].location)

            audit_rows = list_inventory_audit_events(
                db_path,
                inventory_slug="personal",
                limit=10,
            )
            self.assertEqual("add_card", audit_rows[0].action)
            self.assertIsNone(audit_rows[0].after["location"])

    def test_blank_location_is_normalized_to_none_in_set_location_and_audit_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            self._insert_test_card(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )
            added = add_card(
                db_path,
                inventory_slug="personal",
                inventory_display_name=None,
                scryfall_id="race-card-1",
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

            result = set_location(
                db_path,
                inventory_slug="personal",
                item_id=added.item_id,
                location="",
            )

            self.assertIsNone(result.location)
            self.assertEqual("Binder A", result.old_location)

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
            self.assertEqual(1, len(owned_rows))
            self.assertIsNone(owned_rows[0].location)

            audit_rows = list_inventory_audit_events(
                db_path,
                inventory_slug="personal",
                limit=10,
            )
            self.assertEqual("set_location", audit_rows[0].action)
            self.assertEqual("Binder A", audit_rows[0].before["location"])
            self.assertIsNone(audit_rows[0].after["location"])
            self.assertEqual("Binder A", audit_rows[0].metadata["old_location"])
            self.assertIsNone(audit_rows[0].metadata["new_location"])

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

            rendered_export = render_inventory_csv_export(
                db_path,
                inventory_slug="personal",
                provider="tcgplayer",
                profile="default",
                query="Lightning",
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
                limit=None,
            )
            self.assertEqual("default", rendered_export.profile)
            self.assertEqual("personal-default-export.csv", rendered_export.filename)
            self.assertEqual(1, rendered_export.rows_exported)
            self.assertIn("inventory,provider,item_id,scryfall_id,card_name", rendered_export.csv_text)
            self.assertIn("Lightning Bolt", rendered_export.csv_text)
            self.assertNotIn("Counterspell", rendered_export.csv_text)

            with self.assertRaises(ValidationError):
                export_inventory_csv(
                    db_path,
                    inventory_slug="personal",
                    provider="tcgplayer",
                    output_path=export_path,
                    profile="unknown-profile",
                    query=None,
                    set_code=None,
                    rarity=None,
                    finish=None,
                    condition_code=None,
                    language_code=None,
                    location=None,
                    tags=None,
                    limit=None,
                )

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
