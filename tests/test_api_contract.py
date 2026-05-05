"""Contract-focused tests for API-facing serialization and error mapping."""

from __future__ import annotations

import json
from decimal import Decimal
import sqlite3
import tempfile
import unittest
from pathlib import Path
from textwrap import dedent

from tests.common import RepoSmokeTestCase
from tests.optional_dependencies import (
    WEB_TEST_SKIP_REASON,
    web_test_dependencies_available,
)

if not web_test_dependencies_available():
    raise unittest.SkipTest(WEB_TEST_SKIP_REASON)

from mtg_source_stack.api.app import create_app
from mtg_source_stack.api.dependencies import ApiSettings
from mtg_source_stack.api_contract import api_error_payload, api_error_status
from mtg_source_stack.api.request_models import (
    AddInventoryItemRequest,
    BulkInventoryItemMutationRequest,
    BulkItemsSelectionRequest,
    DecklistImportRequest,
    DeckUrlImportRequest,
    InventoryCreateRequest,
    InventoryDuplicateRequest,
    InventoryMembershipGrantRequest,
    InventoryMembershipUpdateRequest,
    InventoryTransferRequest,
    PatchInventoryItemRequest,
    SetInventoryItemPrintingRequest,
)
from mtg_source_stack.api.response_models import (
    AddInventoryItemResponse,
    ApiErrorResponse,
    BulkInventoryItemMutationResponse,
    CatalogNameSearchResponse,
    CatalogNameSearchRowResponse,
    CatalogPrintingLookupRowResponse,
    CatalogPrintingSummaryResponse,
    CatalogSearchRowResponse,
    CsvImportResponse,
    DecklistImportResponse,
    DeckUrlImportResponse,
    DefaultInventoryBootstrapResponse,
    InventoryCreateResponse,
    InventoryDuplicateResponse,
    InventoryListRowResponse,
    InventoryMembershipRemovalResponse,
    InventoryMembershipResponse,
    InventoryShareLinkStatusResponse,
    InventoryShareLinkTokenResponse,
    InventoryTransferResponse,
    OwnedInventoryItemsPageResponse,
    OwnedInventoryRowResponse,
    PublicInventoryShareResponse,
    RemoveInventoryItemResponse,
    SetAcquisitionResponse,
    SetConditionResponse,
    SetFinishResponse,
    SetLocationResponse,
    SetNotesResponse,
    SetPrintingResponse,
    SetQuantityResponse,
    SetTagsResponse,
)
from mtg_source_stack.db.schema import initialize_database, require_current_schema
from mtg_source_stack.errors import ConflictError, NotFoundError, SchemaNotReadyError, ValidationError
from mtg_source_stack.inventory.response_models import serialize_response
from mtg_source_stack.inventory.service import (
    create_inventory,
    list_card_printings_for_oracle,
    list_inventory_audit_events,
    list_owned_filtered,
    list_owned_filtered_page,
    reconcile_prices,
    search_card_names,
    search_cards,
    summarize_card_printings_for_oracle,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI_SNAPSHOT_PATH = REPO_ROOT / "contracts" / "openapi.json"
DEMO_PAYLOADS_DIR = REPO_ROOT / "contracts" / "demo_payloads"
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
                "oracle_id": "oracle-lightning-bolt",
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
                "printing_selection_mode": "explicit",
            }
        )
        owned_page_payload = {
            "inventory": "personal",
            "items": [owned_payload],
            "total_count": 1,
            "limit": 50,
            "offset": 0,
            "has_more": False,
            "sort_key": "name",
            "sort_direction": "asc",
        }
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
        printing_lookup_payload = {
            **catalog_payload,
            "is_default_add_choice": True,
        }
        printing_summary_payload = {
            "oracle_id": "oracle-lightning-bolt",
            "default_printing": printing_lookup_payload,
            "available_languages": ["en", "ja"],
            "printings_count": 2,
            "has_more_printings": True,
            "printings": [printing_lookup_payload],
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
                "default_location": None,
                "default_tags": None,
                "notes": None,
                "acquisition_price": None,
                "acquisition_currency": None,
            },
        }
        inventory_create_payload = {
            "inventory_id": 7,
            "slug": "alice-collection",
            "display_name": "Collection",
            "description": "Main inventory",
            "default_location": "Binder A",
            "default_tags": "modern, staples",
            "notes": "Main trade stock",
            "acquisition_price": "42.50",
            "acquisition_currency": "USD",
        }
        inventory_list_payload = [
            {
                "slug": "alice-collection",
                "display_name": "Collection",
                "description": "Main inventory",
                "default_location": "Binder A",
                "default_tags": "modern, staples",
                "notes": "Main trade stock",
                "acquisition_price": "42.50",
                "acquisition_currency": "USD",
                "item_rows": 12,
                "total_cards": 45,
                "role": "owner",
                "can_read": True,
                "can_write": True,
                "can_manage_share": True,
                "can_transfer_to": True,
            }
        ]
        membership_payload = {
            "inventory": "alice-collection",
            "actor_id": "viewer@example.com",
            "role": "viewer",
            "created_at": "2026-04-21 12:00:00",
            "updated_at": "2026-04-21 12:00:00",
        }
        membership_removal_payload = {
            "inventory": "alice-collection",
            "actor_id": "viewer@example.com",
            "role": "viewer",
        }
        share_link_status_payload = {
            "inventory": "alice-collection",
            "active": False,
            "public_path": None,
            "created_at": None,
            "updated_at": None,
            "revoked_at": None,
        }
        share_link_token_payload = {
            "inventory": "alice-collection",
            "token": "public-token",
            "public_path": "/shared/inventories/public-token",
            "active": True,
            "created_at": "2026-04-21 12:00:00",
            "updated_at": "2026-04-21 12:00:00",
            "revoked_at": None,
        }
        public_share_payload = {
            "inventory": {
                "display_name": "Collection",
                "description": "Shared view",
                "item_rows": 1,
                "total_cards": 4,
            },
            "items": [
                {
                    "scryfall_id": "card-1",
                    "oracle_id": "oracle-lightning-bolt",
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
                }
            ],
        }
        csv_import_payload = {
            "csv_filename": "inventory_import.csv",
            "detected_format": "generic_csv",
            "default_inventory": "personal",
            "rows_seen": 1,
            "rows_written": 1,
            "ready_to_commit": True,
            "summary": {
                "total_card_quantity": 4,
                "distinct_card_names": 1,
                "distinct_printings": 1,
                "requested_card_quantity": 4,
                "unresolved_card_quantity": 0,
            },
            "resolution_issues": [],
            "dry_run": True,
            "imported_rows": [
                {
                    "csv_row": 2,
                    "inventory": "personal",
                    "card_name": "Lightning Bolt",
                    "oracle_id": "oracle-lightning-bolt",
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
                    "printing_selection_mode": "explicit",
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
                    "oracle_id": "oracle-lightning-bolt",
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
                    "printing_selection_mode": "explicit",
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
            "ready_to_commit": True,
            "source_snapshot_token": "snapshot-token",
            "summary": {
                "total_card_quantity": 1,
                "distinct_card_names": 1,
                "distinct_printings": 1,
                "section_card_quantities": {"commander": 1},
                "requested_card_quantity": 1,
                "unresolved_card_quantity": 0,
            },
            "resolution_issues": [],
            "dry_run": True,
            "imported_rows": [
                {
                    "source_position": 1,
                    "section": "commander",
                    "inventory": "personal",
                    "card_name": "Lightning Bolt",
                    "oracle_id": "oracle-lightning-bolt",
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
                    "printing_selection_mode": "explicit",
                }
            ],
        }
        error_payload = api_error_payload(ValidationError("Bad request."))

        owned = OwnedInventoryRowResponse.model_validate(owned_payload)
        owned_page = OwnedInventoryItemsPageResponse.model_validate(owned_page_payload)
        catalog = CatalogSearchRowResponse.model_validate(catalog_payload)
        printing_lookup = CatalogPrintingLookupRowResponse.model_validate(printing_lookup_payload)
        printing_summary = CatalogPrintingSummaryResponse.model_validate(printing_summary_payload)
        catalog_name = CatalogNameSearchRowResponse.model_validate(catalog_name_payload)
        catalog_name_result = CatalogNameSearchResponse.model_validate(
            {
                "items": [catalog_name_payload],
                "total_count": 1,
                "has_more": False,
            }
        )
        inventory_create = InventoryCreateResponse.model_validate(inventory_create_payload)
        inventory_list = [InventoryListRowResponse.model_validate(row) for row in inventory_list_payload]
        membership = InventoryMembershipResponse.model_validate(membership_payload)
        membership_removal = InventoryMembershipRemovalResponse.model_validate(membership_removal_payload)
        share_link_status = InventoryShareLinkStatusResponse.model_validate(share_link_status_payload)
        share_link_token = InventoryShareLinkTokenResponse.model_validate(share_link_token_payload)
        public_share = PublicInventoryShareResponse.model_validate(public_share_payload)
        bootstrap = DefaultInventoryBootstrapResponse.model_validate(bootstrap_payload)
        csv_import = CsvImportResponse.model_validate(csv_import_payload)
        decklist_import = DecklistImportResponse.model_validate(decklist_import_payload)
        deck_url_import = DeckUrlImportResponse.model_validate(deck_url_import_payload)
        error = ApiErrorResponse.model_validate(error_payload)

        self.assertEqual("2.50", owned.acquisition_price)
        self.assertEqual("oracle-lightning-bolt", owned.oracle_id)
        self.assertEqual("3.00", owned.unit_price)
        self.assertEqual("https://example.test/cards/card-1-small.jpg", owned.image_uri_small)
        self.assertEqual(["normal", "foil"], owned.allowed_finishes)
        self.assertEqual("explicit", owned.printing_selection_mode)
        self.assertIsNone(owned.price_date)
        self.assertEqual(1, owned_page.total_count)
        self.assertFalse(owned_page.has_more)
        self.assertEqual("name", owned_page.sort_key)
        self.assertEqual("Lightning Bolt", owned_page.items[0].name)
        self.assertEqual(["normal", "foil"], catalog.finishes)
        self.assertEqual("https://example.test/cards/card-1-normal.jpg", catalog.image_uri_normal)
        self.assertTrue(printing_lookup.is_default_add_choice)
        self.assertEqual("oracle-lightning-bolt", printing_summary.oracle_id)
        self.assertIsNotNone(printing_summary.default_printing)
        self.assertEqual("card-1", printing_summary.default_printing.scryfall_id)
        self.assertEqual(2, printing_summary.printings_count)
        self.assertTrue(printing_summary.has_more_printings)
        self.assertEqual(["en", "ja", "de"], catalog_name.available_languages)
        self.assertEqual(1, catalog_name_result.total_count)
        self.assertFalse(catalog_name_result.has_more)
        self.assertEqual("Binder A", inventory_create.default_location)
        self.assertEqual("modern, staples", inventory_create.default_tags)
        self.assertEqual("42.50", inventory_create.acquisition_price)
        self.assertEqual("USD", inventory_create.acquisition_currency)
        self.assertEqual("Main trade stock", inventory_list[0].notes)
        self.assertEqual(45, inventory_list[0].total_cards)
        self.assertEqual("viewer@example.com", membership.actor_id)
        self.assertEqual("viewer", membership.role)
        self.assertEqual("viewer@example.com", membership_removal.actor_id)
        self.assertFalse(share_link_status.active)
        self.assertEqual("/shared/inventories/public-token", share_link_token.public_path)
        self.assertEqual("Collection", public_share.inventory.display_name)
        self.assertEqual("Lightning Bolt", public_share.items[0].name)
        self.assertTrue(bootstrap.created)
        self.assertEqual("Collection", bootstrap.inventory.display_name)
        self.assertEqual("generic_csv", csv_import.detected_format)
        self.assertTrue(csv_import.ready_to_commit)
        self.assertEqual(4, csv_import.summary.total_card_quantity)
        self.assertEqual(4, csv_import.summary.requested_card_quantity)
        self.assertEqual(0, csv_import.summary.unresolved_card_quantity)
        self.assertEqual(2, csv_import.imported_rows[0].csv_row)
        self.assertTrue(decklist_import.ready_to_commit)
        self.assertEqual({"mainboard": 4}, decklist_import.summary.section_card_quantities)
        self.assertEqual(4, decklist_import.summary.requested_card_quantity)
        self.assertEqual(0, decklist_import.summary.unresolved_card_quantity)
        self.assertEqual("mainboard", decklist_import.imported_rows[0].section)
        self.assertEqual(1, decklist_import.imported_rows[0].decklist_line)
        self.assertEqual("archidekt", deck_url_import.provider)
        self.assertTrue(deck_url_import.ready_to_commit)
        self.assertEqual({"commander": 1}, deck_url_import.summary.section_card_quantities)
        self.assertEqual(1, deck_url_import.summary.requested_card_quantity)
        self.assertEqual(0, deck_url_import.summary.unresolved_card_quantity)
        self.assertEqual("snapshot-token", deck_url_import.source_snapshot_token)
        self.assertEqual(1, deck_url_import.imported_rows[0].source_position)
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
        self.assertIsNone(add_properties["location"]["default"])
        membership_grant_schema = InventoryMembershipGrantRequest.model_json_schema()
        membership_update_schema = InventoryMembershipUpdateRequest.model_json_schema()
        self.assertEqual(["viewer", "editor", "owner"], membership_grant_schema["properties"]["role"]["enum"])
        self.assertEqual(["viewer", "editor", "owner"], membership_update_schema["properties"]["role"]["enum"])
        self.assertIn("inherits the resolved printing language", add_properties["language_code"]["description"])
        self.assertEqual({"type": "string"}, add_properties["oracle_id"]["anyOf"][0])
        self.assertIn("prefers English mainstream-paper printings", add_properties["oracle_id"]["description"])

        inventory_create_schema = InventoryCreateRequest.model_json_schema()
        inventory_create_properties = inventory_create_schema["properties"]
        self.assertEqual("string", inventory_create_properties["slug"]["type"])
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_properties["default_location"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_properties["default_tags"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_properties["notes"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_properties["acquisition_price"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_properties["acquisition_currency"]["anyOf"],
        )

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
        self.assertEqual("array", deck_url_properties["resolutions"]["type"])
        self.assertIn("normalized remote deck payload", deck_url_properties["source_snapshot_token"]["description"])

        owned_schema = OwnedInventoryRowResponse.model_json_schema()
        owned_properties = owned_schema["properties"]
        self.assertEqual("string", owned_properties["oracle_id"]["type"])
        self.assertEqual(["normal", "foil", "etched"], owned_properties["finish"]["enum"])
        self.assertEqual(["normal", "foil", "etched"], owned_properties["allowed_finishes"]["items"]["enum"])
        self.assertIn("Canonical condition codes: M, NM, LP, MP, HP, DMG", owned_properties["condition_code"]["description"])
        self.assertIn("Canonical language codes: en, ja, de, fr", owned_properties["language_code"]["description"])
        self.assertEqual(["explicit", "defaulted"], owned_properties["printing_selection_mode"]["enum"])

        inventory_list_schema = InventoryListRowResponse.model_json_schema()
        inventory_list_properties = inventory_list_schema["properties"]
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_list_properties["default_location"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_list_properties["default_tags"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_list_properties["notes"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_list_properties["acquisition_price"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_list_properties["acquisition_currency"]["anyOf"],
        )
        self.assertEqual(
            [
                {"enum": ["viewer", "editor", "owner", "admin"], "type": "string"},
                {"type": "null"},
            ],
            inventory_list_properties["role"]["anyOf"],
        )
        self.assertEqual("boolean", inventory_list_properties["can_read"]["type"])
        self.assertEqual("boolean", inventory_list_properties["can_write"]["type"])
        self.assertEqual("boolean", inventory_list_properties["can_manage_share"]["type"])
        self.assertEqual("boolean", inventory_list_properties["can_transfer_to"]["type"])

        inventory_create_response_schema = InventoryCreateResponse.model_json_schema()
        inventory_create_response_properties = inventory_create_response_schema["properties"]
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_response_properties["default_location"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_response_properties["default_tags"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_response_properties["notes"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_response_properties["acquisition_price"]["anyOf"],
        )
        self.assertEqual(
            [{"type": "string"}, {"type": "null"}],
            inventory_create_response_properties["acquisition_currency"]["anyOf"],
        )

        set_finish_schema = SetFinishResponse.model_json_schema()
        self.assertEqual("string", set_finish_schema["properties"]["oracle_id"]["type"])
        self.assertEqual(
            ["explicit", "defaulted"],
            set_finish_schema["properties"]["printing_selection_mode"]["enum"],
        )
        set_printing_request_schema = SetInventoryItemPrintingRequest.model_json_schema()
        self.assertIn(
            "different printing of the same oracle card",
            set_printing_request_schema["description"],
        )
        self.assertIn(
            "confirm a defaulted row as explicit",
            set_printing_request_schema["description"],
        )
        self.assertIn(
            "normal > foil > etched",
            set_printing_request_schema["properties"]["finish"]["description"],
        )
        self.assertIn(
            "confirmation-only",
            set_printing_request_schema["properties"]["finish"]["description"],
        )
        self.assertIn(
            "merge is true for printing changes",
            set_printing_request_schema["properties"]["keep_acquisition"]["description"],
        )

        set_printing_schema = SetPrintingResponse.model_json_schema()
        self.assertEqual("set_printing", set_printing_schema["properties"]["operation"]["const"])
        self.assertEqual("string", set_printing_schema["properties"]["old_scryfall_id"]["type"])
        self.assertEqual("string", set_printing_schema["properties"]["old_language_code"]["type"])

        catalog_schema = CatalogSearchRowResponse.model_json_schema()
        catalog_properties = catalog_schema["properties"]
        self.assertEqual(
            ["normal", "foil", "etched"],
            catalog_properties["finishes"]["items"]["enum"],
        )
        self.assertIn("Catalog language code", catalog_properties["lang"]["description"])

        printing_lookup_schema = CatalogPrintingLookupRowResponse.model_json_schema()
        self.assertEqual("boolean", printing_lookup_schema["properties"]["is_default_add_choice"]["type"])
        self.assertIn(
            "default quick-add choice",
            printing_lookup_schema["properties"]["is_default_add_choice"]["description"],
        )
        printing_summary_schema = CatalogPrintingSummaryResponse.model_json_schema()
        printing_summary_properties = printing_summary_schema["properties"]
        self.assertEqual("integer", printing_summary_properties["printings_count"]["type"])
        self.assertEqual("boolean", printing_summary_properties["has_more_printings"]["type"])
        self.assertEqual("array", printing_summary_properties["printings"]["type"])
        self.assertEqual("array", printing_summary_properties["available_languages"]["type"])

        catalog_name_schema = CatalogNameSearchRowResponse.model_json_schema()
        catalog_name_properties = catalog_name_schema["properties"]
        self.assertEqual("array", catalog_name_properties["available_languages"]["type"])
        self.assertEqual("string", catalog_name_properties["available_languages"]["items"]["type"])
        self.assertIn(
            "Catalog language codes available for the matched card",
            catalog_name_properties["available_languages"]["description"],
        )
        catalog_name_result_schema = CatalogNameSearchResponse.model_json_schema()
        self.assertEqual("array", catalog_name_result_schema["properties"]["items"]["type"])
        self.assertEqual("integer", catalog_name_result_schema["properties"]["total_count"]["type"])
        self.assertEqual("boolean", catalog_name_result_schema["properties"]["has_more"]["type"])

        bulk_schema = BulkInventoryItemMutationRequest.model_json_schema()
        bulk_properties = bulk_schema["properties"]
        self.assertIn(
            "supports add_tags, remove_tags, set_tags, clear_tags, set_quantity, set_notes, set_acquisition, set_finish, set_location, and set_condition",
            bulk_schema["description"],
        )
        self.assertEqual(
            [
                "add_tags",
                "remove_tags",
                "set_tags",
                "clear_tags",
                "set_quantity",
                "set_notes",
                "set_acquisition",
                "set_finish",
                "set_location",
                "set_condition",
            ],
            bulk_properties["operation"]["enum"],
        )
        self.assertIn("provided filters", bulk_properties["selection"]["description"])
        selection_schema = bulk_properties["selection"]
        self.assertEqual("kind", selection_schema["discriminator"]["propertyName"])
        selection_refs = {
            option["$ref"].rsplit("/", maxsplit=1)[-1]
            for option in selection_schema["oneOf"]
        }
        self.assertEqual(
            {
                "BulkAllItemsSelectionRequest",
                "BulkFilteredSelectionRequest",
                "BulkItemsSelectionRequest",
            },
            selection_refs,
        )
        items_selection = BulkItemsSelectionRequest.model_json_schema()
        self.assertEqual(1, items_selection["properties"]["item_ids"]["minItems"])
        self.assertEqual(1000, items_selection["properties"]["item_ids"]["maxItems"])
        self.assertIn("Omit this field for non-tag bulk operations", bulk_properties["tags"]["description"])
        self.assertIn("Required for set_quantity", bulk_properties["quantity"]["description"])
        self.assertIn("Used by set_notes", bulk_properties["notes"]["description"])
        self.assertIn("Only applies to set_notes", bulk_properties["clear_notes"]["description"])
        self.assertIn("Used by set_acquisition", bulk_properties["acquisition_price"]["description"])
        self.assertIn("Used by set_acquisition", bulk_properties["acquisition_currency"]["description"])
        self.assertIn("Only applies to set_acquisition", bulk_properties["clear_acquisition"]["description"])
        self.assertIn("Used by set_finish", bulk_properties["finish"]["description"])
        self.assertIn("Used by set_location", bulk_properties["location"]["description"])
        self.assertIn("Only applies to set_location", bulk_properties["clear_location"]["description"])
        self.assertIn("Used by set_condition", bulk_properties["condition_code"]["description"])
        self.assertIn("Only applies to set_location or set_condition", bulk_properties["merge"]["description"])
        self.assertIn(
            "Only applies to merged set_location or set_condition changes",
            bulk_properties["keep_acquisition"]["description"],
        )

        bulk_response = BulkInventoryItemMutationResponse.model_validate(
            {
                "inventory": "personal",
                "operation": "add_tags",
                "selection_kind": "filtered",
                "matched_count": 3,
                "unchanged_count": 1,
                "updated_item_ids": [12, 44],
                "updated_count": 2,
                "updated_item_ids_truncated": False,
            }
        )
        self.assertEqual("add_tags", bulk_response.operation)
        self.assertEqual([12, 44], bulk_response.updated_item_ids)
        self.assertEqual(3, bulk_response.matched_count)

        transfer_schema = InventoryTransferRequest.model_json_schema()
        transfer_properties = transfer_schema["properties"]
        self.assertIn("Transfer selected inventory rows, or the entire source inventory", transfer_schema["description"])
        self.assertEqual(["copy", "move"], transfer_properties["mode"]["enum"])
        self.assertEqual(["fail", "merge"], transfer_properties["on_conflict"]["enum"])
        self.assertEqual(False, transfer_properties["all_items"]["default"])
        self.assertIn(
            "Only applies when on_conflict is `merge`",
            transfer_properties["keep_acquisition"]["description"],
        )
        self.assertFalse(transfer_properties["dry_run"]["default"])

        transfer_response = InventoryTransferResponse.model_validate(
            {
                "source_inventory": "source",
                "target_inventory": "target",
                "mode": "move",
                "dry_run": True,
                "selection_kind": "all_items",
                "requested_item_ids": None,
                "requested_count": 2,
                "copied_count": 0,
                "moved_count": 1,
                "merged_count": 0,
                "failed_count": 1,
                "results_returned": 2,
                "results_truncated": False,
                "results": [
                    {
                        "source_item_id": 12,
                        "target_item_id": None,
                        "status": "would_move",
                        "source_removed": True,
                        "message": None,
                    },
                    {
                        "source_item_id": 27,
                        "target_item_id": 44,
                        "status": "would_fail",
                        "source_removed": False,
                        "message": "conflict",
                    },
                ],
            }
        )
        self.assertTrue(transfer_response.dry_run)
        self.assertEqual("all_items", transfer_response.selection_kind)
        self.assertIsNone(transfer_response.requested_item_ids)
        self.assertEqual("would_move", transfer_response.results[0].status)
        self.assertEqual("would_fail", transfer_response.results[1].status)

        duplicate_schema = InventoryDuplicateRequest.model_json_schema()
        duplicate_properties = duplicate_schema["properties"]
        self.assertIn("Create a new inventory and copy every source inventory row", duplicate_schema["description"])
        self.assertIn(
            "Optional description for the duplicated inventory",
            duplicate_properties["target_description"]["description"],
        )

        duplicate_response = InventoryDuplicateResponse.model_validate(
            {
                "source_inventory": "source",
                "inventory": {
                    "inventory_id": 9,
                    "slug": "source-copy",
                    "display_name": "Source Copy",
                    "description": "Original description",
                    "default_location": None,
                    "default_tags": None,
                    "notes": None,
                    "acquisition_price": None,
                    "acquisition_currency": None,
                },
                "transfer": {
                    "source_inventory": "source",
                    "target_inventory": "source-copy",
                    "mode": "copy",
                    "dry_run": False,
                    "selection_kind": "all_items",
                    "requested_item_ids": None,
                    "requested_count": 2,
                    "copied_count": 2,
                    "moved_count": 0,
                    "merged_count": 0,
                    "failed_count": 0,
                    "results_returned": 2,
                    "results_truncated": False,
                    "results": [
                        {
                            "source_item_id": 12,
                            "target_item_id": 21,
                            "status": "copied",
                            "source_removed": False,
                            "message": None,
                        },
                        {
                            "source_item_id": 13,
                            "target_item_id": 22,
                            "status": "copied",
                            "source_removed": False,
                            "message": None,
                        },
                    ],
                },
            }
        )
        self.assertEqual("source-copy", duplicate_response.inventory.slug)
        self.assertEqual(2, duplicate_response.transfer.copied_count)

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
                "oracle_id": "oracle-sol-ring",
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
                "printing_selection_mode": "explicit",
                "old_acquisition_price": None,
                "old_acquisition_currency": None,
            }
        )
        self.assertEqual("set_acquisition", acquisition_response.operation)

        printing_response = SetPrintingResponse.model_validate(
            {
                "operation": "set_printing",
                "inventory": "personal",
                "card_name": "Sol Ring",
                "oracle_id": "oracle-sol-ring",
                "set_code": "sld",
                "set_name": "Secret Lair",
                "collector_number": "99",
                "scryfall_id": "sld-sol-ring",
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
                "printing_selection_mode": "explicit",
                "old_scryfall_id": "cmd-sol-ring",
                "old_finish": "normal",
                "old_language_code": "en",
                "merged": False,
                "merged_source_item_id": None,
            }
        )
        self.assertEqual("set_printing", printing_response.operation)

    def test_demo_payload_examples_validate_against_models(self) -> None:
        example_validators = {
            "inventories_list.json": lambda payload: [
                InventoryListRowResponse.model_validate(item) for item in payload
            ],
            "bootstrap_default_inventory_response.json": DefaultInventoryBootstrapResponse.model_validate,
            "owned_items.json": lambda payload: [
                OwnedInventoryRowResponse.model_validate(item) for item in payload
            ],
            "owned_items_page.json": OwnedInventoryItemsPageResponse.model_validate,
            "patch_printing_request.json": SetInventoryItemPrintingRequest.model_validate,
            "add_item_response.json": AddInventoryItemResponse.model_validate,
            "delete_item_response.json": RemoveInventoryItemResponse.model_validate,
            "patch_quantity_response.json": SetQuantityResponse.model_validate,
            "patch_finish_response.json": SetFinishResponse.model_validate,
            "patch_location_response.json": SetLocationResponse.model_validate,
            "patch_condition_response.json": SetConditionResponse.model_validate,
            "patch_notes_response.json": SetNotesResponse.model_validate,
            "patch_tags_response.json": SetTagsResponse.model_validate,
            "patch_acquisition_response.json": SetAcquisitionResponse.model_validate,
            "patch_printing_response.json": SetPrintingResponse.model_validate,
            "csv_import_response.json": CsvImportResponse.model_validate,
            "decklist_import_response.json": DecklistImportResponse.model_validate,
            "deck_url_import_response.json": DeckUrlImportResponse.model_validate,
        }

        for filename, validator in example_validators.items():
            with self.subTest(filename=filename):
                payload = json.loads((DEMO_PAYLOADS_DIR / filename).read_text(encoding="utf-8"))
                validator(payload)

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
            lambda: summarize_card_printings_for_oracle(Path("var/db/not-used.db"), "oracle-1", scope="weird"),
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
            lambda: list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                limit=0,
            ),
            lambda: list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                offset=-1,
            ),
            lambda: list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                sort_key="unsafe_sql",
            ),
            lambda: list_owned_filtered_page(
                Path("var/db/not-used.db"),
                inventory_slug="personal",
                provider="tcgplayer",
                sort_direction="sideways",
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
