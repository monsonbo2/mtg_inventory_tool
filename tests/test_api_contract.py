"""Contract-focused tests for API-facing serialization and error mapping."""

from __future__ import annotations

import json
from decimal import Decimal
import sqlite3
import tempfile
from pathlib import Path
from textwrap import dedent

from tests.common import RepoSmokeTestCase
from mtg_source_stack.api.app import create_app
from mtg_source_stack.api.dependencies import ApiSettings
from mtg_source_stack.api_contract import api_error_payload, api_error_status
from mtg_source_stack.api.request_models import (
    AddInventoryItemRequest,
    BulkInventoryItemMutationRequest,
    DecklistImportRequest,
    DeckUrlImportRequest,
    PatchInventoryItemRequest,
)
from mtg_source_stack.api.response_models import (
    ApiErrorResponse,
    BulkInventoryItemMutationResponse,
    CatalogNameSearchRowResponse,
    CatalogSearchRowResponse,
    CsvImportResponse,
    DecklistImportResponse,
    DeckUrlImportResponse,
    DefaultInventoryBootstrapResponse,
    OwnedInventoryRowResponse,
    SetAcquisitionResponse,
    SetFinishResponse,
)
from mtg_source_stack.db.schema import initialize_database, require_current_schema
from mtg_source_stack.errors import ConflictError, NotFoundError, SchemaNotReadyError, ValidationError
from mtg_source_stack.inventory.response_models import serialize_response
from mtg_source_stack.inventory.service import (
    create_inventory,
    list_card_printings_for_oracle,
    list_inventory_audit_events,
    list_owned_filtered,
    reconcile_prices,
    search_card_names,
    search_cards,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_SNAPSHOT_PATH = REPO_ROOT / "contracts" / "openapi.json"
OPENAPI_SNAPSHOT_REFRESH_COMMAND = dedent(
    """\
    PYTHONPATH=src python3 - <<'PY'
    import json
    from pathlib import Path
    from mtg_source_stack.api.app import create_app
    from mtg_source_stack.api.dependencies import ApiSettings

    app = create_app(
        ApiSettings(
            db_path=Path("var/db/mtg_mvp.db"),
            runtime_mode="local_demo",
            auto_migrate=True,
            host="127.0.0.1",
            port=8000,
        )
    )

    Path("contracts/openapi.json").write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\\n"
    )
    PY
    """
)


def _render_live_openapi_snapshot() -> str:
    app = create_app(
        ApiSettings(
            db_path=REPO_ROOT / "var/db" / "mtg_mvp.db",
            runtime_mode="local_demo",
            auto_migrate=True,
            host="127.0.0.1",
            port=8000,
        )
    )
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


class ApiContractTest(RepoSmokeTestCase):
    def test_openapi_snapshot_matches_live_app(self) -> None:
        self.maxDiff = None
        self.assertMultiLineEqual(
            OPENAPI_SNAPSHOT_PATH.read_text(encoding="utf-8"),
            _render_live_openapi_snapshot(),
            "contracts/openapi.json is out of date. Regenerate the enforced OpenAPI snapshot with:\n\n"
            f"{OPENAPI_SNAPSHOT_REFRESH_COMMAND}",
        )

    def test_serialize_response_uses_decimal_strings_and_nulls(self) -> None:
        payload = {
            "price": Decimal("2.50"),
            "missing_price": None,
            "nested": [Decimal("1.00"), None],
        }

        self.assertEqual(
            {
                "price": "2.50",
                "missing_price": None,
                "nested": ["1.00", None],
            },
            serialize_response(payload),
        )

    def test_api_error_helpers_map_domain_errors(self) -> None:
        exc = ConflictError("Inventory already exists.")

        self.assertEqual(409, api_error_status(exc))
        self.assertEqual(
            {
                "error": {
                    "code": "conflict",
                    "message": "Inventory already exists.",
                }
            },
            api_error_payload(exc),
        )

    def test_api_error_helpers_map_not_found_and_validation_errors(self) -> None:
        missing = NotFoundError("Inventory row was not found.")
        invalid = ValidationError("Finish must be one of: normal, foil, etched.")

        self.assertEqual(404, api_error_status(missing))
        self.assertEqual(
            {
                "error": {
                    "code": "not_found",
                    "message": "Inventory row was not found.",
                }
            },
            api_error_payload(missing),
        )

        self.assertEqual(400, api_error_status(invalid))
        self.assertEqual(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Finish must be one of: normal, foil, etched.",
                }
            },
            api_error_payload(invalid),
        )

    def test_api_error_helpers_hide_internal_exception_messages(self) -> None:
        exc = RuntimeError("sqlite blew up")

        self.assertEqual(500, api_error_status(exc))
        self.assertEqual(
            {
                "error": {
                    "code": "internal_error",
                    "message": "Internal server error.",
                }
            },
            api_error_payload(exc),
        )

    def test_api_response_models_match_serialized_http_shapes(self) -> None:
        owned_payload = serialize_response(
            {
                "item_id": 1,
                "scryfall_id": "card-1",
                "name": "Lightning Bolt",
                "set_code": "lea",
                "set_name": "Limited Edition Alpha",
                "rarity": "common",
                "collector_number": "161",
                "image_uri_small": "https://example.test/cards/card-1-small.jpg",
                "image_uri_normal": "https://example.test/cards/card-1-normal.jpg",
                "quantity": 4,
                "condition_code": "NM",
                "finish": "normal",
                "allowed_finishes": ["normal", "foil"],
                "language_code": "en",
                "location": None,
                "tags": ["burn", "trade"],
                "acquisition_price": Decimal("2.50"),
                "acquisition_currency": "USD",
                "currency": None,
                "unit_price": Decimal("3.00"),
                "est_value": Decimal("12.00"),
                "price_date": None,
                "notes": None,
            }
        )
        catalog_payload = {
            "scryfall_id": "card-1",
            "name": "Lightning Bolt",
            "set_code": "lea",
            "set_name": "Limited Edition Alpha",
            "collector_number": "161",
            "lang": "en",
            "rarity": "common",
            "finishes": ["normal", "foil"],
            "tcgplayer_product_id": None,
            "image_uri_small": "https://example.test/cards/card-1-small.jpg",
            "image_uri_normal": "https://example.test/cards/card-1-normal.jpg",
        }
        catalog_name_payload = {
            "oracle_id": "oracle-lightning-bolt",
            "name": "Lightning Bolt",
            "printings_count": 27,
            "available_languages": ["en", "ja", "de"],
            "image_uri_small": "https://example.test/cards/card-1-small.jpg",
            "image_uri_normal": "https://example.test/cards/card-1-normal.jpg",
        }
        bootstrap_payload = {
            "created": True,
            "inventory": {
                "inventory_id": 7,
                "slug": "alice-collection",
                "display_name": "Collection",
                "description": None,
            },
        }
        csv_import_payload = {
            "csv_filename": "inventory_import.csv",
            "detected_format": "generic_csv",
            "default_inventory": "personal",
            "rows_seen": 1,
            "rows_written": 1,
            "summary": {
                "total_card_quantity": 4,
                "distinct_card_names": 1,
                "distinct_printings": 1,
            },
            "dry_run": True,
            "imported_rows": [
                {
                    "csv_row": 2,
                    "inventory": "personal",
                    "card_name": "Lightning Bolt",
                    "set_code": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "scryfall_id": "card-1",
                    "item_id": 1,
                    "quantity": 4,
                    "finish": "normal",
                    "condition_code": "NM",
                    "language_code": "en",
                    "location": None,
                    "acquisition_price": None,
                    "acquisition_currency": None,
                    "notes": None,
                    "tags": [],
                }
            ],
        }
        decklist_import_payload = {
            "deck_name": None,
            "default_inventory": "personal",
            "rows_seen": 1,
            "rows_written": 1,
            "ready_to_commit": True,
            "summary": {
                "total_card_quantity": 4,
                "distinct_card_names": 1,
                "distinct_printings": 1,
                "section_card_quantities": {"mainboard": 4},
                "requested_card_quantity": 4,
                "unresolved_card_quantity": 0,
            },
            "resolution_issues": [],
            "dry_run": True,
            "imported_rows": [
                {
                    "decklist_line": 1,
                    "section": "mainboard",
                    "inventory": "personal",
                    "card_name": "Lightning Bolt",
                    "set_code": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "scryfall_id": "card-1",
                    "item_id": 1,
                    "quantity": 4,
                    "finish": "normal",
                    "condition_code": "NM",
                    "language_code": "en",
                    "location": None,
                    "acquisition_price": None,
                    "acquisition_currency": None,
                    "notes": None,
                    "tags": [],
                }
            ],
        }
        deck_url_import_payload = {
            "source_url": "https://archidekt.com/decks/123/test",
            "provider": "archidekt",
            "deck_name": "Imported Deck",
            "default_inventory": "personal",
            "rows_seen": 1,
            "rows_written": 1,
            "summary": {
                "total_card_quantity": 1,
                "distinct_card_names": 1,
                "distinct_printings": 1,
                "section_card_quantities": {"commander": 1},
            },
            "dry_run": True,
            "imported_rows": [
                {
                    "section": "commander",
                    "inventory": "personal",
                    "card_name": "Lightning Bolt",
                    "set_code": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "scryfall_id": "card-1",
                    "item_id": 1,
                    "quantity": 1,
                    "finish": "normal",
                    "condition_code": "NM",
                    "language_code": "en",
                    "location": None,
                    "acquisition_price": None,
                    "acquisition_currency": None,
                    "notes": None,
                    "tags": [],
                }
            ],
        }
        error_payload = api_error_payload(ValidationError("Bad request."))

        owned = OwnedInventoryRowResponse.model_validate(owned_payload)
        catalog = CatalogSearchRowResponse.model_validate(catalog_payload)
        catalog_name = CatalogNameSearchRowResponse.model_validate(catalog_name_payload)
        bootstrap = DefaultInventoryBootstrapResponse.model_validate(bootstrap_payload)
        csv_import = CsvImportResponse.model_validate(csv_import_payload)
        decklist_import = DecklistImportResponse.model_validate(decklist_import_payload)
        deck_url_import = DeckUrlImportResponse.model_validate(deck_url_import_payload)
        error = ApiErrorResponse.model_validate(error_payload)

        self.assertEqual("2.50", owned.acquisition_price)
        self.assertEqual("3.00", owned.unit_price)
        self.assertEqual("https://example.test/cards/card-1-small.jpg", owned.image_uri_small)
        self.assertEqual(["normal", "foil"], owned.allowed_finishes)
        self.assertIsNone(owned.price_date)
        self.assertEqual(["normal", "foil"], catalog.finishes)
        self.assertEqual("https://example.test/cards/card-1-normal.jpg", catalog.image_uri_normal)
        self.assertEqual(["en", "ja", "de"], catalog_name.available_languages)
        self.assertTrue(bootstrap.created)
        self.assertEqual("Collection", bootstrap.inventory.display_name)
        self.assertEqual("generic_csv", csv_import.detected_format)
        self.assertEqual(4, csv_import.summary.total_card_quantity)
        self.assertEqual(2, csv_import.imported_rows[0].csv_row)
        self.assertTrue(decklist_import.ready_to_commit)
        self.assertEqual({"mainboard": 4}, decklist_import.summary.section_card_quantities)
        self.assertEqual(4, decklist_import.summary.requested_card_quantity)
        self.assertEqual(0, decklist_import.summary.unresolved_card_quantity)
        self.assertEqual("mainboard", decklist_import.imported_rows[0].section)
        self.assertEqual(1, decklist_import.imported_rows[0].decklist_line)
        self.assertEqual("archidekt", deck_url_import.provider)
        self.assertEqual({"commander": 1}, deck_url_import.summary.section_card_quantities)
        self.assertEqual("commander", deck_url_import.imported_rows[0].section)
        self.assertEqual("validation_error", error.error.code)

    def test_api_models_publish_defaults_and_canonical_value_guidance(self) -> None:
        add_schema = AddInventoryItemRequest.model_json_schema()
        add_properties = add_schema["properties"]

        self.assertEqual("normal", add_properties["finish"]["default"])
        self.assertEqual(["normal", "nonfoil", "foil", "etched"], add_properties["finish"]["enum"])
        self.assertIn("Canonical response values: normal, foil, etched", add_properties["finish"]["description"])
        self.assertEqual("NM", add_properties["condition_code"]["default"])
        self.assertIn("Canonical condition codes: M, NM, LP, MP, HP, DMG", add_properties["condition_code"]["description"])
        self.assertIsNone(add_properties["language_code"]["default"])
        self.assertIn("inherits the resolved printing language", add_properties["language_code"]["description"])
        self.assertEqual({"type": "string"}, add_properties["oracle_id"]["anyOf"][0])
        self.assertIn("prefers English mainstream-paper printings", add_properties["oracle_id"]["description"])

        decklist_schema = DecklistImportRequest.model_json_schema()
        decklist_properties = decklist_schema["properties"]
        self.assertEqual(False, decklist_properties["dry_run"]["default"])
        self.assertIn("4 Lightning Bolt", decklist_properties["deck_text"]["description"])
        self.assertIn("About", decklist_properties["deck_text"]["description"])
        self.assertIn("Target inventory slug", decklist_properties["default_inventory"]["description"])
        self.assertEqual("array", decklist_properties["resolutions"]["type"])
        self.assertIn("explicit row resolutions", decklist_properties["resolutions"]["description"])

        deck_url_schema = DeckUrlImportRequest.model_json_schema()
        deck_url_properties = deck_url_schema["properties"]
        self.assertEqual(False, deck_url_properties["dry_run"]["default"])
        self.assertIn("Archidekt", deck_url_properties["source_url"]["description"])
        self.assertIn("AetherHub", deck_url_properties["source_url"]["description"])
        self.assertIn("ManaBox", deck_url_properties["source_url"]["description"])
        self.assertIn("Moxfield", deck_url_properties["source_url"]["description"])
        self.assertIn("MTGGoldfish", deck_url_properties["source_url"]["description"])
        self.assertIn("MTGTop8", deck_url_properties["source_url"]["description"])
        self.assertIn("TappedOut", deck_url_properties["source_url"]["description"])
        self.assertIn("Target inventory slug", deck_url_properties["default_inventory"]["description"])

        owned_schema = OwnedInventoryRowResponse.model_json_schema()
        owned_properties = owned_schema["properties"]
        self.assertEqual(["normal", "foil", "etched"], owned_properties["finish"]["enum"])
        self.assertEqual(["normal", "foil", "etched"], owned_properties["allowed_finishes"]["items"]["enum"])
        self.assertIn("Canonical condition codes: M, NM, LP, MP, HP, DMG", owned_properties["condition_code"]["description"])
        self.assertIn("Canonical language codes: en, ja, de, fr", owned_properties["language_code"]["description"])

        catalog_schema = CatalogSearchRowResponse.model_json_schema()
        catalog_properties = catalog_schema["properties"]
        self.assertEqual(
            ["normal", "foil", "etched"],
            catalog_properties["finishes"]["items"]["enum"],
        )
        self.assertIn("Catalog language code", catalog_properties["lang"]["description"])

        catalog_name_schema = CatalogNameSearchRowResponse.model_json_schema()
        catalog_name_properties = catalog_name_schema["properties"]
        self.assertEqual("array", catalog_name_properties["available_languages"]["type"])
        self.assertEqual("string", catalog_name_properties["available_languages"]["items"]["type"])
        self.assertIn(
            "Catalog language codes available for the matched card",
            catalog_name_properties["available_languages"]["description"],
        )

        bulk_schema = BulkInventoryItemMutationRequest.model_json_schema()
        bulk_properties = bulk_schema["properties"]
        self.assertIn("supports only tag operations", bulk_schema["description"])
        self.assertEqual(
            ["add_tags", "remove_tags", "set_tags", "clear_tags"],
            bulk_properties["operation"]["enum"],
        )
        self.assertEqual(1, bulk_properties["item_ids"]["minItems"])
        self.assertEqual(100, bulk_properties["item_ids"]["maxItems"])
        self.assertIn("Omit this field for clear_tags", bulk_properties["tags"]["description"])

        bulk_response = BulkInventoryItemMutationResponse.model_validate(
            {
                "inventory": "personal",
                "operation": "add_tags",
                "requested_item_ids": [12, 27, 44],
                "updated_item_ids": [12, 44],
                "updated_count": 2,
            }
        )
        self.assertEqual("add_tags", bulk_response.operation)
        self.assertEqual([12, 44], bulk_response.updated_item_ids)

    def test_patch_contract_publishes_single_operation_rule_and_discriminator(self) -> None:
        patch_schema = PatchInventoryItemRequest.model_json_schema()
        patch_properties = patch_schema["properties"]

        self.assertIn("exactly one mutation family", patch_schema["description"])
        self.assertIn("Only applies to location or condition changes", patch_properties["merge"]["description"])
        self.assertIn(
            "Only applies to merged location or condition changes",
            patch_properties["keep_acquisition"]["description"],
        )

        finish_response_schema = SetFinishResponse.model_json_schema()
        finish_operation = finish_response_schema["properties"]["operation"]
        self.assertEqual("set_finish", finish_operation.get("const", finish_operation.get("enum", [None])[0]))

        acquisition_response = SetAcquisitionResponse.model_validate(
            {
                "operation": "set_acquisition",
                "inventory": "personal",
                "card_name": "Sol Ring",
                "set_code": "cmd",
                "set_name": "Commander",
                "collector_number": "260",
                "scryfall_id": "demo-sol-ring",
                "item_id": 15,
                "quantity": 1,
                "finish": "foil",
                "condition_code": "NM",
                "language_code": "en",
                "location": "Artifacts Binder",
                "acquisition_price": "3.50",
                "acquisition_currency": "USD",
                "notes": None,
                "tags": ["commander", "artifact"],
                "old_acquisition_price": None,
                "old_acquisition_currency": None,
            }
        )
        self.assertEqual("set_acquisition", acquisition_response.operation)

    def test_create_inventory_conflict_raises_conflict_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "collection.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
            )

            with self.assertRaises(ConflictError):
                create_inventory(
                    db_path,
                    slug="personal",
                    display_name="Duplicate",
                    description=None,
                )

    def test_reconcile_prices_apply_raises_validation_error(self) -> None:
        with self.assertRaises(ValidationError):
            reconcile_prices(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                apply_changes=True,
            )

    def test_limit_validation_errors_map_to_bad_request(self) -> None:
        service_calls = [
            lambda: search_cards(Path("var/db/not-used.db"), query="bolt", limit=0),
            lambda: search_cards(Path("var/db/not-used.db"), query="bolt", limit=-1),
            lambda: search_cards(Path("var/db/not-used.db"), query="", limit=10),
            lambda: search_cards(Path("var/db/not-used.db"), query="   ", limit=10),
            lambda: search_cards(Path("var/db/not-used.db"), query="bolt", scope="weird", limit=10),
            lambda: search_card_names(Path("var/db/not-used.db"), query="", limit=10),
            lambda: search_card_names(Path("var/db/not-used.db"), query="bolt", scope="weird", limit=10),
            lambda: list_card_printings_for_oracle(Path("var/db/not-used.db"), "oracle-1", scope="weird"),
            lambda: list_owned_filtered(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                limit=-1,
                query=None,
                set_code=None,
                rarity=None,
                finish=None,
                condition_code=None,
                language_code=None,
                location=None,
                tags=None,
            ),
            lambda: list_inventory_audit_events(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                limit=-1,
            ),
        ]

        for service_call in service_calls:
            with self.assertRaises(ValidationError) as caught:
                service_call()
            self.assertEqual(400, api_error_status(caught.exception))
            self.assertEqual("validation_error", api_error_payload(caught.exception)["error"]["code"])

    def test_require_current_schema_raises_schema_not_ready_for_unmigrated_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "unmigrated.db"
            sqlite3.connect(db_path).close()

            with self.assertRaises(SchemaNotReadyError):
                require_current_schema(db_path)
