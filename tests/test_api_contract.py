"""Contract-focused tests for API-facing serialization and error mapping."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
import tempfile
from pathlib import Path

from tests.common import RepoSmokeTestCase
from mtg_source_stack.api_contract import api_error_payload, api_error_status
from mtg_source_stack.api.request_models import AddInventoryItemRequest
from mtg_source_stack.api.response_models import (
    ApiErrorResponse,
    CatalogSearchRowResponse,
    OwnedInventoryRowResponse,
)
from mtg_source_stack.db.schema import initialize_database, require_current_schema
from mtg_source_stack.errors import ConflictError, NotFoundError, SchemaNotReadyError, ValidationError
from mtg_source_stack.inventory.response_models import serialize_response
from mtg_source_stack.inventory.service import (
    create_inventory,
    list_inventory_audit_events,
    list_owned_filtered,
    reconcile_prices,
    search_cards,
)


class ApiContractTest(RepoSmokeTestCase):
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
        error_payload = api_error_payload(ValidationError("Bad request."))

        owned = OwnedInventoryRowResponse.model_validate(owned_payload)
        catalog = CatalogSearchRowResponse.model_validate(catalog_payload)
        error = ApiErrorResponse.model_validate(error_payload)

        self.assertEqual("2.50", owned.acquisition_price)
        self.assertEqual("3.00", owned.unit_price)
        self.assertEqual("https://example.test/cards/card-1-small.jpg", owned.image_uri_small)
        self.assertIsNone(owned.price_date)
        self.assertEqual(["normal", "foil"], catalog.finishes)
        self.assertEqual("https://example.test/cards/card-1-normal.jpg", catalog.image_uri_normal)
        self.assertEqual("validation_error", error.error.code)

    def test_api_models_publish_defaults_and_canonical_value_guidance(self) -> None:
        add_schema = AddInventoryItemRequest.model_json_schema()
        add_properties = add_schema["properties"]

        self.assertEqual("normal", add_properties["finish"]["default"])
        self.assertEqual(["normal", "nonfoil", "foil", "etched"], add_properties["finish"]["enum"])
        self.assertIn("Canonical response values: normal, foil, etched", add_properties["finish"]["description"])
        self.assertEqual("NM", add_properties["condition_code"]["default"])
        self.assertIn("Canonical condition codes: M, NM, LP, MP, HP, DMG", add_properties["condition_code"]["description"])
        self.assertEqual("en", add_properties["language_code"]["default"])
        self.assertIn("Canonical language codes: en, ja, de, fr", add_properties["language_code"]["description"])

        owned_schema = OwnedInventoryRowResponse.model_json_schema()
        owned_properties = owned_schema["properties"]
        self.assertEqual(["normal", "foil", "etched"], owned_properties["finish"]["enum"])
        self.assertIn("Canonical condition codes: M, NM, LP, MP, HP, DMG", owned_properties["condition_code"]["description"])
        self.assertIn("Canonical language codes: en, ja, de, fr", owned_properties["language_code"]["description"])

        catalog_schema = CatalogSearchRowResponse.model_json_schema()
        catalog_properties = catalog_schema["properties"]
        self.assertEqual(
            ["normal", "foil", "etched"],
            catalog_properties["finishes"]["items"]["enum"],
        )
        self.assertIn("Catalog language code", catalog_properties["lang"]["description"])

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
