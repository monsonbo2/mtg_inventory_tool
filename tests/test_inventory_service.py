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
    bulk_mutate_inventory_items,
    create_inventory,
    inventory_health,
    inventory_report,
    list_card_printings_for_oracle,
    list_inventory_audit_events,
    list_owned_filtered,
    list_price_gaps,
    merge_rows,
    reconcile_prices,
    remove_card,
    resolve_card_row,
    search_card_names,
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
                    is_default_add_searchable
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

            rows = search_card_names(db_path, query="Search Group", exact=False, limit=10)

            self.assertEqual(1, len(rows))
            self.assertEqual("grouped-search-oracle", rows[0].oracle_id)
            self.assertEqual("Search Group Card", rows[0].name)
            self.assertEqual(3, rows[0].printings_count)
            self.assertEqual(["en", "ja", "de"], rows[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/grouped-search-en-small.jpg",
                rows[0].image_uri_small,
            )
            self.assertEqual(
                "https://example.test/cards/grouped-search-en-normal.jpg",
                rows[0].image_uri_normal,
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

            rows = search_card_names(db_path, query="Scoped Group", exact=False, limit=10)

            self.assertEqual(1, len(rows))
            self.assertEqual("scoped-group-oracle", rows[0].oracle_id)
            self.assertEqual("Scoped Group Card", rows[0].name)
            self.assertEqual(1, rows[0].printings_count)
            self.assertEqual(["ja"], rows[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/scoped-group-ja-small.jpg",
                rows[0].image_uri_small,
            )
            self.assertEqual(
                "https://example.test/cards/scoped-group-ja-normal.jpg",
                rows[0].image_uri_normal,
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

            rows = search_card_names(db_path, query="Exact Group Card", exact=True, limit=10)

            self.assertEqual(1, len(rows))
            self.assertEqual("exact-group-oracle", rows[0].oracle_id)
            self.assertEqual("Exact Group Card", rows[0].name)
            self.assertEqual(2, rows[0].printings_count)
            self.assertEqual(["en", "ja"], rows[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/exact-group-en-small.jpg",
                rows[0].image_uri_small,
            )

    def test_search_card_names_substring_query_falls_back_to_like_matching(self) -> None:
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

            rows = search_card_names(db_path, query="ning", exact=False, limit=10)

            self.assertEqual(1, len(rows))
            self.assertEqual("substring-group-oracle", rows[0].oracle_id)
            self.assertEqual("Lightning Bolt", rows[0].name)

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

            rows = search_card_names(db_path, query="Scoped Group", exact=False, limit=10, scope="all")

            self.assertEqual(1, len(rows))
            self.assertEqual("scoped-group-oracle", rows[0].oracle_id)
            self.assertEqual(2, rows[0].printings_count)
            self.assertEqual(["en", "ja"], rows[0].available_languages)
            self.assertEqual(
                "https://example.test/cards/scoped-group-en-small.jpg",
                rows[0].image_uri_small,
            )
            self.assertEqual(
                "https://example.test/cards/scoped-group-en-normal.jpg",
                rows[0].image_uri_normal,
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

            all_rows = list_card_printings_for_oracle(db_path, "lookup-oracle", lang="all")
            self.assertEqual(["lookup-ja", "lookup-en-new", "lookup-en-old"], [row.scryfall_id for row in all_rows])

            japanese_rows = list_card_printings_for_oracle(db_path, "lookup-oracle", lang="ja")
            self.assertEqual(["lookup-ja"], [row.scryfall_id for row in japanese_rows])

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

            with self.assertRaisesRegex(NotFoundError, "No printings found for oracle_id 'missing-oracle'"):
                list_card_printings_for_oracle(db_path, "missing-oracle")

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
                "mtg_source_stack.inventory.mutations.write_inventory_audit_event",
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
            self.assertEqual("USD", owned_rows[0].currency)
            self.assertEqual("https://example.test/cards/price-card-1-small.jpg", owned_rows[0].image_uri_small)
            self.assertEqual("https://example.test/cards/price-card-1-normal.jpg", owned_rows[0].image_uri_normal)
            self.assertEqual(["normal", "foil"], owned_rows[0].allowed_finishes)
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
