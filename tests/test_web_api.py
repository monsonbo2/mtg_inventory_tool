"""Integration-oriented smoke tests for the FastAPI web shell."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import io
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.inventory.service import (
    actor_inventory_role,
    create_inventory,
    grant_inventory_membership,
    import_deck_url,
    list_inventory_audit_events,
)
from tests.optional_dependencies import (
    WEB_TEST_SKIP_REASON,
    web_test_dependencies_available,
)


WEB_TESTING_AVAILABLE = web_test_dependencies_available()

if WEB_TESTING_AVAILABLE:
    import httpx
    import uvicorn

    from mtg_source_stack.api.app import create_app
    from mtg_source_stack.api.dependencies import ApiSettings, RequestContext
    from mtg_source_stack.api.routes import (
        _parse_resolutions_json_form,
        _require_csv_import_inventory_write_access,
        _validate_uploaded_csv_size,
    )
    from mtg_source_stack.errors import AuthorizationError, ValidationError


def _localhost_server_testing_available() -> bool:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return True


LOCALHOST_SERVER_TESTING_AVAILABLE = _localhost_server_testing_available()


@contextmanager
def _live_test_server(app):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    host, port = sock.getsockname()
    sock.close()

    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 5
    while not server.started and thread.is_alive() and time.time() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=1)
        raise RuntimeError("Timed out waiting for test server to start.")
    try:
        yield f"http://{host}:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@unittest.skipUnless(
    WEB_TESTING_AVAILABLE,
    WEB_TEST_SKIP_REASON,
)
class WebApiSchemaTest(unittest.TestCase):
    def _schema_name_from_ref(self, ref: str) -> str:
        return ref.rsplit("/", 1)[-1]

    def test_demo_api_openapi_exposes_typed_response_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            app = create_app(
                ApiSettings(
                    db_path=db_path,
                    runtime_mode="local_demo",
                    auto_migrate=True,
                    host="127.0.0.1",
                    port=8000,
                )
            )
            spec = app.openapi()
            components = spec["components"]["schemas"]

            for path, method in [
                ("/imports/csv", "post"),
                ("/imports/decklist", "post"),
                ("/imports/deck-url", "post"),
                ("/me/access-summary", "get"),
                ("/me/bootstrap", "post"),
                ("/inventories/{inventory_slug}/members", "get"),
                ("/inventories/{inventory_slug}/members", "post"),
                ("/inventories/{inventory_slug}/members/{actor_id}", "patch"),
                ("/inventories/{inventory_slug}/members/{actor_id}", "delete"),
                ("/inventories/{inventory_slug}/share-link", "get"),
                ("/inventories/{inventory_slug}/share-link", "post"),
                ("/inventories/{inventory_slug}/share-link/rotate", "post"),
                ("/inventories/{inventory_slug}/share-link", "delete"),
                ("/shared/inventories/{share_token}", "get"),
                ("/cards/search", "get"),
                ("/cards/search/names", "get"),
                ("/cards/oracle/{oracle_id}/printings", "get"),
                ("/cards/oracle/{oracle_id}/printings/summary", "get"),
                ("/inventories", "post"),
                ("/inventories/{source_inventory_slug}/duplicate", "post"),
                ("/inventories/{inventory_slug}/export.csv", "get"),
                ("/inventories/{inventory_slug}/items", "get"),
                ("/inventories/{inventory_slug}/items/page", "get"),
                ("/inventories/{inventory_slug}/items", "post"),
                ("/inventories/{inventory_slug}/items/bulk", "post"),
                ("/inventories/{source_inventory_slug}/transfer", "post"),
                ("/inventories/{inventory_slug}/items/{item_id}", "patch"),
                ("/inventories/{inventory_slug}/items/{item_id}/printing", "patch"),
                ("/inventories/{inventory_slug}/items/{item_id}", "delete"),
                ("/inventories/{inventory_slug}/audit", "get"),
            ]:
                self.assertNotIn("422", spec["paths"][path][method]["responses"])

            for path, method in [
                ("/inventories", "get"),
                ("/inventories", "post"),
                ("/imports/csv", "post"),
                ("/imports/decklist", "post"),
                ("/imports/deck-url", "post"),
                ("/inventories/{inventory_slug}/export.csv", "get"),
                ("/me/access-summary", "get"),
                ("/me/bootstrap", "post"),
                ("/inventories/{inventory_slug}/members", "get"),
                ("/inventories/{inventory_slug}/members", "post"),
                ("/inventories/{inventory_slug}/members/{actor_id}", "patch"),
                ("/inventories/{inventory_slug}/members/{actor_id}", "delete"),
                ("/inventories/{inventory_slug}/share-link", "get"),
                ("/inventories/{inventory_slug}/share-link", "post"),
                ("/inventories/{inventory_slug}/share-link/rotate", "post"),
                ("/inventories/{inventory_slug}/share-link", "delete"),
                ("/cards/search", "get"),
                ("/cards/search/names", "get"),
                ("/cards/oracle/{oracle_id}/printings", "get"),
                ("/inventories/{source_inventory_slug}/duplicate", "post"),
                ("/inventories/{inventory_slug}/items", "get"),
                ("/inventories/{inventory_slug}/items/page", "get"),
                ("/inventories/{inventory_slug}/items", "post"),
                ("/inventories/{inventory_slug}/items/bulk", "post"),
                ("/inventories/{source_inventory_slug}/transfer", "post"),
                ("/inventories/{inventory_slug}/items/{item_id}", "patch"),
                ("/inventories/{inventory_slug}/items/{item_id}/printing", "patch"),
                ("/inventories/{inventory_slug}/items/{item_id}", "delete"),
                ("/inventories/{inventory_slug}/audit", "get"),
            ]:
                self.assertIn("401", spec["paths"][path][method]["responses"])
                self.assertIn("403", spec["paths"][path][method]["responses"])

            cards_schema = spec["paths"]["/cards/search"]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ]
            self.assertEqual("array", cards_schema["type"])
            card_schema_name = self._schema_name_from_ref(cards_schema["items"]["$ref"])
            self.assertEqual("CatalogSearchRowResponse", card_schema_name)
            self.assertEqual("array", components[card_schema_name]["properties"]["finishes"]["type"])
            self.assertEqual(
                "string",
                components[card_schema_name]["properties"]["finishes"]["items"]["type"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                components[card_schema_name]["properties"]["image_uri_small"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                components[card_schema_name]["properties"]["image_uri_normal"]["anyOf"],
            )
            search_parameters = {
                parameter["name"]: parameter
                for parameter in spec["paths"]["/cards/search"]["get"]["parameters"]
            }
            self.assertEqual(
                ["normal", "nonfoil", "foil", "etched"],
                search_parameters["finish"]["schema"]["anyOf"][0]["enum"],
            )
            self.assertIn(
                "Recommended codes include: en, ja, de, fr",
                search_parameters["lang"]["description"],
            )
            self.assertEqual(
                ["default", "all"],
                search_parameters["scope"]["schema"]["enum"],
            )

            card_names_schema = spec["paths"]["/cards/search/names"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            self.assertEqual(
                "CatalogNameSearchResponse",
                self._schema_name_from_ref(card_names_schema["$ref"]),
            )
            card_name_result_schema_name = self._schema_name_from_ref(card_names_schema["$ref"])
            self.assertEqual(
                "array",
                components[card_name_result_schema_name]["properties"]["items"]["type"],
            )
            card_name_schema_name = self._schema_name_from_ref(
                components[card_name_result_schema_name]["properties"]["items"]["items"]["$ref"]
            )
            self.assertEqual("CatalogNameSearchRowResponse", card_name_schema_name)
            self.assertEqual(
                "array",
                components[card_name_schema_name]["properties"]["available_languages"]["type"],
            )
            self.assertEqual(
                "string",
                components[card_name_schema_name]["properties"]["available_languages"]["items"]["type"],
            )
            self.assertEqual(
                "integer",
                components[card_name_result_schema_name]["properties"]["total_count"]["type"],
            )
            self.assertEqual(
                "boolean",
                components[card_name_result_schema_name]["properties"]["has_more"]["type"],
            )
            name_search_parameters = {
                parameter["name"]: parameter
                for parameter in spec["paths"]["/cards/search/names"]["get"]["parameters"]
            }
            self.assertEqual(
                ["default", "all"],
                name_search_parameters["scope"]["schema"]["enum"],
            )

            printings_schema = spec["paths"]["/cards/oracle/{oracle_id}/printings"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            self.assertEqual("array", printings_schema["type"])
            self.assertEqual(
                "CatalogPrintingLookupRowResponse",
                self._schema_name_from_ref(printings_schema["items"]["$ref"]),
            )
            printings_schema_name = self._schema_name_from_ref(printings_schema["items"]["$ref"])
            self.assertEqual(
                "boolean",
                components[printings_schema_name]["properties"]["is_default_add_choice"]["type"],
            )
            printings_parameters = {
                parameter["name"]: parameter
                for parameter in spec["paths"]["/cards/oracle/{oracle_id}/printings"]["get"]["parameters"]
            }
            self.assertIn("Use `all` to include every available catalog language", printings_parameters["lang"]["description"])
            self.assertEqual(
                ["default", "all"],
                printings_parameters["scope"]["schema"]["enum"],
            )
            summary_schema = spec["paths"]["/cards/oracle/{oracle_id}/printings/summary"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            summary_schema_name = self._schema_name_from_ref(summary_schema["$ref"])
            self.assertEqual("CatalogPrintingSummaryResponse", summary_schema_name)
            summary_properties = components[summary_schema_name]["properties"]
            self.assertEqual(
                "CatalogPrintingLookupRowResponse",
                self._schema_name_from_ref(summary_properties["default_printing"]["anyOf"][0]["$ref"]),
            )
            self.assertEqual("boolean", summary_properties["has_more_printings"]["type"])
            self.assertEqual("integer", summary_properties["printings_count"]["type"])
            self.assertEqual("array", summary_properties["available_languages"]["type"])
            self.assertEqual(
                ["default", "all"],
                {
                    parameter["name"]: parameter
                    for parameter in spec["paths"]["/cards/oracle/{oracle_id}/printings/summary"]["get"]["parameters"]
                }["scope"]["schema"]["enum"],
            )

            owned_schema = spec["paths"]["/inventories/{inventory_slug}/items"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            self.assertEqual("array", owned_schema["type"])
            owned_schema_name = self._schema_name_from_ref(owned_schema["items"]["$ref"])
            owned_properties = components[owned_schema_name]["properties"]
            self.assertEqual("OwnedInventoryRowResponse", owned_schema_name)
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                owned_properties["acquisition_price"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                owned_properties["unit_price"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                owned_properties["est_value"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                owned_properties["image_uri_small"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                owned_properties["image_uri_normal"]["anyOf"],
            )
            self.assertEqual(
                ["normal", "foil", "etched"],
                owned_properties["allowed_finishes"]["items"]["enum"],
            )
            self.assertEqual(
                ["explicit", "defaulted"],
                owned_properties["printing_selection_mode"]["enum"],
            )

            owned_page_schema = spec["paths"]["/inventories/{inventory_slug}/items/page"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            owned_page_schema_name = self._schema_name_from_ref(owned_page_schema["$ref"])
            self.assertEqual("OwnedInventoryItemsPageResponse", owned_page_schema_name)
            owned_page_properties = components[owned_page_schema_name]["properties"]
            self.assertEqual(
                "OwnedInventoryRowResponse",
                self._schema_name_from_ref(owned_page_properties["items"]["items"]["$ref"]),
            )
            self.assertEqual("integer", owned_page_properties["total_count"]["type"])
            self.assertEqual("boolean", owned_page_properties["has_more"]["type"])
            self.assertEqual(
                ["name", "set", "quantity", "finish", "condition_code", "language_code", "location", "tags", "est_value", "item_id"],
                owned_page_properties["sort_key"]["enum"],
            )
            owned_page_parameters = {
                parameter["name"]: parameter
                for parameter in spec["paths"]["/inventories/{inventory_slug}/items/page"]["get"]["parameters"]
            }
            self.assertEqual(50, owned_page_parameters["limit"]["schema"]["default"])
            self.assertEqual(0, owned_page_parameters["offset"]["schema"]["default"])
            self.assertEqual(
                ["asc", "desc"],
                owned_page_parameters["sort_direction"]["schema"]["enum"],
            )

            inventories_list_schema = spec["paths"]["/inventories"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            self.assertEqual("array", inventories_list_schema["type"])
            inventories_list_schema_name = self._schema_name_from_ref(inventories_list_schema["items"]["$ref"])
            self.assertEqual("InventoryListRowResponse", inventories_list_schema_name)
            inventories_list_properties = components[inventories_list_schema_name]["properties"]
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_list_properties["default_location"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_list_properties["default_tags"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_list_properties["notes"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_list_properties["acquisition_price"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_list_properties["acquisition_currency"]["anyOf"],
            )
            self.assertEqual(
                [
                    {"enum": ["viewer", "editor", "owner", "admin"], "type": "string"},
                    {"type": "null"},
                ],
                inventories_list_properties["role"]["anyOf"],
            )
            self.assertEqual("boolean", inventories_list_properties["can_read"]["type"])
            self.assertEqual("boolean", inventories_list_properties["can_write"]["type"])
            self.assertEqual("boolean", inventories_list_properties["can_manage_share"]["type"])
            self.assertEqual("boolean", inventories_list_properties["can_transfer_to"]["type"])

            inventories_create_request_schema = spec["paths"]["/inventories"]["post"]["requestBody"]["content"][
                "application/json"
            ]["schema"]
            inventories_create_request_schema_name = self._schema_name_from_ref(
                inventories_create_request_schema["$ref"]
            )
            inventories_create_request_properties = components[inventories_create_request_schema_name]["properties"]
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_request_properties["default_location"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_request_properties["default_tags"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_request_properties["notes"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_request_properties["acquisition_price"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_request_properties["acquisition_currency"]["anyOf"],
            )

            inventories_create_schema = spec["paths"]["/inventories"]["post"]["responses"]["201"]["content"][
                "application/json"
            ]["schema"]
            inventories_create_schema_name = self._schema_name_from_ref(inventories_create_schema["$ref"])
            self.assertEqual("InventoryCreateResponse", inventories_create_schema_name)
            inventories_create_properties = components[inventories_create_schema_name]["properties"]
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_properties["default_location"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_properties["default_tags"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_properties["notes"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_properties["acquisition_price"]["anyOf"],
            )
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                inventories_create_properties["acquisition_currency"]["anyOf"],
            )

            bootstrap_schema = spec["paths"]["/me/bootstrap"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            bootstrap_schema_name = self._schema_name_from_ref(bootstrap_schema["$ref"])
            self.assertEqual("DefaultInventoryBootstrapResponse", bootstrap_schema_name)
            self.assertEqual("boolean", components[bootstrap_schema_name]["properties"]["created"]["type"])
            self.assertEqual(
                "InventoryCreateResponse",
                self._schema_name_from_ref(components[bootstrap_schema_name]["properties"]["inventory"]["$ref"]),
            )
            access_summary_schema = spec["paths"]["/me/access-summary"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            access_summary_schema_name = self._schema_name_from_ref(access_summary_schema["$ref"])
            self.assertEqual("AccessSummaryResponse", access_summary_schema_name)
            access_summary_properties = components[access_summary_schema_name]["properties"]
            self.assertEqual("boolean", access_summary_properties["can_bootstrap"]["type"])
            self.assertEqual("boolean", access_summary_properties["has_readable_inventory"]["type"])
            self.assertEqual("integer", access_summary_properties["visible_inventory_count"]["type"])
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                access_summary_properties["default_inventory_slug"]["anyOf"],
            )

            members_schema = spec["paths"]["/inventories/{inventory_slug}/members"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            self.assertEqual("array", members_schema["type"])
            member_schema_name = self._schema_name_from_ref(members_schema["items"]["$ref"])
            self.assertEqual("InventoryMembershipResponse", member_schema_name)
            member_properties = components[member_schema_name]["properties"]
            self.assertEqual(["viewer", "editor", "owner"], member_properties["role"]["enum"])
            self.assertEqual("string", member_properties["actor_id"]["type"])
            member_grant_request_schema = spec["paths"]["/inventories/{inventory_slug}/members"]["post"][
                "requestBody"
            ]["content"]["application/json"]["schema"]
            self.assertEqual(
                "InventoryMembershipGrantRequest",
                self._schema_name_from_ref(member_grant_request_schema["$ref"]),
            )
            member_update_request_schema = spec["paths"]["/inventories/{inventory_slug}/members/{actor_id}"][
                "patch"
            ]["requestBody"]["content"]["application/json"]["schema"]
            self.assertEqual(
                "InventoryMembershipUpdateRequest",
                self._schema_name_from_ref(member_update_request_schema["$ref"]),
            )
            member_remove_schema = spec["paths"]["/inventories/{inventory_slug}/members/{actor_id}"]["delete"][
                "responses"
            ]["200"]["content"]["application/json"]["schema"]
            self.assertEqual(
                "InventoryMembershipRemovalResponse",
                self._schema_name_from_ref(member_remove_schema["$ref"]),
            )
            share_link_schema = spec["paths"]["/inventories/{inventory_slug}/share-link"]["post"]["responses"][
                "201"
            ]["content"]["application/json"]["schema"]
            share_link_schema_name = self._schema_name_from_ref(share_link_schema["$ref"])
            self.assertEqual("InventoryShareLinkTokenResponse", share_link_schema_name)
            share_link_properties = components[share_link_schema_name]["properties"]
            self.assertEqual("string", share_link_properties["token"]["type"])
            self.assertEqual("string", share_link_properties["public_path"]["type"])
            self.assertIn(
                "Browser-facing public share page path",
                share_link_properties["public_path"]["description"],
            )
            self.assertIn(
                "/api/shared/inventories/{share_token}",
                share_link_properties["public_path"]["description"],
            )
            self.assertEqual("boolean", share_link_properties["active"]["type"])

            public_share_schema = spec["paths"]["/shared/inventories/{share_token}"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            public_share_schema_name = self._schema_name_from_ref(public_share_schema["$ref"])
            self.assertEqual("PublicInventoryShareResponse", public_share_schema_name)
            public_item_schema_name = self._schema_name_from_ref(
                components[public_share_schema_name]["properties"]["items"]["items"]["$ref"]
            )
            public_item_properties = components[public_item_schema_name]["properties"]
            self.assertNotIn("notes", public_item_properties)
            self.assertNotIn("acquisition_price", public_item_properties)
            self.assertNotIn("location", public_item_properties)
            duplicate_schema = spec["paths"]["/inventories/{source_inventory_slug}/duplicate"]["post"]["responses"][
                "201"
            ]["content"]["application/json"]["schema"]
            duplicate_schema_name = self._schema_name_from_ref(duplicate_schema["$ref"])
            self.assertEqual("InventoryDuplicateResponse", duplicate_schema_name)
            self.assertEqual(
                "InventoryCreateResponse",
                self._schema_name_from_ref(components[duplicate_schema_name]["properties"]["inventory"]["$ref"]),
            )
            self.assertEqual(
                "InventoryTransferResponse",
                self._schema_name_from_ref(components[duplicate_schema_name]["properties"]["transfer"]["$ref"]),
            )
            import_request_schema = spec["paths"]["/imports/csv"]["post"]["requestBody"]["content"][
                "multipart/form-data"
            ]["schema"]
            import_request_schema_name = self._schema_name_from_ref(import_request_schema["$ref"])
            import_request_component = components[import_request_schema_name]
            self.assertEqual(["file"], import_request_component["required"])
            self.assertEqual("string", import_request_component["properties"]["file"]["type"])
            self.assertEqual(
                "application/octet-stream",
                import_request_component["properties"]["file"]["contentMediaType"],
            )
            self.assertEqual("boolean", import_request_component["properties"]["dry_run"]["type"])
            self.assertEqual(
                [{"type": "string"}, {"type": "null"}],
                import_request_component["properties"]["resolutions_json"]["anyOf"],
            )

            import_response_schema = spec["paths"]["/imports/csv"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            import_response_schema_name = self._schema_name_from_ref(import_response_schema["$ref"])
            self.assertEqual("CsvImportResponse", import_response_schema_name)
            self.assertEqual(
                "string",
                components[import_response_schema_name]["properties"]["detected_format"]["type"],
            )
            self.assertEqual(
                "boolean",
                components[import_response_schema_name]["properties"]["ready_to_commit"]["type"],
            )
            self.assertEqual(
                "CsvImportRowResponse",
                self._schema_name_from_ref(
                    components[import_response_schema_name]["properties"]["imported_rows"]["items"]["$ref"]
                ),
            )
            self.assertEqual(
                "CsvImportSummaryResponse",
                self._schema_name_from_ref(components[import_response_schema_name]["properties"]["summary"]["$ref"]),
            )
            self.assertEqual(
                "CsvImportResolutionIssueResponse",
                self._schema_name_from_ref(
                    components[import_response_schema_name]["properties"]["resolution_issues"]["items"]["$ref"]
                ),
            )
            decklist_request_schema = spec["paths"]["/imports/decklist"]["post"]["requestBody"]["content"][
                "application/json"
            ]["schema"]
            decklist_request_schema_name = self._schema_name_from_ref(decklist_request_schema["$ref"])
            self.assertEqual("DecklistImportRequest", decklist_request_schema_name)
            self.assertEqual(
                ["deck_text", "default_inventory"],
                components[decklist_request_schema_name]["required"],
            )
            self.assertEqual(
                False,
                components[decklist_request_schema_name]["properties"]["dry_run"]["default"],
            )
            self.assertEqual(
                "DecklistImportResolutionRequest",
                self._schema_name_from_ref(
                    components[decklist_request_schema_name]["properties"]["resolutions"]["items"]["$ref"]
                ),
            )
            decklist_response_schema = spec["paths"]["/imports/decklist"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            decklist_response_schema_name = self._schema_name_from_ref(decklist_response_schema["$ref"])
            self.assertEqual("DecklistImportResponse", decklist_response_schema_name)
            self.assertEqual(
                "boolean",
                components[decklist_response_schema_name]["properties"]["ready_to_commit"]["type"],
            )
            self.assertEqual(
                "DecklistImportRowResponse",
                self._schema_name_from_ref(
                    components[decklist_response_schema_name]["properties"]["imported_rows"]["items"]["$ref"]
                ),
            )
            self.assertEqual(
                "DecklistImportSummaryResponse",
                self._schema_name_from_ref(components[decklist_response_schema_name]["properties"]["summary"]["$ref"]),
            )
            self.assertEqual(
                "DecklistImportResolutionIssueResponse",
                self._schema_name_from_ref(
                    components[decklist_response_schema_name]["properties"]["resolution_issues"]["items"]["$ref"]
                ),
            )
            deck_url_request_schema = spec["paths"]["/imports/deck-url"]["post"]["requestBody"]["content"][
                "application/json"
            ]["schema"]
            deck_url_request_schema_name = self._schema_name_from_ref(deck_url_request_schema["$ref"])
            self.assertEqual("DeckUrlImportRequest", deck_url_request_schema_name)
            self.assertEqual(
                ["source_url", "default_inventory"],
                components[deck_url_request_schema_name]["required"],
            )
            self.assertEqual(
                "DeckUrlImportResolutionRequest",
                self._schema_name_from_ref(
                    components[deck_url_request_schema_name]["properties"]["resolutions"]["items"]["$ref"]
                ),
            )
            deck_url_response_schema = spec["paths"]["/imports/deck-url"]["post"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            deck_url_response_schema_name = self._schema_name_from_ref(deck_url_response_schema["$ref"])
            self.assertEqual("DeckUrlImportResponse", deck_url_response_schema_name)
            self.assertEqual(
                "boolean",
                components[deck_url_response_schema_name]["properties"]["ready_to_commit"]["type"],
            )
            self.assertEqual(
                "DeckUrlImportRowResponse",
                self._schema_name_from_ref(
                    components[deck_url_response_schema_name]["properties"]["imported_rows"]["items"]["$ref"]
                ),
            )
            self.assertEqual(
                "DeckUrlImportSummaryResponse",
                self._schema_name_from_ref(components[deck_url_response_schema_name]["properties"]["summary"]["$ref"]),
            )
            self.assertEqual(
                "DeckUrlImportResolutionIssueResponse",
                self._schema_name_from_ref(
                    components[deck_url_response_schema_name]["properties"]["resolution_issues"]["items"]["$ref"]
                ),
            )
            self.assertIn(
                "unknown_card",
                components["DeckUrlImportResolutionIssueResponse"]["properties"]["kind"]["enum"],
            )
            self.assertIn(
                "scryfall_id",
                components["DeckUrlImportRequestedCardResponse"]["properties"],
            )
            export_csv_response = spec["paths"]["/inventories/{inventory_slug}/export.csv"]["get"]["responses"]["200"]
            self.assertIn("text/csv", export_csv_response["content"])
            self.assertEqual(
                "string",
                export_csv_response["content"]["text/csv"]["schema"]["type"],
            )
            export_csv_parameters = {
                parameter["name"]: parameter
                for parameter in spec["paths"]["/inventories/{inventory_slug}/export.csv"]["get"]["parameters"]
            }
            self.assertEqual(
                ["default"],
                export_csv_parameters["profile"]["schema"]["enum"],
            )
            self.assertEqual(
                "default",
                export_csv_parameters["profile"]["schema"]["default"],
            )
            inventory_parameters = {
                parameter["name"]: parameter
                for parameter in spec["paths"]["/inventories/{inventory_slug}/items"]["get"]["parameters"]
            }
            self.assertEqual(
                ["normal", "nonfoil", "foil", "etched"],
                inventory_parameters["finish"]["schema"]["anyOf"][0]["enum"],
            )
            self.assertIn(
                "Canonical condition codes: M, NM, LP, MP, HP, DMG",
                inventory_parameters["condition_code"]["description"],
            )
            self.assertIn(
                "Canonical language codes: en, ja, de, fr",
                inventory_parameters["language_code"]["description"],
            )

            add_request_schema = components["AddInventoryItemRequest"]
            self.assertIn("oracle_id", add_request_schema["properties"])
            self.assertNotIn("default", add_request_schema["properties"]["language_code"])
            self.assertIsNone(add_request_schema["properties"]["location"].get("default"))
            self.assertIn(
                "inherits the resolved printing language",
                add_request_schema["properties"]["language_code"]["description"],
            )
            self.assertIn(
                "prefers English mainstream-paper printings",
                add_request_schema["properties"]["oracle_id"]["description"],
            )

            patch_schema = spec["paths"]["/inventories/{inventory_slug}/items/{item_id}"]["patch"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            patch_variants = patch_schema.get("anyOf") or patch_schema.get("oneOf")
            self.assertIsNotNone(patch_variants)
            self.assertGreaterEqual(len(patch_variants), 2)
            patch_schema_names = {self._schema_name_from_ref(variant["$ref"]) for variant in patch_variants}
            self.assertEqual(
                {
                    "SetQuantityResponse",
                    "SetFinishResponse",
                    "SetLocationResponse",
                    "SetConditionResponse",
                    "SetNotesResponse",
                    "SetTagsResponse",
                    "SetAcquisitionResponse",
                },
                patch_schema_names,
            )
            for schema_name, expected_operation in {
                "SetQuantityResponse": "set_quantity",
                "SetFinishResponse": "set_finish",
                "SetLocationResponse": "set_location",
                "SetConditionResponse": "set_condition",
                "SetNotesResponse": "set_notes",
                "SetTagsResponse": "set_tags",
                "SetAcquisitionResponse": "set_acquisition",
            }.items():
                operation_property = components[schema_name]["properties"]["operation"]
                operation_value = operation_property.get("const", operation_property.get("enum", [None])[0])
                self.assertEqual(expected_operation, operation_value)
                self.assertIn("operation", components[schema_name]["required"])

            patch_request_schema = components["PatchInventoryItemRequest"]
            self.assertIn("exactly one mutation family", patch_request_schema["description"])
            self.assertIn(
                "Only applies to location or condition changes",
                patch_request_schema["properties"]["merge"]["description"],
            )
            self.assertIn(
                "Only applies to merged location or condition changes",
                patch_request_schema["properties"]["keep_acquisition"]["description"],
            )

            set_printing_request_schema = components["SetInventoryItemPrintingRequest"]
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
            set_printing_schema = spec["paths"]["/inventories/{inventory_slug}/items/{item_id}/printing"]["patch"][
                "responses"
            ]["200"]["content"]["application/json"]["schema"]
            self.assertEqual(
                "SetPrintingResponse",
                self._schema_name_from_ref(set_printing_schema["$ref"]),
            )

            bulk_request_schema = components["BulkInventoryItemMutationRequest"]
            self.assertIn(
                "supports add_tags, remove_tags, set_tags, clear_tags, set_quantity, set_notes, set_acquisition, set_finish, set_location, and set_condition",
                bulk_request_schema["description"],
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
                bulk_request_schema["properties"]["operation"]["enum"],
            )
            self.assertEqual(1, bulk_request_schema["properties"]["item_ids"]["minItems"])
            self.assertEqual(200, bulk_request_schema["properties"]["item_ids"]["maxItems"])
            self.assertIn("Used by set_location", bulk_request_schema["properties"]["location"]["description"])
            self.assertIn("Only applies to set_location", bulk_request_schema["properties"]["clear_location"]["description"])
            self.assertIn("Used by set_condition", bulk_request_schema["properties"]["condition_code"]["description"])
            self.assertIn("Only applies to set_location or set_condition", bulk_request_schema["properties"]["merge"]["description"])
            self.assertIn(
                "Only applies to merged set_location or set_condition changes",
                bulk_request_schema["properties"]["keep_acquisition"]["description"],
            )

            bulk_response_schema = spec["paths"]["/inventories/{inventory_slug}/items/bulk"]["post"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            self.assertEqual(
                "BulkInventoryItemMutationResponse",
                self._schema_name_from_ref(bulk_response_schema["$ref"]),
            )

            audit_schema = spec["paths"]["/inventories/{inventory_slug}/audit"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            self.assertEqual("array", audit_schema["type"])
            audit_schema_name = self._schema_name_from_ref(audit_schema["items"]["$ref"])
            self.assertEqual("InventoryAuditEventResponse", audit_schema_name)

            error_schema = spec["paths"]["/cards/search"]["get"]["responses"]["400"]["content"]["application/json"][
                "schema"
            ]
            self.assertEqual("ApiErrorResponse", self._schema_name_from_ref(error_schema["$ref"]))

            health_schema = spec["paths"]["/health"]["get"]["responses"]["200"]["content"]["application/json"][
                "schema"
            ]
            health_schema_name = self._schema_name_from_ref(health_schema["$ref"])
            self.assertEqual("HealthResponse", health_schema_name)
            self.assertNotIn("db_path", components[health_schema_name]["properties"])
            self.assertEqual(
                "boolean",
                components[health_schema_name]["properties"]["trusted_actor_headers"]["type"],
            )
            self.assertNotIn("HTTPValidationError", components)
            self.assertNotIn("ValidationError", components)


@unittest.skipUnless(
    WEB_TESTING_AVAILABLE,
    WEB_TEST_SKIP_REASON,
)
class WebApiImportHelperTest(unittest.TestCase):
    def test_parse_resolutions_json_form_accepts_array_of_objects(self) -> None:
        self.assertEqual(
            [{"csv_row": 2, "scryfall_id": "api-card-1", "finish": "normal"}],
            _parse_resolutions_json_form(
                json.dumps([{"csv_row": 2, "scryfall_id": "api-card-1", "finish": "normal"}])
            ),
        )

    def test_validate_uploaded_csv_size_rejects_oversized_files(self) -> None:
        upload = type("UploadStub", (), {"file": io.BytesIO(b"x" * 65)})()

        with self.assertRaisesRegex(ValidationError, "CSV upload must not exceed 64 bytes."):
            _validate_uploaded_csv_size(upload, max_bytes=64)

    def test_shared_service_csv_import_write_access_helper_requires_membership_or_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer-user",
                role="viewer",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="editor-user",
                role="editor",
            )

            viewer_context = RequestContext(
                actor_type="api",
                actor_id="viewer-user",
                request_id="req-viewer",
                roles=frozenset({"viewer"}),
            )
            editor_context = RequestContext(
                actor_type="api",
                actor_id="editor-user",
                request_id="req-editor",
                roles=frozenset({"viewer"}),
            )
            admin_context = RequestContext(
                actor_type="api",
                actor_id="admin-user",
                request_id="req-admin",
                roles=frozenset({"editor", "admin"}),
            )

            with connect(db_path) as connection:
                with self.assertRaises(AuthorizationError):
                    _require_csv_import_inventory_write_access(
                        connection,
                        inventory_slug="personal",
                        context=viewer_context,
                    )

                _require_csv_import_inventory_write_access(
                    connection,
                    inventory_slug="personal",
                    context=editor_context,
                )
                _require_csv_import_inventory_write_access(
                    connection,
                    inventory_slug="personal",
                    context=admin_context,
                )


@unittest.skipUnless(
    WEB_TESTING_AVAILABLE and LOCALHOST_SERVER_TESTING_AVAILABLE,
    f"{WEB_TEST_SKIP_REASON} Localhost socket access is also required for live API shell tests.",
)
class WebApiTest(unittest.TestCase):
    @contextmanager
    def _client(
        self,
        db_path: Path,
        *,
        trust_actor_headers: bool = False,
        runtime_mode: str = "local_demo",
        auto_migrate: bool = True,
        csv_import_max_bytes: int = 25 * 1024 * 1024,
        snapshot_signing_secret: str | None = None,
    ):
        settings_kwargs = {
            "db_path": db_path,
            "runtime_mode": runtime_mode,
            "auto_migrate": auto_migrate,
            "host": "127.0.0.1",
            "port": 8000,
            "csv_import_max_bytes": csv_import_max_bytes,
            "trust_actor_headers": trust_actor_headers,
            "proxy_headers": runtime_mode == "shared_service",
        }
        if snapshot_signing_secret is not None:
            settings_kwargs["snapshot_signing_secret"] = snapshot_signing_secret
        elif runtime_mode == "shared_service":
            settings_kwargs["snapshot_signing_secret"] = "test-shared-snapshot-secret"
        app = create_app(
            ApiSettings(**settings_kwargs)
        )
        with _live_test_server(app) as base_url:
            with httpx.Client(base_url=base_url, timeout=5.0) as client:
                yield client

    def _seed_card(self, db_path: Path, *, finishes_json: str = '["normal","foil"]') -> None:
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
                    ?,
                    ?,
                    ?,
                    'tst',
                    'Test Set',
                    '10',
                    ?,
                    '{"small":"https://example.test/cards/api-card-1-small.jpg","normal":"https://example.test/cards/api-card-1-normal.jpg"}'
                )
                """,
                ("api-card-1", "api-oracle-1", "API Test Card", finishes_json),
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
        collector_number: str = "10",
        lang: str = "en",
        released_at: str = "2026-04-01",
        finishes_json: str = '["normal","foil"]',
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

    def _seed_oracle_printings(self, db_path: Path) -> None:
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
                VALUES (?, 'api-oracle-lookup', ?, ?, ?, ?, ?, ?, '["nonfoil","foil"]', ?)
                """,
                [
                    (
                        "api-printing-en-new",
                        "API Lookup Card",
                        "mkm",
                        "Murders at Karlov Manor",
                        "14",
                        "en",
                        "2024-02-09",
                        '{"small":"https://example.test/cards/api-printing-en-new-small.jpg","normal":"https://example.test/cards/api-printing-en-new-normal.jpg"}',
                    ),
                    (
                        "api-printing-ja",
                        "API Lookup Card",
                        "mkm",
                        "Murders at Karlov Manor",
                        "15",
                        "ja",
                        "2024-03-01",
                        '{"small":"https://example.test/cards/api-printing-ja-small.jpg","normal":"https://example.test/cards/api-printing-ja-normal.jpg"}',
                    ),
                    (
                        "api-printing-en-old",
                        "API Lookup Card",
                        "woe",
                        "Wilds of Eldraine",
                        "16",
                        "en",
                        "2023-09-01",
                        '{"small":"https://example.test/cards/api-printing-en-old-small.jpg","normal":"https://example.test/cards/api-printing-en-old-normal.jpg"}',
                    ),
                ],
            )
            connection.commit()

    def _seed_oracle_add_candidates(self, db_path: Path) -> None:
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
                VALUES (?, 'api-add-oracle', 'API Oracle Add Card', ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "api-add-ja",
                        "neo",
                        "Kamigawa: Neon Dynasty",
                        "71",
                        "ja",
                        "2024-02-01",
                        '["foil"]',
                        '{"small":"https://example.test/cards/api-add-ja-small.jpg","normal":"https://example.test/cards/api-add-ja-normal.jpg"}',
                    ),
                    (
                        "api-add-en",
                        "neo",
                        "Kamigawa: Neon Dynasty",
                        "72",
                        "en",
                        "2024-01-01",
                        '["nonfoil","foil"]',
                        '{"small":"https://example.test/cards/api-add-en-small.jpg","normal":"https://example.test/cards/api-add-en-normal.jpg"}',
                    ),
                ],
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

    def _schema_name_from_ref(self, ref: str) -> str:
        return ref.rsplit("/", 1)[-1]

    def test_demo_api_exposes_inventory_item_and_audit_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                health = client.get("/health")
                self.assertEqual(200, health.status_code)
                self.assertEqual("ok", health.json()["status"])
                self.assertTrue(health.json()["auto_migrate"])
                self.assertFalse(health.json()["trusted_actor_headers"])
                self.assertNotIn("db_path", health.json())

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)
                self.assertEqual("personal", created_inventory.json()["slug"])

                search = client.get("/cards/search", params={"query": "API Test"})
                self.assertEqual(200, search.status_code)
                self.assertEqual("api-card-1", search.json()[0]["scryfall_id"])
                self.assertEqual(
                    "https://example.test/cards/api-card-1-small.jpg",
                    search.json()[0]["image_uri_small"],
                )
                self.assertEqual(
                    "https://example.test/cards/api-card-1-normal.jpg",
                    search.json()[0]["image_uri_normal"],
                )

                added = client.post(
                    "/inventories/personal/items",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-add"},
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 2,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "Binder A",
                        "tags": ["demo", "web"],
                    },
                )
                self.assertEqual(201, added.status_code)
                added_payload = added.json()
                self.assertEqual(["demo", "web"], added_payload["tags"])
                self.assertEqual("api-oracle-1", added_payload["oracle_id"])
                self.assertEqual("explicit", added_payload["printing_selection_mode"])
                self.assertEqual("req-add", added.headers["X-Request-Id"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertEqual(1, len(listed.json()))
                self.assertEqual("api-oracle-1", listed.json()[0]["oracle_id"])
                self.assertEqual(2, listed.json()[0]["quantity"])
                self.assertEqual(["normal", "foil"], listed.json()[0]["allowed_finishes"])
                self.assertEqual("explicit", listed.json()[0]["printing_selection_mode"])
                self.assertEqual(
                    "https://example.test/cards/api-card-1-small.jpg",
                    listed.json()[0]["image_uri_small"],
                )
                self.assertEqual(
                    "https://example.test/cards/api-card-1-normal.jpg",
                    listed.json()[0]["image_uri_normal"],
                )

                paged = client.get(
                    "/inventories/personal/items/page",
                    params={"limit": 50, "offset": 0, "sort_key": "name", "sort_direction": "asc"},
                )
                self.assertEqual(200, paged.status_code)
                self.assertEqual("personal", paged.json()["inventory"])
                self.assertEqual(1, paged.json()["total_count"])
                self.assertFalse(paged.json()["has_more"])
                self.assertEqual("name", paged.json()["sort_key"])
                self.assertEqual("api-oracle-1", paged.json()["items"][0]["oracle_id"])

                patched = client.patch(
                    f"/inventories/personal/items/{added_payload['item_id']}",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-finish"},
                    json={"finish": "foil"},
                )
                self.assertEqual(200, patched.status_code)
                self.assertEqual("set_finish", patched.json()["operation"])
                self.assertEqual("foil", patched.json()["finish"])

                audit = client.get(
                    "/inventories/personal/audit",
                    headers={"X-Authenticated-User": "shared-user"},
                )
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_finish", audit.json()[0]["action"])
                self.assertEqual("api", audit.json()[0]["actor_type"])
                self.assertEqual("local-demo", audit.json()[0]["actor_id"])
                self.assertEqual("req-finish", audit.json()[0]["request_id"])
                self.assertRegex(audit.json()[0]["occurred_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_demo_api_inventory_metadata_round_trips_and_add_defaults_apply(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={
                        "slug": "personal",
                        "display_name": "Personal Collection",
                        "description": "Main demo inventory",
                        "default_location": "Trade Binder",
                        "default_tags": "trade, staples",
                        "notes": "Main inventory notes",
                        "acquisition_price": "25.00",
                        "acquisition_currency": "usd",
                    },
                )
                self.assertEqual(201, created_inventory.status_code)
                self.assertEqual(
                    {
                        "inventory_id": 1,
                        "slug": "personal",
                        "display_name": "Personal Collection",
                        "description": "Main demo inventory",
                        "default_location": "Trade Binder",
                        "default_tags": "trade, staples",
                        "notes": "Main inventory notes",
                        "acquisition_price": "25.00",
                        "acquisition_currency": "USD",
                    },
                    created_inventory.json(),
                )

                inventories = client.get("/inventories")
                self.assertEqual(200, inventories.status_code)
                self.assertEqual(
                    [
                        {
                            "slug": "personal",
                            "display_name": "Personal Collection",
                            "description": "Main demo inventory",
                            "default_location": "Trade Binder",
                            "default_tags": "trade, staples",
                            "notes": "Main inventory notes",
                            "acquisition_price": "25",
                            "acquisition_currency": "USD",
                            "item_rows": 0,
                            "total_cards": 0,
                            "role": "admin",
                            "can_read": True,
                            "can_write": True,
                            "can_manage_share": True,
                            "can_transfer_to": True,
                        }
                    ],
                    inventories.json(),
                )

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 2,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)
                self.assertEqual("Trade Binder", added.json()["location"])
                self.assertEqual(["trade", "staples"], added.json()["tags"])

                with connect(db_path) as connection:
                    item_row = connection.execute(
                        "SELECT location, tags_json FROM inventory_items WHERE id = ?",
                        (added.json()["item_id"],),
                    ).fetchone()

                self.assertEqual("Trade Binder", item_row["location"])
                self.assertEqual(["trade", "staples"], json.loads(item_row["tags_json"]))

    def test_demo_api_csv_import_uses_strict_schema_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                with patch(
                    "mtg_source_stack.api.routes.import_csv_stream",
                    return_value={
                        "csv_filename": "inventory_import.csv",
                        "detected_format": "generic_csv",
                        "default_inventory": None,
                        "rows_seen": 0,
                        "rows_written": 0,
                        "ready_to_commit": True,
                        "summary": {
                            "total_card_quantity": 0,
                            "distinct_card_names": 0,
                            "distinct_printings": 0,
                            "requested_card_quantity": 0,
                            "unresolved_card_quantity": 0,
                        },
                        "resolution_issues": [],
                        "dry_run": True,
                        "imported_rows": [],
                    },
                ) as import_csv_stream:
                    response = client.post(
                        "/imports/csv",
                        files={
                            "file": (
                                "inventory_import.csv",
                                b"Inventory,Scryfall ID,Qty\npersonal,api-card-1,1\n",
                                "text/csv",
                            )
                        },
                        data={"dry_run": "true"},
                    )

                self.assertEqual(200, response.status_code)
                self.assertEqual("require_current", import_csv_stream.call_args.kwargs["schema_policy"])

    def test_demo_api_csv_import_supports_preview_and_commit_but_not_implicit_inventory_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                missing_inventory = client.post(
                    "/imports/csv",
                    files={
                        "file": (
                            "inventory_import.csv",
                            (
                                "Collection Name,Scryfall ID,Qty,Cond\n"
                                "Trade Binder,api-card-1,2,NM\n"
                            ).encode("utf-8"),
                            "text/csv",
                        )
                    },
                )
                self.assertEqual(404, missing_inventory.status_code)
                self.assertEqual("not_found", missing_inventory.json()["error"]["code"])

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                csv_body = (
                    "Inventory,Scryfall ID,Qty,Cond,Location,Notes\n"
                    "personal,api-card-1,2,NM,Blue Binder,Imported by API\n"
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    headers={"X-Request-Id": "req-import-preview"},
                    files={"file": ("inventory_import.csv", csv_body, "text/csv")},
                    data={"dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertEqual("inventory_import.csv", preview_payload["csv_filename"])
                self.assertEqual("generic_csv", preview_payload["detected_format"])
                self.assertTrue(preview_payload["dry_run"])
                self.assertEqual(1, preview_payload["rows_seen"])
                self.assertEqual(1, preview_payload["rows_written"])
                self.assertTrue(preview_payload["ready_to_commit"])
                self.assertEqual(2, preview_payload["summary"]["total_card_quantity"])
                self.assertEqual(2, preview_payload["summary"]["requested_card_quantity"])
                self.assertEqual(0, preview_payload["summary"]["unresolved_card_quantity"])
                self.assertEqual(1, preview_payload["summary"]["distinct_card_names"])
                self.assertEqual(1, preview_payload["summary"]["distinct_printings"])
                self.assertEqual([], preview_payload["resolution_issues"])
                self.assertEqual("personal", preview_payload["imported_rows"][0]["inventory"])
                self.assertEqual("Imported by API", preview_payload["imported_rows"][0]["notes"])
                self.assertEqual("req-import-preview", preview.headers["X-Request-Id"])

                with connect(db_path) as connection:
                    self.assertEqual(
                        0,
                        connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0],
                    )

                committed = client.post(
                    "/imports/csv",
                    headers={"X-Request-Id": "req-import-commit"},
                    files={"file": ("inventory_import.csv", csv_body, "text/csv")},
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertFalse(committed_payload["dry_run"])
                self.assertEqual("generic_csv", committed_payload["detected_format"])
                self.assertEqual(1, committed_payload["rows_written"])
                self.assertTrue(committed_payload["ready_to_commit"])
                self.assertEqual(2, committed_payload["summary"]["total_card_quantity"])
                self.assertEqual(2, committed_payload["summary"]["requested_card_quantity"])
                self.assertEqual(0, committed_payload["summary"]["unresolved_card_quantity"])
                self.assertEqual([], committed_payload["resolution_issues"])
                self.assertEqual(2, committed_payload["imported_rows"][0]["quantity"])

                with connect(db_path) as connection:
                    item_row = connection.execute(
                        """
                        SELECT quantity, location, notes
                        FROM inventory_items
                        """
                    ).fetchone()
                    audit_row = connection.execute(
                        """
                        SELECT actor_type, actor_id, request_id
                        FROM inventory_audit_log
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()

                self.assertEqual(2, item_row["quantity"])
                self.assertEqual("Blue Binder", item_row["location"])
                self.assertEqual("Imported by API", item_row["notes"])
                self.assertEqual(("api", "local-demo", "req-import-commit"), tuple(audit_row))

    def test_demo_api_csv_import_returns_resolution_issues_and_accepts_resolutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

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
                            finishes_json,
                            is_default_add_searchable
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                        """,
                        [
                            (
                                "api-csv-amb-1",
                                "api-csv-amb-oracle-1",
                                "API CSV Ambiguous",
                                "tst",
                                "Test Set",
                                "1",
                                "en",
                                '["normal"]',
                            ),
                            (
                                "api-csv-amb-2",
                                "api-csv-amb-oracle-2",
                                "API CSV Ambiguous",
                                "pls",
                                "Plus Set",
                                "2",
                                "en",
                                '["foil"]',
                            ),
                        ],
                    )
                    connection.commit()

                csv_body = (
                    "Inventory,Name,Qty\n"
                    "personal,API CSV Ambiguous,3\n"
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    headers={"X-Request-Id": "req-csv-resolution-preview"},
                    files={"file": ("inventory_import.csv", csv_body, "text/csv")},
                    data={"dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertFalse(preview_payload["ready_to_commit"])
                self.assertEqual(3, preview_payload["summary"]["requested_card_quantity"])
                self.assertEqual(3, preview_payload["summary"]["unresolved_card_quantity"])
                self.assertEqual(1, len(preview_payload["resolution_issues"]))
                issue = preview_payload["resolution_issues"][0]
                self.assertEqual("ambiguous_card_name", issue["kind"])
                self.assertEqual(2, issue["csv_row"])

                unresolved_commit = client.post(
                    "/imports/csv",
                    files={"file": ("inventory_import.csv", csv_body, "text/csv")},
                )
                self.assertEqual(400, unresolved_commit.status_code)
                self.assertIn("resolution_issues", unresolved_commit.json()["error"]["details"])

                committed = client.post(
                    "/imports/csv",
                    headers={"X-Request-Id": "req-csv-resolution-commit"},
                    files={"file": ("inventory_import.csv", csv_body, "text/csv")},
                    data={
                        "resolutions_json": json.dumps(
                            [
                                {
                                    "csv_row": 2,
                                    "scryfall_id": issue["options"][0]["scryfall_id"],
                                    "finish": issue["options"][0]["finish"],
                                }
                            ]
                        )
                    },
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertTrue(committed_payload["ready_to_commit"])
                self.assertEqual([], committed_payload["resolution_issues"])
                self.assertEqual(1, committed_payload["rows_written"])
                self.assertEqual(3, committed_payload["summary"]["total_card_quantity"])

                with connect(db_path) as connection:
                    item_row = connection.execute("SELECT quantity FROM inventory_items").fetchone()
                    audit_row = connection.execute(
                        """
                        SELECT actor_type, actor_id, request_id
                        FROM inventory_audit_log
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()

                self.assertEqual(3, item_row["quantity"])
                self.assertEqual(("api", "local-demo", "req-csv-resolution-commit"), tuple(audit_row))

    def test_demo_api_csv_import_rejects_oversized_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path, csv_import_max_bytes=64) as client:
                csv_body = (
                    "Inventory,Scryfall ID,Qty,Cond,Notes\n"
                    "personal,api-card-1,1,NM,This CSV body is intentionally too large.\n"
                ).encode("utf-8")

                response = client.post(
                    "/imports/csv",
                    files={"file": ("inventory_import.csv", csv_body, "text/csv")},
                )

            self.assertEqual(400, response.status_code)
            self.assertEqual("validation_error", response.json()["error"]["code"])
            self.assertIn("CSV upload must not exceed 64 bytes.", response.json()["error"]["message"])

    def test_demo_api_csv_import_detects_tcgplayer_app_collection_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
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
                            tcgplayer_product_id,
                            finishes_json,
                            image_uris_json
                        )
                        VALUES (
                            'api-card-product',
                            'api-oracle-product',
                            'API Product Card',
                            'tst',
                            'Test Set',
                            '12',
                            'en',
                            '777888',
                            '["normal","foil"]',
                            '{"small":"https://example.test/cards/api-card-product-small.jpg","normal":"https://example.test/cards/api-card-product-normal.jpg"}'
                        )
                        """
                    )
                    connection.commit()

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                csv_body = (
                    "List Name,Product ID,Name,Condition,Language,Printing,Quantity\n"
                    "Personal Collection,777888,API Product Card,Near Mint,English,Non-Foil,3\n"
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    files={"file": ("tcgplayer_app.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal", "dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertEqual("tcgplayer_app_collection_csv", preview_payload["detected_format"])
                self.assertEqual("normal", preview_payload["imported_rows"][0]["finish"])
                self.assertEqual(1, preview_payload["rows_written"])

                committed = client.post(
                    "/imports/csv",
                    files={"file": ("tcgplayer_app.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal"},
                )
                self.assertEqual(200, committed.status_code)
                self.assertEqual("tcgplayer_app_collection_csv", committed.json()["detected_format"])
                self.assertEqual("normal", committed.json()["imported_rows"][0]["finish"])

    def test_demo_api_csv_import_detects_manabox_collection_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
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
                            'api-card-manabox',
                            'api-oracle-manabox',
                            'ManaBox API Card',
                            'tst',
                            'Test Set',
                            '208',
                            'en',
                            '["normal","foil"]',
                            '{"small":"https://example.test/cards/api-card-manabox-small.jpg","normal":"https://example.test/cards/api-card-manabox-normal.jpg"}'
                        )
                        """
                    )
                    connection.commit()

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                csv_body = (
                    "Card Name,Set Name,Card Number,Scryfall ID,Quantity,Foil,Language,Condition,"
                    "Purchase Price,Purchase Currency,Misprint,Altered,Binder Name\n"
                    "ManaBox API Card,Test Set,208,,2,Yes,English,Near Mint,3.25,USD,Yes,No,Commander Binder\n"
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    files={"file": ("manabox_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal", "dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertEqual("manabox_collection_csv", preview_payload["detected_format"])
                self.assertEqual("foil", preview_payload["imported_rows"][0]["finish"])
                self.assertEqual(["misprint"], preview_payload["imported_rows"][0]["tags"])

                committed = client.post(
                    "/imports/csv",
                    files={"file": ("manabox_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal"},
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertEqual("manabox_collection_csv", committed_payload["detected_format"])
                self.assertEqual("foil", committed_payload["imported_rows"][0]["finish"])
                self.assertEqual(["misprint"], committed_payload["imported_rows"][0]["tags"])

    def test_demo_api_csv_import_detects_mtggoldfish_collection_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
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
                            'api-card-mtggoldfish',
                            'api-oracle-mtggoldfish',
                            'MTGGoldfish API Card',
                            '7ed',
                            'Seventh Edition',
                            '1',
                            'en',
                            '["normal","foil"]',
                            '{"small":"https://example.test/cards/api-card-mtggoldfish-small.jpg","normal":"https://example.test/cards/api-card-mtggoldfish-normal.jpg"}'
                        )
                        """
                    )
                    connection.commit()

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                csv_body = (
                    "Card,Set ID,Set Name,Quantity,Foil,Variation\n"
                    "MTGGoldfish API Card,7E,Seventh Edition,2,REGULAR,\n"
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    files={"file": ("mtggoldfish_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal", "dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertEqual("mtggoldfish_collection_csv", preview_payload["detected_format"])
                self.assertEqual("normal", preview_payload["imported_rows"][0]["finish"])

                committed = client.post(
                    "/imports/csv",
                    files={"file": ("mtggoldfish_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal"},
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertEqual("mtggoldfish_collection_csv", committed_payload["detected_format"])
                self.assertEqual("normal", committed_payload["imported_rows"][0]["finish"])

    def test_demo_api_csv_import_detects_deckbox_collection_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
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
                            'api-card-deckbox',
                            'api-oracle-deckbox',
                            'Deckbox API Card',
                            'rtr',
                            'Return to Ravnica',
                            '1',
                            'en',
                            '["normal","foil"]',
                            '{"small":"https://example.test/cards/api-card-deckbox-small.jpg","normal":"https://example.test/cards/api-card-deckbox-normal.jpg"}'
                        )
                        """
                    )
                    connection.commit()

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                csv_body = (
                    "Count,Tradelist Count,Name,Edition,Card Number,Condition,Language,Foil,"
                    "Signed,Artist Proof,Altered Art,Mis\n"
                    "4,4,Deckbox API Card,Return to Ravnica,1,Near Mint,English,foil,Yes,,Yes,Yes\n"
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    files={"file": ("deckbox_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal", "dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertEqual("deckbox_collection_csv", preview_payload["detected_format"])
                self.assertEqual("foil", preview_payload["imported_rows"][0]["finish"])
                self.assertEqual(
                    ["signed", "altered art", "misprint"],
                    preview_payload["imported_rows"][0]["tags"],
                )

                committed = client.post(
                    "/imports/csv",
                    files={"file": ("deckbox_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal"},
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertEqual("deckbox_collection_csv", committed_payload["detected_format"])
                self.assertEqual("foil", committed_payload["imported_rows"][0]["finish"])
                self.assertEqual(
                    ["signed", "altered art", "misprint"],
                    committed_payload["imported_rows"][0]["tags"],
                )

    def test_demo_api_csv_import_detects_deckstats_collection_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
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
                            'api-card-deckstats',
                            'api-oracle-deckstats',
                            'Deckstats API Card',
                            'emn',
                            'Eldritch Moon',
                            '147',
                            'en',
                            '["normal","foil"]',
                            '{"small":"https://example.test/cards/api-card-deckstats-small.jpg","normal":"https://example.test/cards/api-card-deckstats-normal.jpg"}'
                        )
                        """
                    )
                    connection.commit()

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                csv_body = (
                    "amount,card_name,is_foil,is_pinned,set_id,set_code\n"
                    '2,"Deckstats API Card",1,1,147,"EMN"\n'
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    files={"file": ("deckstats_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal", "dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertEqual("deckstats_collection_csv", preview_payload["detected_format"])
                self.assertEqual("foil", preview_payload["imported_rows"][0]["finish"])
                self.assertEqual(["pinned"], preview_payload["imported_rows"][0]["tags"])

                committed = client.post(
                    "/imports/csv",
                    files={"file": ("deckstats_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal"},
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertEqual("deckstats_collection_csv", committed_payload["detected_format"])
                self.assertEqual("foil", committed_payload["imported_rows"][0]["finish"])
                self.assertEqual(["pinned"], committed_payload["imported_rows"][0]["tags"])

    def test_demo_api_csv_import_detects_mtgstocks_collection_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
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
                            'api-card-mtgstocks',
                            'api-oracle-mtgstocks',
                            'MTGStocks API Card',
                            'mma',
                            'Modern Masters',
                            '1',
                            'en',
                            '["normal","foil"]',
                            '{"small":"https://example.test/cards/api-card-mtgstocks-small.jpg","normal":"https://example.test/cards/api-card-mtgstocks-normal.jpg"}'
                        )
                        """
                    )
                    connection.commit()

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                csv_body = (
                    '"Card","Set","Quantity","Price","Condition","Language","Foil","Signed"\n'
                    '"MTGStocks API Card","Modern Masters",2,0.99,NM,en,Yes,Yes\n'
                ).encode("utf-8")

                preview = client.post(
                    "/imports/csv",
                    files={"file": ("mtgstocks_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal", "dry_run": "true"},
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertEqual("mtgstocks_collection_csv", preview_payload["detected_format"])
                self.assertEqual("foil", preview_payload["imported_rows"][0]["finish"])
                self.assertEqual(["signed"], preview_payload["imported_rows"][0]["tags"])
                self.assertIsNone(preview_payload["imported_rows"][0]["acquisition_price"])

                committed = client.post(
                    "/imports/csv",
                    files={"file": ("mtgstocks_collection.csv", csv_body, "text/csv")},
                    data={"default_inventory": "personal"},
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertEqual("mtgstocks_collection_csv", committed_payload["detected_format"])
                self.assertEqual("foil", committed_payload["imported_rows"][0]["finish"])
                self.assertEqual(["signed"], committed_payload["imported_rows"][0]["tags"])
                self.assertIsNone(committed_payload["imported_rows"][0]["acquisition_price"])

    def test_demo_api_decklist_import_supports_preview_and_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                preview = client.post(
                    "/imports/decklist",
                    headers={"X-Request-Id": "req-decklist-preview"},
                    json={
                        "deck_text": "About\nName API Test Deck\n\nDeck\n4 API Test Card",
                        "default_inventory": "personal",
                        "dry_run": True,
                    },
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertTrue(preview_payload["dry_run"])
                self.assertEqual("API Test Deck", preview_payload["deck_name"])
                self.assertEqual(1, preview_payload["rows_seen"])
                self.assertEqual(1, preview_payload["rows_written"])
                self.assertTrue(preview_payload["ready_to_commit"])
                self.assertEqual(4, preview_payload["summary"]["total_card_quantity"])
                self.assertEqual(4, preview_payload["summary"]["requested_card_quantity"])
                self.assertEqual(0, preview_payload["summary"]["unresolved_card_quantity"])
                self.assertEqual({"mainboard": 4}, preview_payload["summary"]["section_card_quantities"])
                self.assertEqual([], preview_payload["resolution_issues"])
                self.assertEqual(5, preview_payload["imported_rows"][0]["decklist_line"])
                self.assertEqual("mainboard", preview_payload["imported_rows"][0]["section"])
                self.assertEqual("personal", preview_payload["imported_rows"][0]["inventory"])
                self.assertEqual("req-decklist-preview", preview.headers["X-Request-Id"])

                with connect(db_path) as connection:
                    self.assertEqual(
                        0,
                        connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0],
                    )

                committed = client.post(
                    "/imports/decklist",
                    headers={"X-Request-Id": "req-decklist-commit"},
                    json={
                        "deck_text": "Commander\n1 API Test Card",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertFalse(committed_payload["dry_run"])
                self.assertIsNone(committed_payload["deck_name"])
                self.assertEqual(1, committed_payload["rows_written"])
                self.assertTrue(committed_payload["ready_to_commit"])
                self.assertEqual(1, committed_payload["summary"]["total_card_quantity"])
                self.assertEqual(1, committed_payload["summary"]["requested_card_quantity"])
                self.assertEqual(0, committed_payload["summary"]["unresolved_card_quantity"])
                self.assertEqual({"commander": 1}, committed_payload["summary"]["section_card_quantities"])
                self.assertEqual([], committed_payload["resolution_issues"])
                self.assertEqual("commander", committed_payload["imported_rows"][0]["section"])

                with connect(db_path) as connection:
                    item_row = connection.execute(
                        "SELECT quantity, finish FROM inventory_items"
                    ).fetchone()
                self.assertEqual(1, item_row["quantity"])
                self.assertEqual("normal", item_row["finish"])

                with connect(db_path) as connection:
                    item_row = connection.execute("SELECT quantity FROM inventory_items").fetchone()
                    audit_row = connection.execute(
                        """
                        SELECT actor_type, actor_id, request_id
                        FROM inventory_audit_log
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()

                self.assertEqual(1, item_row["quantity"])
                self.assertEqual(("api", "local-demo", "req-decklist-commit"), tuple(audit_row))

    def test_demo_api_decklist_import_uses_strict_schema_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                with patch(
                    "mtg_source_stack.api.routes.import_decklist_text",
                    return_value={
                        "deck_name": None,
                        "default_inventory": "personal",
                        "rows_seen": 0,
                        "rows_written": 0,
                        "ready_to_commit": True,
                        "summary": {
                            "total_card_quantity": 0,
                            "distinct_card_names": 0,
                            "distinct_printings": 0,
                            "section_card_quantities": {},
                            "requested_card_quantity": 0,
                            "unresolved_card_quantity": 0,
                        },
                        "resolution_issues": [],
                        "dry_run": True,
                        "imported_rows": [],
                    },
                ) as import_decklist_text:
                    response = client.post(
                        "/imports/decklist",
                        json={
                            "deck_text": "1 API Test Card",
                            "default_inventory": "personal",
                            "dry_run": True,
                        },
                    )

                self.assertEqual(200, response.status_code)
                self.assertEqual("require_current", import_decklist_text.call_args.kwargs["schema_policy"])

    def test_demo_api_decklist_import_returns_resolution_issues_and_accepts_resolutions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-ambiguous-main",
                    oracle_id="api-ambiguous-main-oracle",
                    name="API Ambiguous Card",
                    set_code="lea",
                    set_name="Limited Edition Alpha",
                    collector_number="161",
                    finishes_json='["normal"]',
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-ambiguous-other",
                    oracle_id="api-ambiguous-other-oracle",
                    name="API Ambiguous Card",
                    set_code="2ed",
                    set_name="Unlimited Edition",
                    collector_number="162",
                    finishes_json='["normal"]',
                )

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                preview = client.post(
                    "/imports/decklist",
                    json={
                        "deck_text": "4 API Ambiguous Card",
                        "default_inventory": "personal",
                        "dry_run": True,
                    },
                )
                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertFalse(preview_payload["ready_to_commit"])
                self.assertEqual(0, preview_payload["rows_written"])
                self.assertEqual(4, preview_payload["summary"]["requested_card_quantity"])
                self.assertEqual(4, preview_payload["summary"]["unresolved_card_quantity"])
                self.assertEqual(1, len(preview_payload["resolution_issues"]))
                self.assertEqual("ambiguous_card_name", preview_payload["resolution_issues"][0]["kind"])

                unresolved_commit = client.post(
                    "/imports/decklist",
                    json={
                        "deck_text": "4 API Ambiguous Card",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(400, unresolved_commit.status_code)
                self.assertEqual("validation_error", unresolved_commit.json()["error"]["code"])
                self.assertIn("resolution_issues", unresolved_commit.json()["error"]["details"])

                committed = client.post(
                    "/imports/decklist",
                    json={
                        "deck_text": "4 API Ambiguous Card",
                        "default_inventory": "personal",
                        "resolutions": [
                            {
                                "decklist_line": 1,
                                "scryfall_id": "api-ambiguous-other",
                                "finish": "normal",
                            }
                        ],
                    },
                )
                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertTrue(committed_payload["ready_to_commit"])
                self.assertEqual([], committed_payload["resolution_issues"])
                self.assertEqual("api-ambiguous-other", committed_payload["imported_rows"][0]["scryfall_id"])

    def test_demo_api_deck_url_import_supports_preview_and_commit(self) -> None:
        from mtg_source_stack.inventory.deck_url_import import RemoteDeckCard, RemoteDeckSource

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                preview_source = RemoteDeckSource(
                    provider="archidekt",
                    source_url="https://archidekt.com/decks/123/test",
                    deck_name="Preview Deck",
                    cards=[RemoteDeckCard(1, 4, "mainboard", "api-card-1", "normal")],
                )
                committed_source = RemoteDeckSource(
                    provider="archidekt",
                    source_url="https://archidekt.com/decks/123/test",
                    deck_name="Committed Deck",
                    cards=[RemoteDeckCard(1, 1, "commander", "api-card-1", "normal")],
                )

                with patch(
                    "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                    side_effect=[preview_source, committed_source],
                ):
                    preview = client.post(
                        "/imports/deck-url",
                        headers={"X-Request-Id": "req-deck-url-preview"},
                        json={
                            "source_url": "https://archidekt.com/decks/123/test",
                            "default_inventory": "personal",
                            "dry_run": True,
                        },
                    )
                    self.assertEqual(200, preview.status_code)
                    preview_payload = preview.json()
                    self.assertTrue(preview_payload["dry_run"])
                    self.assertEqual("archidekt", preview_payload["provider"])
                    self.assertEqual("Preview Deck", preview_payload["deck_name"])
                    self.assertEqual(1, preview_payload["rows_seen"])
                    self.assertEqual(1, preview_payload["rows_written"])
                    self.assertTrue(preview_payload["ready_to_commit"])
                    self.assertIsInstance(preview_payload["source_snapshot_token"], str)
                    self.assertEqual(4, preview_payload["summary"]["total_card_quantity"])
                    self.assertEqual(4, preview_payload["summary"]["requested_card_quantity"])
                    self.assertEqual(0, preview_payload["summary"]["unresolved_card_quantity"])
                    self.assertEqual({"mainboard": 4}, preview_payload["summary"]["section_card_quantities"])
                    self.assertEqual([], preview_payload["resolution_issues"])
                    self.assertEqual(1, preview_payload["imported_rows"][0]["source_position"])
                    self.assertEqual("mainboard", preview_payload["imported_rows"][0]["section"])
                    self.assertEqual("req-deck-url-preview", preview.headers["X-Request-Id"])

                    with connect(db_path) as connection:
                        self.assertEqual(
                            0,
                            connection.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0],
                        )

                    committed = client.post(
                        "/imports/deck-url",
                        headers={"X-Request-Id": "req-deck-url-commit"},
                        json={
                            "source_url": "https://archidekt.com/decks/123/test",
                            "default_inventory": "personal",
                            "source_snapshot_token": preview_payload["source_snapshot_token"],
                        },
                    )

                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertFalse(committed_payload["dry_run"])
                self.assertEqual("Preview Deck", committed_payload["deck_name"])
                self.assertTrue(committed_payload["ready_to_commit"])
                self.assertEqual(4, committed_payload["summary"]["total_card_quantity"])
                self.assertEqual(4, committed_payload["summary"]["requested_card_quantity"])
                self.assertEqual(0, committed_payload["summary"]["unresolved_card_quantity"])
                self.assertEqual({"mainboard": 4}, committed_payload["summary"]["section_card_quantities"])
                self.assertEqual([], committed_payload["resolution_issues"])
                self.assertEqual(1, committed_payload["imported_rows"][0]["source_position"])
                self.assertEqual("mainboard", committed_payload["imported_rows"][0]["section"])

                with connect(db_path) as connection:
                    item_row = connection.execute("SELECT quantity FROM inventory_items").fetchone()
                    audit_row = connection.execute(
                        """
                        SELECT actor_type, actor_id, request_id
                        FROM inventory_audit_log
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ).fetchone()

                self.assertEqual(4, item_row["quantity"])
                self.assertEqual(("api", "local-demo", "req-deck-url-commit"), tuple(audit_row))

    def test_demo_api_deck_url_import_reports_unknown_cards_without_blocking_known_rows(self) -> None:
        from mtg_source_stack.inventory.deck_url_import import RemoteDeckCard, RemoteDeckSource

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-known-card",
                    oracle_id="api-known-oracle",
                    name="Known Card",
                    set_code="tst",
                    set_name="Test Set",
                    collector_number="10",
                    finishes_json='["normal"]',
                )

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                remote_source = RemoteDeckSource(
                    provider="archidekt",
                    source_url="https://archidekt.com/decks/15761099/counters_and_counters",
                    deck_name="Counters and Counters",
                    cards=[
                        RemoteDeckCard(1, 2, "mainboard", "api-known-card", "normal"),
                        RemoteDeckCard(
                            227,
                            1,
                            "mainboard",
                            "stale-wildgrowth-id",
                            "normal",
                            name="Wildgrowth Archaic",
                            set_code="TST",
                            collector_number="168",
                        ),
                    ],
                )

                with patch(
                    "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                    return_value=remote_source,
                ):
                    committed = client.post(
                        "/imports/deck-url",
                        json={
                            "source_url": "https://archidekt.com/decks/15761099/counters_and_counters",
                            "default_inventory": "personal",
                        },
                    )

                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertTrue(committed_payload["ready_to_commit"])
                self.assertEqual(1, committed_payload["rows_written"])
                self.assertEqual(1, len(committed_payload["resolution_issues"]))
                self.assertEqual("unknown_card", committed_payload["resolution_issues"][0]["kind"])
                self.assertEqual(
                    "Wildgrowth Archaic",
                    committed_payload["resolution_issues"][0]["requested"]["name"],
                )
                self.assertEqual(
                    "stale-wildgrowth-id",
                    committed_payload["resolution_issues"][0]["requested"]["scryfall_id"],
                )

                with connect(db_path) as connection:
                    rows = connection.execute(
                        "SELECT scryfall_id, quantity FROM inventory_items ORDER BY scryfall_id"
                    ).fetchall()

                self.assertEqual([("api-known-card", 2)], [(row["scryfall_id"], row["quantity"]) for row in rows])

    def test_demo_api_deck_url_import_uses_strict_schema_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                with patch(
                    "mtg_source_stack.api.routes.import_deck_url",
                    return_value={
                        "source_url": "https://archidekt.com/decks/123/test",
                        "provider": "archidekt",
                        "deck_name": None,
                        "default_inventory": "personal",
                        "rows_seen": 0,
                        "rows_written": 0,
                        "ready_to_commit": True,
                        "source_snapshot_token": "snapshot-token",
                        "summary": {
                            "total_card_quantity": 0,
                            "distinct_card_names": 0,
                            "distinct_printings": 0,
                            "section_card_quantities": {},
                            "requested_card_quantity": 0,
                            "unresolved_card_quantity": 0,
                        },
                        "resolution_issues": [],
                        "dry_run": True,
                        "imported_rows": [],
                    },
                ) as import_deck_url:
                    response = client.post(
                        "/imports/deck-url",
                        json={
                            "source_url": "https://archidekt.com/decks/123/test",
                            "default_inventory": "personal",
                            "dry_run": True,
                        },
                    )

                self.assertEqual(200, response.status_code)
                self.assertEqual("require_current", import_deck_url.call_args.kwargs["schema_policy"])

    def test_demo_api_deck_url_import_returns_resolution_issues_and_uses_snapshot_token(self) -> None:
        from mtg_source_stack.inventory.deck_url_import import RemoteDeckCard, RemoteDeckSource

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-remote-main",
                    oracle_id="api-remote-main-oracle",
                    name="API Remote Ambiguous Card",
                    set_code="lea",
                    set_name="Limited Edition Alpha",
                    collector_number="161",
                    finishes_json='["normal"]',
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-remote-other",
                    oracle_id="api-remote-other-oracle",
                    name="API Remote Ambiguous Card",
                    set_code="2ed",
                    set_name="Unlimited Edition",
                    collector_number="162",
                    finishes_json='["normal"]',
                )

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                remote_source = RemoteDeckSource(
                    provider="aetherhub",
                    source_url="https://aetherhub.com/Deck/ambiguous",
                    deck_name="Ambiguous URL Deck",
                    cards=[
                        RemoteDeckCard(
                            9,
                            2,
                            "mainboard",
                            None,
                            "normal",
                            name="API Remote Ambiguous Card",
                        )
                    ],
                )

                with patch(
                    "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                    return_value=remote_source,
                ) as fetch_remote_deck_source:
                    preview = client.post(
                        "/imports/deck-url",
                        json={
                            "source_url": "https://aetherhub.com/Deck/ambiguous",
                            "default_inventory": "personal",
                            "dry_run": True,
                        },
                    )
                    self.assertEqual(200, preview.status_code)
                    preview_payload = preview.json()
                    self.assertFalse(preview_payload["ready_to_commit"])
                    self.assertEqual(0, preview_payload["rows_written"])
                    self.assertEqual(2, preview_payload["summary"]["requested_card_quantity"])
                    self.assertEqual(2, preview_payload["summary"]["unresolved_card_quantity"])
                    self.assertEqual(1, len(preview_payload["resolution_issues"]))
                    self.assertEqual(9, preview_payload["resolution_issues"][0]["source_position"])
                    self.assertIsInstance(preview_payload["source_snapshot_token"], str)

                    unresolved_commit = client.post(
                        "/imports/deck-url",
                        json={
                            "source_url": "https://aetherhub.com/Deck/ambiguous",
                            "default_inventory": "personal",
                            "source_snapshot_token": preview_payload["source_snapshot_token"],
                        },
                    )
                    self.assertEqual(400, unresolved_commit.status_code)
                    self.assertEqual("validation_error", unresolved_commit.json()["error"]["code"])
                    self.assertIn("resolution_issues", unresolved_commit.json()["error"]["details"])
                    self.assertIn("source_snapshot_token", unresolved_commit.json()["error"]["details"])

                    committed = client.post(
                        "/imports/deck-url",
                        json={
                            "source_url": "https://aetherhub.com/Deck/ambiguous",
                            "default_inventory": "personal",
                            "source_snapshot_token": preview_payload["source_snapshot_token"],
                            "resolutions": [
                                {
                                    "source_position": 9,
                                    "scryfall_id": "api-remote-other",
                                    "finish": "normal",
                                }
                            ],
                        },
                    )

                self.assertEqual(200, committed.status_code)
                committed_payload = committed.json()
                self.assertTrue(committed_payload["ready_to_commit"])
                self.assertEqual([], committed_payload["resolution_issues"])
                self.assertEqual("api-remote-other", committed_payload["imported_rows"][0]["scryfall_id"])
                self.assertEqual(1, fetch_remote_deck_source.call_count)

    def test_demo_api_deck_url_snapshot_token_uses_configured_signing_secret(self) -> None:
        from mtg_source_stack.inventory.deck_url_import import RemoteDeckCard, RemoteDeckSource

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path, snapshot_signing_secret="api-custom-secret") as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                with patch(
                    "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                    return_value=RemoteDeckSource(
                        provider="archidekt",
                        source_url="https://archidekt.com/decks/123/test",
                        deck_name="Signed Deck",
                        cards=[RemoteDeckCard(1, 1, "mainboard", "api-card-1", "normal")],
                    ),
                ):
                    preview = client.post(
                        "/imports/deck-url",
                        json={
                            "source_url": "https://archidekt.com/decks/123/test",
                            "default_inventory": "personal",
                            "dry_run": True,
                        },
                    )

                self.assertEqual(200, preview.status_code)
                preview_payload = preview.json()
                self.assertIsInstance(preview_payload["source_snapshot_token"], str)

                with self.assertRaisesRegex(ValidationError, "source_snapshot_token is invalid."):
                    import_deck_url(
                        db_path,
                        source_url="https://archidekt.com/decks/123/test",
                        default_inventory="personal",
                        source_snapshot_token=preview_payload["source_snapshot_token"],
                        snapshot_signing_secret="wrong-secret",
                    )

    def test_demo_api_export_csv_route_returns_filtered_download(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 2,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "Binder A",
                        "tags": ["demo"],
                    },
                )
                self.assertEqual(201, added.status_code)

                export_response = client.get(
                    "/inventories/personal/export.csv",
                    params={"provider": "tcgplayer", "profile": "default", "query": "API Test"},
                )
                self.assertEqual(200, export_response.status_code)
                self.assertEqual("text/csv; charset=utf-8", export_response.headers["content-type"])
                self.assertIn(
                    'attachment; filename="personal-default-export.csv"',
                    export_response.headers["content-disposition"],
                )
                self.assertIn("inventory,provider,item_id,scryfall_id,card_name", export_response.text)
                self.assertIn("API Test Card", export_response.text)
                self.assertIn("Binder A", export_response.text)

    def test_demo_api_normalizes_blank_location_to_null_in_mutation_owned_and_audit_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-add-blank"},
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "",
                    },
                )
                self.assertEqual(201, added.status_code)
                self.assertIsNone(added.json()["location"])
                item_id = added.json()["item_id"]

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertEqual(1, len(listed.json()))
                self.assertIsNone(listed.json()[0]["location"])

                set_location = client.patch(
                    f"/inventories/personal/items/{item_id}",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-set-binder"},
                    json={"location": "Binder A"},
                )
                self.assertEqual(200, set_location.status_code)
                self.assertEqual("set_location", set_location.json()["operation"])
                self.assertIsNone(set_location.json()["old_location"])
                self.assertEqual("Binder A", set_location.json()["location"])

                clear_location = client.patch(
                    f"/inventories/personal/items/{item_id}",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-clear-binder"},
                    json={"location": ""},
                )
                self.assertEqual(200, clear_location.status_code)
                self.assertEqual("set_location", clear_location.json()["operation"])
                self.assertEqual("Binder A", clear_location.json()["old_location"])
                self.assertIsNone(clear_location.json()["location"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_location", audit.json()[0]["action"])
                self.assertEqual("Binder A", audit.json()[0]["before"]["location"])
                self.assertIsNone(audit.json()[0]["after"]["location"])
                self.assertEqual("set_location", audit.json()[1]["action"])
                self.assertIsNone(audit.json()[1]["before"]["location"])
                self.assertEqual("Binder A", audit.json()[1]["after"]["location"])
                self.assertEqual("add_card", audit.json()[2]["action"])
                self.assertIsNone(audit.json()[2]["after"]["location"])

    def test_demo_api_exposes_name_search_and_oracle_printings_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_oracle_printings(db_path)

                name_search = client.get("/cards/search/names", params={"query": "API Lookup"})
                self.assertEqual(200, name_search.status_code)
                self.assertEqual(1, name_search.json()["total_count"])
                self.assertFalse(name_search.json()["has_more"])
                self.assertEqual(1, len(name_search.json()["items"]))
                self.assertEqual("api-oracle-lookup", name_search.json()["items"][0]["oracle_id"])
                self.assertEqual(["en", "ja"], name_search.json()["items"][0]["available_languages"])
                self.assertEqual(
                    "https://example.test/cards/api-printing-en-new-small.jpg",
                    name_search.json()["items"][0]["image_uri_small"],
                )

                default_printings = client.get("/cards/oracle/api-oracle-lookup/printings")
                self.assertEqual(200, default_printings.status_code)
                self.assertEqual(
                    ["api-printing-en-new", "api-printing-en-old"],
                    [row["scryfall_id"] for row in default_printings.json()],
                )
                self.assertEqual([True, False], [row["is_default_add_choice"] for row in default_printings.json()])

                all_printings = client.get(
                    "/cards/oracle/api-oracle-lookup/printings",
                    params={"lang": "all"},
                )
                self.assertEqual(200, all_printings.status_code)
                self.assertEqual(
                    ["api-printing-en-new", "api-printing-en-old", "api-printing-ja"],
                    [row["scryfall_id"] for row in all_printings.json()],
                )
                self.assertEqual([True, False, False], [row["is_default_add_choice"] for row in all_printings.json()])

                japanese_printings = client.get(
                    "/cards/oracle/api-oracle-lookup/printings",
                    params={"lang": "ja"},
                )
                self.assertEqual(200, japanese_printings.status_code)
                self.assertEqual(["api-printing-ja"], [row["scryfall_id"] for row in japanese_printings.json()])
                self.assertEqual([True], [row["is_default_add_choice"] for row in japanese_printings.json()])

                missing = client.get("/cards/oracle/missing-oracle/printings")
                self.assertEqual(404, missing.status_code)
                self.assertEqual("not_found", missing.json()["error"]["code"])

    def test_demo_api_exposes_oracle_printings_summary_for_quick_add(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_oracle_printings(db_path)

                summary = client.get("/cards/oracle/api-oracle-lookup/printings/summary")
                self.assertEqual(200, summary.status_code)
                self.assertEqual("api-oracle-lookup", summary.json()["oracle_id"])
                self.assertEqual("api-printing-en-new", summary.json()["default_printing"]["scryfall_id"])
                self.assertEqual(["en", "ja"], summary.json()["available_languages"])
                self.assertEqual(3, summary.json()["printings_count"])
                self.assertTrue(summary.json()["has_more_printings"])
                self.assertEqual(
                    ["api-printing-en-new", "api-printing-en-old"],
                    [row["scryfall_id"] for row in summary.json()["printings"]],
                )
                self.assertEqual([True, False], [row["is_default_add_choice"] for row in summary.json()["printings"]])

                missing = client.get("/cards/oracle/missing-oracle/printings/summary")
                self.assertEqual(404, missing.status_code)
                self.assertEqual("not_found", missing.json()["error"]["code"])

    def test_demo_api_oracle_printings_lookup_leaves_default_choice_unset_when_normal_quick_add_would_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-foil-only-printing",
                    oracle_id="api-foil-only-oracle",
                    name="API Foil Only Card",
                    set_code="neo",
                    set_name="Kamigawa: Neon Dynasty",
                    collector_number="99",
                    lang="en",
                    finishes_json='["foil"]',
                    set_type="expansion",
                    booster=1,
                )

                printings = client.get("/cards/oracle/api-foil-only-oracle/printings")
                self.assertEqual(200, printings.status_code)
                self.assertEqual(["api-foil-only-printing"], [row["scryfall_id"] for row in printings.json()])
                self.assertEqual([False], [row["is_default_add_choice"] for row in printings.json()])

    def test_demo_api_set_printing_changes_to_a_sibling_printing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-printing-old",
                    oracle_id="api-printing-oracle",
                    name="API Printing Card",
                    set_code="old",
                    set_name="Old Set",
                    collector_number="7",
                    lang="en",
                    finishes_json='["normal"]',
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-printing-new",
                    oracle_id="api-printing-oracle",
                    name="API Printing Card",
                    set_code="sld",
                    set_name="Secret Lair",
                    collector_number="8",
                    lang="ja",
                    finishes_json='["foil"]',
                )

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-add-printing"},
                    json={
                        "scryfall_id": "api-printing-old",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)
                item_id = added.json()["item_id"]

                changed = client.patch(
                    f"/inventories/personal/items/{item_id}/printing",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-set-printing"},
                    json={"scryfall_id": "api-printing-new"},
                )
                self.assertEqual(200, changed.status_code)
                self.assertEqual("set_printing", changed.json()["operation"])
                self.assertEqual("api-printing-old", changed.json()["old_scryfall_id"])
                self.assertEqual("normal", changed.json()["old_finish"])
                self.assertEqual("en", changed.json()["old_language_code"])
                self.assertEqual("api-printing-new", changed.json()["scryfall_id"])
                self.assertEqual("api-printing-oracle", changed.json()["oracle_id"])
                self.assertEqual("foil", changed.json()["finish"])
                self.assertEqual("ja", changed.json()["language_code"])
                self.assertEqual("explicit", changed.json()["printing_selection_mode"])
                self.assertFalse(changed.json()["merged"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_printing", audit.json()[0]["action"])
                self.assertEqual("api-printing-old", audit.json()[0]["metadata"]["old_scryfall_id"])
                self.assertEqual("api-printing-new", audit.json()[0]["metadata"]["new_scryfall_id"])
                self.assertTrue(audit.json()[0]["metadata"]["auto_selected_finish"])

    def test_demo_api_set_printing_reports_conflict_without_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-printing-source",
                    oracle_id="api-printing-oracle-merge",
                    name="API Merge Printing Card",
                    set_code="old",
                    collector_number="1",
                    finishes_json='["normal"]',
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-printing-target",
                    oracle_id="api-printing-oracle-merge",
                    name="API Merge Printing Card",
                    set_code="new",
                    collector_number="2",
                    finishes_json='["normal"]',
                )

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                source = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-printing-source",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "Binder A",
                    },
                )
                self.assertEqual(201, source.status_code)
                target = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-printing-target",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "Binder A",
                    },
                )
                self.assertEqual(201, target.status_code)

                conflict = client.patch(
                    f"/inventories/personal/items/{source.json()['item_id']}/printing",
                    json={"scryfall_id": "api-printing-target"},
                )
                self.assertEqual(409, conflict.status_code)
                self.assertEqual("conflict", conflict.json()["error"]["code"])
                self.assertIn("Changing printing would collide", conflict.json()["error"]["message"])

    def test_demo_api_set_printing_rejects_same_printing_finish_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-printing-same-id",
                    oracle_id="api-printing-same-id-oracle",
                    name="API Same Printing Card",
                    set_code="lea",
                    collector_number="7",
                    finishes_json='["normal","foil"]',
                )

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-printing-same-id",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)
                item_id = added.json()["item_id"]

                changed = client.patch(
                    f"/inventories/personal/items/{item_id}/printing",
                    json={"scryfall_id": "api-printing-same-id", "finish": "foil"},
                )
                self.assertEqual(400, changed.status_code)
                self.assertEqual("validation_error", changed.json()["error"]["code"])
                self.assertIn("finish and language stay unchanged", changed.json()["error"]["message"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertEqual(1, len(listed.json()))
                self.assertEqual("normal", listed.json()[0]["finish"])
                self.assertEqual("explicit", listed.json()[0]["printing_selection_mode"])

    def test_demo_api_filters_default_add_scope_for_catalog_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-scope-allowed",
                    oracle_id="api-scope-allowed-oracle",
                    name="API Scope Probe Card",
                    collector_number="21",
                    layout="reversible_card",
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-scope-excluded",
                    oracle_id="api-scope-excluded-oracle",
                    name="API Scope Probe Token",
                    collector_number="22",
                    layout="token",
                    is_default_add_searchable=0,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-scoped-ja",
                    oracle_id="api-scoped-oracle",
                    name="API Scoped Lookup Card",
                    collector_number="31",
                    lang="ja",
                    released_at="2026-04-01",
                    image_uris_json='{"small":"https://example.test/cards/api-scoped-ja-small.jpg","normal":"https://example.test/cards/api-scoped-ja-normal.jpg"}',
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-scoped-en-excluded",
                    oracle_id="api-scoped-oracle",
                    name="API Scoped Lookup Card",
                    collector_number="32",
                    lang="en",
                    released_at="2026-05-01",
                    image_uris_json='{"small":"https://example.test/cards/api-scoped-en-small.jpg","normal":"https://example.test/cards/api-scoped-en-normal.jpg"}',
                    is_default_add_searchable=0,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-excluded-only",
                    oracle_id="api-excluded-only-oracle",
                    name="API Excluded Only Card",
                    collector_number="41",
                    layout="emblem",
                    is_default_add_searchable=0,
                )

                search = client.get("/cards/search", params={"query": "API Scope Probe"})
                self.assertEqual(200, search.status_code)
                self.assertEqual(["api-scope-allowed"], [row["scryfall_id"] for row in search.json()])

                name_search = client.get("/cards/search/names", params={"query": "API Scoped Lookup"})
                self.assertEqual(200, name_search.status_code)
                self.assertEqual(1, name_search.json()["total_count"])
                self.assertFalse(name_search.json()["has_more"])
                self.assertEqual(1, len(name_search.json()["items"]))
                self.assertEqual("api-scoped-oracle", name_search.json()["items"][0]["oracle_id"])
                self.assertEqual(1, name_search.json()["items"][0]["printings_count"])
                self.assertEqual(["ja"], name_search.json()["items"][0]["available_languages"])
                self.assertEqual(
                    "https://example.test/cards/api-scoped-ja-small.jpg",
                    name_search.json()["items"][0]["image_uri_small"],
                )

                default_printings = client.get("/cards/oracle/api-scoped-oracle/printings")
                self.assertEqual(200, default_printings.status_code)
                self.assertEqual(["api-scoped-ja"], [row["scryfall_id"] for row in default_printings.json()])

                all_printings = client.get(
                    "/cards/oracle/api-scoped-oracle/printings",
                    params={"lang": "all"},
                )
                self.assertEqual(200, all_printings.status_code)
                self.assertEqual(["api-scoped-ja"], [row["scryfall_id"] for row in all_printings.json()])

                search_all = client.get(
                    "/cards/search",
                    params={"query": "API Scope Probe", "scope": "all"},
                )
                self.assertEqual(200, search_all.status_code)
                self.assertEqual(
                    ["api-scope-allowed", "api-scope-excluded"],
                    [row["scryfall_id"] for row in search_all.json()],
                )

                name_search_all = client.get(
                    "/cards/search/names",
                    params={"query": "API Scoped Lookup", "scope": "all"},
                )
                self.assertEqual(200, name_search_all.status_code)
                self.assertEqual(1, name_search_all.json()["total_count"])
                self.assertFalse(name_search_all.json()["has_more"])
                self.assertEqual(1, len(name_search_all.json()["items"]))
                self.assertEqual(2, name_search_all.json()["items"][0]["printings_count"])
                self.assertEqual(["en", "ja"], name_search_all.json()["items"][0]["available_languages"])
                self.assertEqual(
                    "https://example.test/cards/api-scoped-en-small.jpg",
                    name_search_all.json()["items"][0]["image_uri_small"],
                )

                default_printings_all_scope = client.get(
                    "/cards/oracle/api-scoped-oracle/printings",
                    params={"scope": "all"},
                )
                self.assertEqual(200, default_printings_all_scope.status_code)
                self.assertEqual(
                    ["api-scoped-en-excluded"],
                    [row["scryfall_id"] for row in default_printings_all_scope.json()],
                )

                all_printings_all_scope = client.get(
                    "/cards/oracle/api-scoped-oracle/printings",
                    params={"lang": "all", "scope": "all"},
                )
                self.assertEqual(200, all_printings_all_scope.status_code)
                self.assertEqual(
                    ["api-scoped-en-excluded", "api-scoped-ja"],
                    [row["scryfall_id"] for row in all_printings_all_scope.json()],
                )

                excluded = client.get("/cards/oracle/api-excluded-only-oracle/printings")
                self.assertEqual(404, excluded.status_code)
                self.assertEqual("not_found", excluded.json()["error"]["code"])

                excluded_all_scope = client.get(
                    "/cards/oracle/api-excluded-only-oracle/printings",
                    params={"scope": "all"},
                )
                self.assertEqual(200, excluded_all_scope.status_code)
                self.assertEqual(["api-excluded-only"], [row["scryfall_id"] for row in excluded_all_scope.json()])

    def test_demo_api_grouped_name_search_supports_exact_and_selective_substring_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-exact-group-en",
                    oracle_id="api-exact-group-oracle",
                    name="Exact API Group Card",
                    collector_number="51",
                    lang="en",
                    released_at="2026-04-01",
                    image_uris_json='{"small":"https://example.test/cards/api-exact-group-en-small.jpg","normal":"https://example.test/cards/api-exact-group-en-normal.jpg"}',
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-exact-group-ja",
                    oracle_id="api-exact-group-oracle",
                    name="Exact API Group Card",
                    collector_number="52",
                    lang="ja",
                    released_at="2026-05-01",
                    image_uris_json='{"small":"https://example.test/cards/api-exact-group-ja-small.jpg","normal":"https://example.test/cards/api-exact-group-ja-normal.jpg"}',
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-lightning-bolt-en",
                    oracle_id="api-lightning-bolt-oracle",
                    name="Lightning Bolt",
                    collector_number="61",
                    lang="en",
                    released_at="2026-04-01",
                    is_default_add_searchable=1,
                )

                exact = client.get(
                    "/cards/search/names",
                    params={"query": "Exact API Group Card", "exact": "true"},
                )
                self.assertEqual(200, exact.status_code)
                self.assertEqual(1, exact.json()["total_count"])
                self.assertFalse(exact.json()["has_more"])
                self.assertEqual(1, len(exact.json()["items"]))
                self.assertEqual("api-exact-group-oracle", exact.json()["items"][0]["oracle_id"])
                self.assertEqual(["en", "ja"], exact.json()["items"][0]["available_languages"])
                self.assertEqual(
                    "https://example.test/cards/api-exact-group-en-small.jpg",
                    exact.json()["items"][0]["image_uri_small"],
                )

                substring = client.get(
                    "/cards/search/names",
                    params={"query": "ightn"},
                )
                self.assertEqual(200, substring.status_code)
                self.assertEqual(1, substring.json()["total_count"])
                self.assertFalse(substring.json()["has_more"])
                self.assertEqual(1, len(substring.json()["items"]))
                self.assertEqual("api-lightning-bolt-oracle", substring.json()["items"][0]["oracle_id"])
                self.assertEqual("Lightning Bolt", substring.json()["items"][0]["name"])

                short_substring = client.get(
                    "/cards/search/names",
                    params={"query": "ning"},
                )
                self.assertEqual(200, short_substring.status_code)
                self.assertEqual(0, short_substring.json()["total_count"])
                self.assertFalse(short_substring.json()["has_more"])
                self.assertEqual([], short_substring.json()["items"])

    def test_demo_api_grouped_name_search_substring_fallback_respects_requested_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                for index in range(12):
                    self._insert_catalog_card(
                        db_path,
                        scryfall_id=f"api-substring-limit-{index}",
                        oracle_id=f"api-substring-limit-oracle-{index}",
                        name=f"AlphaXYZBeta Card {index}",
                        collector_number=str(90 + index),
                        is_default_add_searchable=1,
                    )

                response = client.get(
                    "/cards/search/names",
                    params={"query": "haxyzbe", "limit": 11},
                )
                self.assertEqual(200, response.status_code)
                self.assertEqual(12, response.json()["total_count"])
                self.assertTrue(response.json()["has_more"])
                self.assertEqual(11, len(response.json()["items"]))

    def test_demo_api_grouped_name_search_only_uses_infix_fallback_after_fts_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-bolt-token-match",
                    oracle_id="api-bolt-token-oracle",
                    name="Lightning Bolt",
                    collector_number="65",
                    lang="en",
                    released_at="2026-04-01",
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-bolt-infix-only",
                    oracle_id="api-bolt-infix-oracle",
                    name="Thunderbolt",
                    collector_number="66",
                    lang="en",
                    released_at="2026-04-02",
                    is_default_add_searchable=1,
                )

                response = client.get("/cards/search/names", params={"query": "bolt"})
                self.assertEqual(200, response.status_code)
                self.assertEqual(1, response.json()["total_count"])
                self.assertFalse(response.json()["has_more"])
                self.assertEqual(
                    ["Lightning Bolt"],
                    [row["name"] for row in response.json()["items"]],
                )

    def test_demo_api_grouped_name_search_uses_popularity_within_lexical_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-lightning-angel",
                    oracle_id="api-lightning-angel-oracle",
                    name="Lightning Angel",
                    collector_number="71",
                    edhrec_rank=5000,
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-lightning-bolt-ranked",
                    oracle_id="api-lightning-bolt-ranked-oracle",
                    name="Lightning Bolt",
                    collector_number="72",
                    edhrec_rank=100,
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-lightning-cloud",
                    oracle_id="api-lightning-cloud-oracle",
                    name="Lightning Cloud",
                    collector_number="73",
                    edhrec_rank=None,
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-thunder-lightning",
                    oracle_id="api-thunder-lightning-oracle",
                    name="Thunder Lightning",
                    collector_number="74",
                    edhrec_rank=1,
                    is_default_add_searchable=1,
                )

                response = client.get("/cards/search/names", params={"query": "lightn"})
                self.assertEqual(200, response.status_code)
                self.assertEqual(4, response.json()["total_count"])
                self.assertFalse(response.json()["has_more"])
                self.assertEqual(
                    [
                        "Lightning Bolt",
                        "Lightning Angel",
                        "Lightning Cloud",
                        "Thunder Lightning",
                    ],
                    [row["name"] for row in response.json()["items"]],
                )

    def test_demo_api_grouped_name_search_prefers_exact_leading_name_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-cloud-key",
                    oracle_id="api-cloud-key-oracle",
                    name="Cloud Key",
                    collector_number="81",
                    edhrec_rank=657,
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-cloud-midgar-mercenary",
                    oracle_id="api-cloud-midgar-mercenary-oracle",
                    name="Cloud, Midgar Mercenary",
                    collector_number="82",
                    edhrec_rank=2010,
                    is_default_add_searchable=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-cloud-manta",
                    oracle_id="api-cloud-manta-oracle",
                    name="Cloud Manta",
                    collector_number="83",
                    edhrec_rank=100,
                    is_default_add_searchable=1,
                )

                response = client.get("/cards/search/names", params={"query": "cloud"})
                self.assertEqual(200, response.status_code)
                self.assertEqual(3, response.json()["total_count"])
                self.assertFalse(response.json()["has_more"])
                self.assertEqual(
                    [
                        "Cloud, Midgar Mercenary",
                        "Cloud Manta",
                        "Cloud Key",
                    ],
                    [row["name"] for row in response.json()["items"]],
                )

    def test_demo_api_bulk_tag_mutation_updates_multiple_rows_and_writes_grouped_audit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal","foil"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="normal",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="foil",
                    location="Binder B",
                    tags_json='["foil"]',
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-demo"},
                    json={
                        "operation": "add_tags",
                        "item_ids": item_ids,
                        "tags": ["trade", "deck"],
                    },
                )
                self.assertEqual(200, bulk.status_code)
                self.assertEqual("personal", bulk.json()["inventory"])
                self.assertEqual("add_tags", bulk.json()["operation"])
                self.assertEqual(item_ids, bulk.json()["requested_item_ids"])
                self.assertEqual(item_ids, bulk.json()["updated_item_ids"])
                self.assertEqual(2, bulk.json()["updated_count"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual(["trade", "deck"], rows_by_id[item_ids[0]]["tags"])
                self.assertEqual(["foil", "trade", "deck"], rows_by_id[item_ids[1]]["tags"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("add_tags", audit.json()[0]["action"])
                self.assertEqual("add_tags", audit.json()[1]["action"])
                self.assertTrue(audit.json()[0]["metadata"]["bulk_operation"])
                self.assertEqual("add_tags", audit.json()[0]["metadata"]["bulk_kind"])
                self.assertEqual(2, audit.json()[0]["metadata"]["bulk_count"])
                self.assertEqual(2, audit.json()[0]["metadata"]["updated_count"])
                self.assertEqual("req-bulk-demo", audit.json()[0]["request_id"])

    def test_demo_api_bulk_tag_mutation_rejects_duplicate_item_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                )
                with connect(db_path) as connection:
                    item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

                duplicate = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "add_tags",
                        "item_ids": [item_id, item_id],
                        "tags": ["trade"],
                    },
                )
                self.assertEqual(400, duplicate.status_code)
                self.assertEqual("validation_error", duplicate.json()["error"]["code"])
                self.assertIn("must not contain duplicates", duplicate.json()["error"]["message"])

    def test_demo_api_bulk_tag_mutation_rejects_unrelated_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                )
                with connect(db_path) as connection:
                    item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

                invalid = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "add_tags",
                        "item_ids": [item_id],
                        "tags": ["trade"],
                        "quantity": 2,
                    },
                )
                self.assertEqual(400, invalid.status_code)
                self.assertEqual("validation_error", invalid.json()["error"]["code"])
                self.assertIn("quantity is not valid for add_tags", invalid.json()["error"]["message"])

    def test_demo_api_bulk_mutation_supports_quantity_notes_and_acquisition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    quantity=1,
                    location="Binder A",
                    notes="old note",
                    acquisition_price="1.25",
                    acquisition_currency="USD",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    quantity=3,
                    location="Binder B",
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                quantity_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-quantity-demo"},
                    json={
                        "operation": "set_quantity",
                        "item_ids": item_ids,
                        "quantity": 4,
                    },
                )
                self.assertEqual(200, quantity_bulk.status_code)
                self.assertEqual("set_quantity", quantity_bulk.json()["operation"])
                self.assertEqual(item_ids, quantity_bulk.json()["updated_item_ids"])

                notes_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-notes-demo"},
                    json={
                        "operation": "set_notes",
                        "item_ids": item_ids,
                        "notes": "featured",
                    },
                )
                self.assertEqual(200, notes_bulk.status_code)
                self.assertEqual("set_notes", notes_bulk.json()["operation"])

                clear_notes_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-clear-notes-demo"},
                    json={
                        "operation": "set_notes",
                        "item_ids": [item_ids[1]],
                        "clear_notes": True,
                    },
                )
                self.assertEqual(200, clear_notes_bulk.status_code)
                self.assertEqual([item_ids[1]], clear_notes_bulk.json()["updated_item_ids"])

                acquisition_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-acquisition-demo"},
                    json={
                        "operation": "set_acquisition",
                        "item_ids": item_ids,
                        "acquisition_price": "2.50",
                        "acquisition_currency": "usd",
                    },
                )
                self.assertEqual(200, acquisition_bulk.status_code)
                self.assertEqual("set_acquisition", acquisition_bulk.json()["operation"])

                clear_acquisition_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-clear-acquisition-demo"},
                    json={
                        "operation": "set_acquisition",
                        "item_ids": [item_ids[0]],
                        "clear_acquisition": True,
                    },
                )
                self.assertEqual(200, clear_acquisition_bulk.status_code)
                self.assertEqual([item_ids[0]], clear_acquisition_bulk.json()["updated_item_ids"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual(4, rows_by_id[item_ids[0]]["quantity"])
                self.assertEqual(4, rows_by_id[item_ids[1]]["quantity"])
                self.assertEqual("featured", rows_by_id[item_ids[0]]["notes"])
                self.assertIsNone(rows_by_id[item_ids[1]]["notes"])
                self.assertIsNone(rows_by_id[item_ids[0]]["acquisition_price"])
                self.assertIsNone(rows_by_id[item_ids[0]]["acquisition_currency"])
                self.assertEqual("2.5", rows_by_id[item_ids[1]]["acquisition_price"])
                self.assertEqual("USD", rows_by_id[item_ids[1]]["acquisition_currency"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_acquisition", audit.json()[0]["action"])
                self.assertTrue(audit.json()[0]["metadata"]["bulk_operation"])
                self.assertTrue(audit.json()[0]["metadata"]["clear"])
                self.assertEqual("req-bulk-clear-acquisition-demo", audit.json()[0]["request_id"])

    def test_demo_api_bulk_finish_updates_rows_and_skips_noops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal","foil"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="normal",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="foil",
                    location="Binder B",
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-finish-demo"},
                    json={
                        "operation": "set_finish",
                        "item_ids": item_ids,
                        "finish": "foil",
                    },
                )
                self.assertEqual(200, bulk.status_code)
                self.assertEqual("set_finish", bulk.json()["operation"])
                self.assertEqual([item_ids[0]], bulk.json()["updated_item_ids"])
                self.assertEqual(1, bulk.json()["updated_count"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual("foil", rows_by_id[item_ids[0]]["finish"])
                self.assertEqual("foil", rows_by_id[item_ids[1]]["finish"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_finish", audit.json()[0]["action"])
                self.assertEqual("normal", audit.json()[0]["metadata"]["old_finish"])
                self.assertEqual("foil", audit.json()[0]["metadata"]["new_finish"])
                self.assertEqual("req-bulk-finish-demo", audit.json()[0]["request_id"])

    def test_demo_api_bulk_finish_conflict_returns_409(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal","foil"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="normal",
                    location="",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="foil",
                    location="",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="normal",
                    location="Binder C",
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                conflict = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_finish",
                        "item_ids": [item_ids[2], item_ids[0]],
                        "finish": "foil",
                    },
                )
                self.assertEqual(409, conflict.status_code)
                self.assertEqual("conflict", conflict.json()["error"]["code"])
                self.assertIn("Changing finish would collide", conflict.json()["error"]["message"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual("normal", rows_by_id[item_ids[0]]["finish"])
                self.assertEqual("foil", rows_by_id[item_ids[1]]["finish"])
                self.assertEqual("normal", rows_by_id[item_ids[2]]["finish"])

    def test_demo_api_bulk_location_updates_rows_and_skips_noops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal","foil"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="normal",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    finish="foil",
                    location="Binder B",
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-location-demo"},
                    json={
                        "operation": "set_location",
                        "item_ids": item_ids,
                        "location": "Binder B",
                    },
                )
                self.assertEqual(200, bulk.status_code)
                self.assertEqual("set_location", bulk.json()["operation"])
                self.assertEqual([item_ids[0]], bulk.json()["updated_item_ids"])
                self.assertEqual(1, bulk.json()["updated_count"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual("Binder B", rows_by_id[item_ids[0]]["location"])
                self.assertEqual("Binder B", rows_by_id[item_ids[1]]["location"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_location", audit.json()[0]["action"])
                self.assertEqual("Binder A", audit.json()[0]["metadata"]["old_location"])
                self.assertEqual("Binder B", audit.json()[0]["metadata"]["new_location"])
                self.assertEqual("req-bulk-location-demo", audit.json()[0]["request_id"])

    def test_demo_api_bulk_clear_location_normalizes_to_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    location="Binder A",
                )
                with connect(db_path) as connection:
                    item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

                clear_location = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-clear-location-demo"},
                    json={
                        "operation": "set_location",
                        "item_ids": [item_id],
                        "clear_location": True,
                    },
                )
                self.assertEqual(200, clear_location.status_code)
                self.assertEqual([item_id], clear_location.json()["updated_item_ids"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertIsNone(listed.json()[0]["location"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("Binder A", audit.json()[0]["before"]["location"])
                self.assertIsNone(audit.json()[0]["after"]["location"])
                self.assertIsNone(audit.json()[0]["metadata"]["new_location"])

    def test_demo_api_bulk_location_conflict_returns_409(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="NM",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="NM",
                    location="Binder B",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="LP",
                    location="Binder C",
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                conflict = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_location",
                        "item_ids": [item_ids[2], item_ids[0]],
                        "location": "Binder B",
                    },
                )
                self.assertEqual(409, conflict.status_code)
                self.assertEqual("conflict", conflict.json()["error"]["code"])
                self.assertIn("Changing location would collide", conflict.json()["error"]["message"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual("Binder A", rows_by_id[item_ids[0]]["location"])
                self.assertEqual("Binder B", rows_by_id[item_ids[1]]["location"])
                self.assertEqual("Binder C", rows_by_id[item_ids[2]]["location"])

    def test_demo_api_bulk_location_merge_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    quantity=2,
                    location="Binder A",
                    acquisition_price="1.25",
                    acquisition_currency="USD",
                    tags_json='["deck"]',
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    quantity=3,
                    location="Binder B",
                    acquisition_price="2.50",
                    acquisition_currency="USD",
                    tags_json='["trade"]',
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                merged = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-location-merge-demo"},
                    json={
                        "operation": "set_location",
                        "item_ids": [item_ids[0]],
                        "location": "Binder B",
                        "merge": True,
                        "keep_acquisition": "target",
                    },
                )
                self.assertEqual(200, merged.status_code)
                self.assertEqual("set_location", merged.json()["operation"])
                self.assertEqual([item_ids[0]], merged.json()["updated_item_ids"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertEqual(1, len(listed.json()))
                self.assertEqual(5, listed.json()[0]["quantity"])
                self.assertEqual("Binder B", listed.json()[0]["location"])
                self.assertEqual("2.5", listed.json()[0]["acquisition_price"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                location_audits = [row for row in audit.json() if row["action"] == "set_location"]
                self.assertEqual(2, len(location_audits))
                self.assertTrue(all(row["metadata"]["merged"] for row in location_audits))
                self.assertTrue(all(row["metadata"]["keep_acquisition"] == "target" for row in location_audits))

    def test_demo_api_bulk_location_rejects_invalid_field_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                )
                with connect(db_path) as connection:
                    item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

                invalid_combo = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_location",
                        "item_ids": [item_id],
                        "location": "Binder A",
                        "clear_location": True,
                    },
                )
                self.assertEqual(400, invalid_combo.status_code)
                self.assertEqual("validation_error", invalid_combo.json()["error"]["code"])
                self.assertIn(
                    "Use either location or clear_location for set_location",
                    invalid_combo.json()["error"]["message"],
                )

                invalid_keep = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_location",
                        "item_ids": [item_id],
                        "location": "Binder A",
                        "keep_acquisition": "target",
                    },
                )
                self.assertEqual(400, invalid_keep.status_code)
                self.assertEqual("validation_error", invalid_keep.json()["error"]["code"])
                self.assertIn(
                    "keep_acquisition only applies when merge is true for set_location",
                    invalid_keep.json()["error"]["message"],
                )

    def test_demo_api_bulk_condition_updates_rows_and_skips_noops(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal","foil"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="NM",
                    finish="normal",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="LP",
                    finish="foil",
                    location="Binder B",
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-condition-demo"},
                    json={
                        "operation": "set_condition",
                        "item_ids": item_ids,
                        "condition_code": "LP",
                    },
                )
                self.assertEqual(200, bulk.status_code)
                self.assertEqual("set_condition", bulk.json()["operation"])
                self.assertEqual([item_ids[0]], bulk.json()["updated_item_ids"])
                self.assertEqual(1, bulk.json()["updated_count"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual("LP", rows_by_id[item_ids[0]]["condition_code"])
                self.assertEqual("LP", rows_by_id[item_ids[1]]["condition_code"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_condition", audit.json()[0]["action"])
                self.assertEqual("NM", audit.json()[0]["metadata"]["old_condition_code"])
                self.assertEqual("LP", audit.json()[0]["metadata"]["new_condition_code"])
                self.assertEqual("req-bulk-condition-demo", audit.json()[0]["request_id"])

    def test_demo_api_bulk_condition_conflict_returns_409(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="NM",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="LP",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    condition_code="NM",
                    location="Binder B",
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                conflict = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_condition",
                        "item_ids": [item_ids[2], item_ids[0]],
                        "condition_code": "LP",
                    },
                )
                self.assertEqual(409, conflict.status_code)
                self.assertEqual("conflict", conflict.json()["error"]["code"])
                self.assertIn("Changing condition would collide", conflict.json()["error"]["message"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                rows_by_id = {row["item_id"]: row for row in listed.json()}
                self.assertEqual("NM", rows_by_id[item_ids[0]]["condition_code"])
                self.assertEqual("LP", rows_by_id[item_ids[1]]["condition_code"])
                self.assertEqual("NM", rows_by_id[item_ids[2]]["condition_code"])

    def test_demo_api_bulk_condition_merge_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
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
                    scryfall_id="api-card-1",
                    quantity=3,
                    condition_code="LP",
                    location="Binder A",
                    acquisition_price="2.50",
                    acquisition_currency="USD",
                    tags_json='["trade"]',
                )
                with connect(db_path) as connection:
                    item_ids = [int(row["id"]) for row in connection.execute("SELECT id FROM inventory_items ORDER BY id").fetchall()]

                merged = client.post(
                    "/inventories/personal/items/bulk",
                    headers={"X-Request-Id": "req-bulk-condition-merge-demo"},
                    json={
                        "operation": "set_condition",
                        "item_ids": [item_ids[0]],
                        "condition_code": "LP",
                        "merge": True,
                        "keep_acquisition": "source",
                    },
                )
                self.assertEqual(200, merged.status_code)
                self.assertEqual("set_condition", merged.json()["operation"])
                self.assertEqual([item_ids[0]], merged.json()["updated_item_ids"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertEqual(1, len(listed.json()))
                self.assertEqual(5, listed.json()[0]["quantity"])
                self.assertEqual("LP", listed.json()[0]["condition_code"])
                self.assertEqual("1.25", listed.json()[0]["acquisition_price"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                condition_audits = [row for row in audit.json() if row["action"] == "set_condition"]
                self.assertEqual(2, len(condition_audits))
                self.assertTrue(all(row["metadata"]["merged"] for row in condition_audits))
                self.assertTrue(all(row["metadata"]["keep_acquisition"] == "source" for row in condition_audits))

    def test_demo_api_bulk_condition_rejects_invalid_field_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                )
                with connect(db_path) as connection:
                    item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

                missing_condition = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_condition",
                        "item_ids": [item_id],
                    },
                )
                self.assertEqual(400, missing_condition.status_code)
                self.assertEqual("validation_error", missing_condition.json()["error"]["code"])
                self.assertIn(
                    "condition_code is required for set_condition",
                    missing_condition.json()["error"]["message"],
                )

                invalid_keep = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_condition",
                        "item_ids": [item_id],
                        "condition_code": "LP",
                        "keep_acquisition": "target",
                    },
                )
                self.assertEqual(400, invalid_keep.status_code)
                self.assertEqual("validation_error", invalid_keep.json()["error"]["code"])
                self.assertIn(
                    "keep_acquisition only applies when merge is true for set_condition",
                    invalid_keep.json()["error"]["message"],
                )

    def test_demo_api_transfer_supports_dry_run_and_live_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                source_created = client.post(
                    "/inventories",
                    json={"slug": "source", "display_name": "Source Collection"},
                )
                self.assertEqual(201, source_created.status_code)
                target_created = client.post(
                    "/inventories",
                    json={"slug": "target", "display_name": "Target Collection"},
                )
                self.assertEqual(201, target_created.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
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

                preview = client.post(
                    "/inventories/source/transfer",
                    headers={"X-Request-Id": "req-transfer-preview"},
                    json={
                        "target_inventory_slug": "target",
                        "mode": "move",
                        "item_ids": [source_item_id],
                        "on_conflict": "fail",
                        "dry_run": True,
                    },
                )
                self.assertEqual(200, preview.status_code)
                self.assertTrue(preview.json()["dry_run"])
                self.assertEqual("items", preview.json()["selection_kind"])
                self.assertEqual([source_item_id], preview.json()["requested_item_ids"])
                self.assertEqual("would_move", preview.json()["results"][0]["status"])

                moved = client.post(
                    "/inventories/source/transfer",
                    headers={"X-Request-Id": "req-transfer-live"},
                    json={
                        "target_inventory_slug": "target",
                        "mode": "move",
                        "item_ids": [source_item_id],
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(200, moved.status_code)
                self.assertFalse(moved.json()["dry_run"])
                self.assertEqual("items", moved.json()["selection_kind"])
                self.assertEqual("moved", moved.json()["results"][0]["status"])
                self.assertTrue(moved.json()["results"][0]["source_removed"])

                source_rows = client.get("/inventories/source/items")
                target_rows = client.get("/inventories/target/items")
                self.assertEqual(200, source_rows.status_code)
                self.assertEqual(200, target_rows.status_code)
                self.assertEqual([], source_rows.json())
                self.assertEqual(1, len(target_rows.json()))
                self.assertEqual(2, target_rows.json()[0]["quantity"])
                self.assertEqual(["deck"], target_rows.json()[0]["tags"])
                self.assertEqual("defaulted", target_rows.json()[0]["printing_selection_mode"])

                source_audit = client.get("/inventories/source/audit")
                target_audit = client.get("/inventories/target/audit")
                self.assertEqual("transfer_items", source_audit.json()[0]["action"])
                self.assertEqual("transfer_items", target_audit.json()[0]["action"])
                self.assertEqual("source", source_audit.json()[0]["metadata"]["role"])
                self.assertEqual("target", target_audit.json()[0]["metadata"]["role"])
                self.assertEqual("req-transfer-live", source_audit.json()[0]["request_id"])

    def test_demo_api_transfer_conflict_returns_409_without_mutating_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                source_created = client.post(
                    "/inventories",
                    json={"slug": "source", "display_name": "Source Collection"},
                )
                self.assertEqual(201, source_created.status_code)
                target_created = client.post(
                    "/inventories",
                    json={"slug": "target", "display_name": "Target Collection"},
                )
                self.assertEqual(201, target_created.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="target",
                    scryfall_id="api-card-1",
                    location="Binder A",
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

                conflict = client.post(
                    "/inventories/source/transfer",
                    json={
                        "target_inventory_slug": "target",
                        "mode": "move",
                        "item_ids": [source_item_id],
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(409, conflict.status_code)
                self.assertEqual("conflict", conflict.json()["error"]["code"])
                self.assertIn("would collide with an existing row in inventory 'target'", conflict.json()["error"]["message"])

                source_rows = client.get("/inventories/source/items")
                target_rows = client.get("/inventories/target/items")
                self.assertEqual(1, len(source_rows.json()))
                self.assertEqual(1, len(target_rows.json()))

    def test_demo_api_transfer_all_items_moves_entire_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                source_created = client.post(
                    "/inventories",
                    json={"slug": "source", "display_name": "Source Collection"},
                )
                self.assertEqual(201, source_created.status_code)
                target_created = client.post(
                    "/inventories",
                    json={"slug": "target", "display_name": "Target Collection"},
                )
                self.assertEqual(201, target_created.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
                    quantity=2,
                    location="Binder A",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
                    quantity=1,
                    location="Binder B",
                )

                moved = client.post(
                    "/inventories/source/transfer",
                    headers={"X-Request-Id": "req-transfer-all"},
                    json={
                        "target_inventory_slug": "target",
                        "mode": "move",
                        "all_items": True,
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(200, moved.status_code)
                self.assertEqual("all_items", moved.json()["selection_kind"])
                self.assertIsNone(moved.json()["requested_item_ids"])
                self.assertEqual(2, moved.json()["requested_count"])
                self.assertEqual(2, moved.json()["moved_count"])

                source_rows = client.get("/inventories/source/items")
                target_rows = client.get("/inventories/target/items")
                self.assertEqual([], source_rows.json())
                self.assertEqual(2, len(target_rows.json()))

    def test_demo_api_duplicate_creates_new_inventory_and_copies_all_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                source_created = client.post(
                    "/inventories",
                    json={
                        "slug": "source",
                        "display_name": "Source Collection",
                        "description": "Original description",
                    },
                )
                self.assertEqual(201, source_created.status_code)
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
                    quantity=2,
                    location="Binder A",
                    tags_json='["deck"]',
                    printing_selection_mode="defaulted",
                )

                duplicated = client.post(
                    "/inventories/source/duplicate",
                    headers={"X-Request-Id": "req-duplicate"},
                    json={
                        "target_slug": "source-copy",
                        "target_display_name": "Source Copy",
                    },
                )
                self.assertEqual(201, duplicated.status_code)
                self.assertEqual("source", duplicated.json()["source_inventory"])
                self.assertEqual("source-copy", duplicated.json()["inventory"]["slug"])
                self.assertEqual("Original description", duplicated.json()["inventory"]["description"])
                self.assertEqual("all_items", duplicated.json()["transfer"]["selection_kind"])
                self.assertEqual(1, duplicated.json()["transfer"]["copied_count"])

                source_rows = client.get("/inventories/source/items")
                target_rows = client.get("/inventories/source-copy/items")
                self.assertEqual(1, len(source_rows.json()))
                self.assertEqual(1, len(target_rows.json()))
                self.assertEqual(2, target_rows.json()[0]["quantity"])
                self.assertEqual(["deck"], target_rows.json()[0]["tags"])
                self.assertEqual("defaulted", target_rows.json()[0]["printing_selection_mode"])

    def test_demo_api_inventory_create_trims_slug_and_rejects_trimmed_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                created = client.post(
                    "/inventories",
                    json={"slug": " personal ", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created.status_code)
                self.assertEqual("personal", created.json()["slug"])

                duplicate = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Duplicate Personal"},
                )
                self.assertEqual(409, duplicate.status_code)
                self.assertEqual("conflict", duplicate.json()["error"]["code"])
                self.assertIn("Inventory 'personal' already exists", duplicate.json()["error"]["message"])

    def test_demo_api_bulk_quantity_requires_quantity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                )
                with connect(db_path) as connection:
                    item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

                invalid = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "set_quantity",
                        "item_ids": [item_id],
                    },
                )
                self.assertEqual(400, invalid.status_code)
                self.assertEqual("validation_error", invalid.json()["error"]["code"])
                self.assertIn("quantity is required for set_quantity", invalid.json()["error"]["message"])

    def test_demo_api_add_item_accepts_oracle_id_and_inherits_resolved_printing_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_oracle_add_candidates(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "oracle_id": "api-add-oracle",
                        "lang": "ja",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "foil",
                    },
                )
                self.assertEqual(201, added.status_code)
                self.assertEqual("api-add-ja", added.json()["scryfall_id"])
                self.assertEqual("ja", added.json()["language_code"])
                self.assertEqual("explicit", added.json()["printing_selection_mode"])

                conflict = client.post(
                    "/inventories/personal/items",
                    json={
                        "oracle_id": "api-add-oracle",
                        "lang": "ja",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "foil",
                        "language_code": "en",
                    },
                )
                self.assertEqual(400, conflict.status_code)
                self.assertEqual("validation_error", conflict.json()["error"]["code"])
                self.assertIn("language_code must match the resolved printing language", conflict.json()["error"]["message"])

    def test_demo_api_add_item_uses_mainstream_default_printing_for_oracle_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-policy-mainstream-en",
                    oracle_id="api-policy-oracle",
                    name="API Oracle Policy Card",
                    set_code="bro",
                    set_name="The Brothers' War",
                    collector_number="81",
                    lang="en",
                    released_at="2023-11-18",
                    finishes_json='["nonfoil","foil"]',
                    set_type="expansion",
                    booster=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-policy-mainstream-ja",
                    oracle_id="api-policy-oracle",
                    name="API Oracle Policy Card",
                    set_code="mkm",
                    set_name="Murders at Karlov Manor",
                    collector_number="82",
                    lang="ja",
                    released_at="2024-02-09",
                    finishes_json='["nonfoil","foil"]',
                    set_type="expansion",
                    booster=1,
                )
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-policy-promo-en",
                    oracle_id="api-policy-oracle",
                    name="API Oracle Policy Card",
                    set_code="pneo",
                    set_name="Kamigawa: Neon Dynasty Promos",
                    collector_number="83",
                    lang="en",
                    released_at="2024-03-01",
                    finishes_json='["nonfoil","foil"]',
                    set_type="expansion",
                    booster=0,
                    promo_types_json='["promo_pack"]',
                )

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "oracle_id": "api-policy-oracle",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)
                self.assertEqual("api-policy-mainstream-en", added.json()["scryfall_id"])
                self.assertEqual("en", added.json()["language_code"])
                self.assertEqual("defaulted", added.json()["printing_selection_mode"])

    def test_demo_api_returns_409_for_concurrent_add_item_identity_collision(self) -> None:
        from mtg_source_stack.inventory.service import add_card as service_add_card

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                def insert_conflicting_row() -> None:
                    self._insert_inventory_item(
                        db_path,
                        inventory_slug="personal",
                        scryfall_id="api-card-1",
                        quantity=1,
                    )

                def add_card_with_collision(*args, **kwargs):
                    return service_add_card(*args, before_write=insert_conflicting_row, **kwargs)

                with patch("mtg_source_stack.api.routes.add_card", side_effect=add_card_with_collision):
                    response = client.post(
                        "/inventories/personal/items",
                        json={
                            "scryfall_id": "api-card-1",
                            "quantity": 2,
                            "condition_code": "NM",
                            "finish": "normal",
                        },
                    )

                self.assertEqual(409, response.status_code)
                self.assertEqual("conflict", response.json()["error"]["code"])
                self.assertEqual(
                    "Adding card would collide with an existing inventory row due to a concurrent write. Retry the request.",
                    response.json()["error"]["message"],
                )

    def test_demo_api_returns_409_for_concurrent_location_collision(self) -> None:
        from mtg_source_stack.inventory.service import set_location as service_set_location

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 2,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "Binder A",
                    },
                )
                self.assertEqual(201, added.status_code)
                item_id = added.json()["item_id"]

                def insert_conflicting_row() -> None:
                    self._insert_inventory_item(
                        db_path,
                        inventory_slug="personal",
                        scryfall_id="api-card-1",
                        quantity=1,
                        location="Binder B",
                    )

                def set_location_with_collision(*args, **kwargs):
                    return service_set_location(*args, before_write=insert_conflicting_row, **kwargs)

                with patch("mtg_source_stack.api.routes.set_location", side_effect=set_location_with_collision):
                    response = client.patch(
                        f"/inventories/personal/items/{item_id}",
                        json={"location": "Binder B"},
                    )

                self.assertEqual(409, response.status_code)
                self.assertEqual("conflict", response.json()["error"]["code"])
                self.assertEqual(
                    "Changing location would collide with an existing inventory row. Re-run with --merge to combine the rows, or resolve the duplicate row first.",
                    response.json()["error"]["message"],
                )

    def test_demo_api_returns_409_for_concurrent_condition_collision(self) -> None:
        from mtg_source_stack.inventory.service import set_condition as service_set_condition

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 2,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "Binder A",
                    },
                )
                self.assertEqual(201, added.status_code)
                item_id = added.json()["item_id"]

                def insert_conflicting_row() -> None:
                    self._insert_inventory_item(
                        db_path,
                        inventory_slug="personal",
                        scryfall_id="api-card-1",
                        quantity=1,
                        condition_code="LP",
                        location="Binder A",
                    )

                def set_condition_with_collision(*args, **kwargs):
                    return service_set_condition(*args, before_write=insert_conflicting_row, **kwargs)

                with patch("mtg_source_stack.api.routes.set_condition", side_effect=set_condition_with_collision):
                    response = client.patch(
                        f"/inventories/personal/items/{item_id}",
                        json={"condition_code": "LP"},
                    )

                self.assertEqual(409, response.status_code)
                self.assertEqual("conflict", response.json()["error"]["code"])
                self.assertEqual(
                    "Changing condition would collide with an existing inventory row. Re-run with --merge to combine the rows, or resolve the duplicate row first.",
                    response.json()["error"]["message"],
                )

    def test_shared_service_mode_handles_a_small_concurrent_request_burst(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            auth_headers = {"X-Authenticated-User": "shared-user"}

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)

                self.assertEqual(401, client.get("/inventories").status_code)
                self.assertEqual(401, client.get("/cards/search", params={"query": "API"}).status_code)

                created_inventory = client.post(
                    "/inventories",
                    headers=auth_headers,
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    headers=auth_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)
                item_id = added.json()["item_id"]

                def get_inventories():
                    response = client.get("/inventories", headers=auth_headers)
                    self.assertEqual(200, response.status_code)
                    return response.status_code

                def get_items():
                    response = client.get("/inventories/personal/items", headers=auth_headers)
                    self.assertEqual(200, response.status_code)
                    return response.status_code

                def patch_notes():
                    response = client.patch(
                        f"/inventories/personal/items/{item_id}",
                        headers=auth_headers,
                        json={"notes": "shared burst"},
                    )
                    self.assertEqual(200, response.status_code)
                    return response.status_code

                def get_audit():
                    response = client.get("/inventories/personal/audit", headers=auth_headers)
                    self.assertEqual(200, response.status_code)
                    return response.status_code

                with ThreadPoolExecutor(max_workers=5) as executor:
                    futures = [
                        executor.submit(get_inventories),
                        executor.submit(get_items),
                        executor.submit(patch_notes),
                        executor.submit(get_audit),
                        executor.submit(get_items),
                    ]
                    results = [future.result(timeout=5) for future in futures]

                self.assertEqual([200, 200, 200, 200, 200], results)

    def test_shared_service_inventory_list_is_filtered_by_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            viewer_headers = {
                "X-Authenticated-User": "viewer-user",
                "X-Authenticated-Roles": "viewer",
            }
            outsider_headers = {
                "X-Authenticated-User": "outsider-user",
                "X-Authenticated-Roles": "viewer",
            }
            owner_headers = {"X-Authenticated-User": "owner-user"}
            admin_headers = {
                "X-Authenticated-User": "shared-admin",
                "X-Authenticated-Roles": "admin",
            }

            create_inventory(
                db_path,
                slug="admin-only",
                display_name="Admin Only",
                description=None,
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer-user",
                role="viewer",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                anonymous_inventories = client.get("/inventories")
                self.assertEqual(401, anonymous_inventories.status_code)
                self.assertEqual("authentication_required", anonymous_inventories.json()["error"]["code"])

                viewer_inventories = client.get("/inventories", headers=viewer_headers)
                self.assertEqual(200, viewer_inventories.status_code)
                self.assertEqual(["personal"], [row["slug"] for row in viewer_inventories.json()])
                viewer_inventory = viewer_inventories.json()[0]
                self.assertEqual("viewer", viewer_inventory["role"])
                self.assertTrue(viewer_inventory["can_read"])
                self.assertFalse(viewer_inventory["can_write"])
                self.assertFalse(viewer_inventory["can_manage_share"])
                self.assertFalse(viewer_inventory["can_transfer_to"])

                outsider_inventories = client.get("/inventories", headers=outsider_headers)
                self.assertEqual(200, outsider_inventories.status_code)
                self.assertEqual([], outsider_inventories.json())

                owner_inventories = client.get("/inventories", headers=owner_headers)
                self.assertEqual(200, owner_inventories.status_code)
                self.assertEqual(["personal"], [row["slug"] for row in owner_inventories.json()])
                owner_inventory = owner_inventories.json()[0]
                self.assertEqual("owner", owner_inventory["role"])
                self.assertTrue(owner_inventory["can_read"])
                self.assertTrue(owner_inventory["can_write"])
                self.assertTrue(owner_inventory["can_manage_share"])
                self.assertTrue(owner_inventory["can_transfer_to"])

                admin_inventories = client.get("/inventories", headers=admin_headers)
                self.assertEqual(200, admin_inventories.status_code)
                self.assertEqual(
                    ["admin-only", "personal"],
                    [row["slug"] for row in admin_inventories.json()],
                )
                self.assertTrue(all(row["role"] == "admin" for row in admin_inventories.json()))
                self.assertTrue(all(row["can_read"] for row in admin_inventories.json()))
                self.assertTrue(all(row["can_write"] for row in admin_inventories.json()))
                self.assertTrue(all(row["can_manage_share"] for row in admin_inventories.json()))
                self.assertTrue(all(row["can_transfer_to"] for row in admin_inventories.json()))

    def test_shared_service_inventory_read_routes_allow_viewers_and_reject_non_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            owner_headers = {"X-Authenticated-User": "owner-user"}
            viewer_headers = {
                "X-Authenticated-User": "viewer-user",
                "X-Authenticated-Roles": "viewer",
            }
            outsider_headers = {
                "X-Authenticated-User": "outsider-user",
                "X-Authenticated-Roles": "viewer",
            }

            create_inventory(
                db_path,
                slug="admin-only",
                display_name="Admin Only",
                description=None,
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer-user",
                role="viewer",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)
                self._seed_oracle_printings(db_path)

                added = client.post(
                    "/inventories/personal/items",
                    headers=owner_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)

                viewer_items = client.get("/inventories/personal/items", headers=viewer_headers)
                self.assertEqual(200, viewer_items.status_code)

                viewer_audit = client.get("/inventories/personal/audit", headers=viewer_headers)
                self.assertEqual(200, viewer_audit.status_code)

                viewer_export = client.get(
                    "/inventories/personal/export.csv",
                    headers=viewer_headers,
                    params={"provider": "tcgplayer", "profile": "default"},
                )
                self.assertEqual(200, viewer_export.status_code)
                self.assertIn("API Test Card", viewer_export.text)

                viewer_search = client.get("/cards/search", headers=viewer_headers, params={"query": "API Test"})
                self.assertEqual(200, viewer_search.status_code)

                viewer_name_search = client.get(
                    "/cards/search/names",
                    headers=viewer_headers,
                    params={"query": "API Lookup"},
                )
                self.assertEqual(200, viewer_name_search.status_code)

                viewer_printings = client.get(
                    "/cards/oracle/api-oracle-lookup/printings",
                    headers=viewer_headers,
                )
                self.assertEqual(200, viewer_printings.status_code)

                denied_items = client.get("/inventories/admin-only/items", headers=viewer_headers)
                self.assertEqual(403, denied_items.status_code)
                self.assertEqual("forbidden", denied_items.json()["error"]["code"])

                denied_audit = client.get("/inventories/admin-only/audit", headers=viewer_headers)
                self.assertEqual(403, denied_audit.status_code)
                self.assertEqual("forbidden", denied_audit.json()["error"]["code"])

                denied_export = client.get(
                    "/inventories/admin-only/export.csv",
                    headers=viewer_headers,
                    params={"provider": "tcgplayer", "profile": "default"},
                )
                self.assertEqual(403, denied_export.status_code)
                self.assertEqual("forbidden", denied_export.json()["error"]["code"])

                outsider_search = client.get("/cards/search", headers=outsider_headers, params={"query": "API Test"})
                self.assertEqual(403, outsider_search.status_code)
                self.assertEqual("forbidden", outsider_search.json()["error"]["code"])

                outsider_name_search = client.get(
                    "/cards/search/names",
                    headers=outsider_headers,
                    params={"query": "API Lookup"},
                )
                self.assertEqual(403, outsider_name_search.status_code)
                self.assertEqual("forbidden", outsider_name_search.json()["error"]["code"])

                outsider_printings = client.get(
                    "/cards/oracle/api-oracle-lookup/printings",
                    headers=outsider_headers,
                )
                self.assertEqual(403, outsider_printings.status_code)
                self.assertEqual("forbidden", outsider_printings.json()["error"]["code"])

    def test_inventory_share_links_are_owner_managed_and_public_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            owner_headers = {"X-Authenticated-User": "owner-user"}
            viewer_headers = {"X-Authenticated-User": "viewer-user"}
            editor_headers = {"X-Authenticated-User": "editor-user"}

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description="Cards I want to share",
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer-user",
                role="viewer",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="editor-user",
                role="editor",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)

                added = client.post(
                    "/inventories/personal/items",
                    headers=owner_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 2,
                        "condition_code": "NM",
                        "finish": "normal",
                        "location": "Private Binder",
                        "acquisition_price": "1.25",
                        "acquisition_currency": "USD",
                        "notes": "private owner note",
                        "tags": ["trade", "private"],
                    },
                )
                self.assertEqual(201, added.status_code)

                viewer_create = client.post("/inventories/personal/share-link", headers=viewer_headers)
                self.assertEqual(403, viewer_create.status_code)

                editor_create = client.post("/inventories/personal/share-link", headers=editor_headers)
                self.assertEqual(403, editor_create.status_code)

                initial_status = client.get("/inventories/personal/share-link", headers=owner_headers)
                self.assertEqual(200, initial_status.status_code)
                self.assertEqual(
                    {
                        "inventory": "personal",
                        "active": False,
                        "public_path": None,
                        "created_at": None,
                        "updated_at": None,
                        "revoked_at": None,
                    },
                    initial_status.json(),
                )

                created = client.post("/inventories/personal/share-link", headers=owner_headers)
                self.assertEqual(201, created.status_code)
                created_payload = created.json()
                self.assertEqual("personal", created_payload["inventory"])
                self.assertTrue(created_payload["active"])
                self.assertTrue(created_payload["token"])
                created_backend_route = f"/shared/inventories/{created_payload['token']}"
                self.assertEqual(
                    created_backend_route,
                    created_payload["public_path"],
                )
                active_status = client.get("/inventories/personal/share-link", headers=owner_headers)
                self.assertEqual(200, active_status.status_code)
                self.assertEqual(created_payload["public_path"], active_status.json()["public_path"])
                with connect(db_path) as connection:
                    share_row = connection.execute(
                        """
                        SELECT token_nonce
                        FROM inventory_share_links
                        WHERE inventory_id = (
                            SELECT id
                            FROM inventories
                            WHERE slug = ?
                        )
                        """,
                        ("personal",),
                    ).fetchone()
                self.assertIn(share_row["token_nonce"], created_payload["token"])
                self.assertNotEqual(created_payload["token"], share_row["token_nonce"])

                duplicate_create = client.post("/inventories/personal/share-link", headers=owner_headers)
                self.assertEqual(409, duplicate_create.status_code)

                public_view = client.get(created_backend_route)
                self.assertEqual(200, public_view.status_code)
                public_payload = public_view.json()
                self.assertEqual(
                    {
                        "display_name": "Personal Collection",
                        "description": "Cards I want to share",
                        "item_rows": 1,
                        "total_cards": 2,
                    },
                    public_payload["inventory"],
                )
                self.assertEqual(1, len(public_payload["items"]))
                public_item = public_payload["items"][0]
                self.assertEqual("API Test Card", public_item["name"])
                self.assertEqual(2, public_item["quantity"])
                self.assertEqual("normal", public_item["finish"])
                self.assertNotIn("notes", public_item)
                self.assertNotIn("acquisition_price", public_item)
                self.assertNotIn("acquisition_currency", public_item)
                self.assertNotIn("location", public_item)
                self.assertNotIn("tags", public_item)
                self.assertNotIn("item_id", public_item)
                self.assertNotIn("currency", public_item)
                self.assertNotIn("unit_price", public_item)
                self.assertNotIn("est_value", public_item)

                anonymous_private_route = client.get("/inventories/personal/items")
                self.assertEqual(401, anonymous_private_route.status_code)

                rotated = client.post("/inventories/personal/share-link/rotate", headers=owner_headers)
                self.assertEqual(200, rotated.status_code)
                rotated_payload = rotated.json()
                self.assertNotEqual(created_payload["token"], rotated_payload["token"])
                rotated_backend_route = f"/shared/inventories/{rotated_payload['token']}"
                self.assertEqual(rotated_backend_route, rotated_payload["public_path"])

                old_public_view = client.get(created_backend_route)
                self.assertEqual(404, old_public_view.status_code)
                new_public_view = client.get(rotated_backend_route)
                self.assertEqual(200, new_public_view.status_code)

                revoked = client.delete("/inventories/personal/share-link", headers=owner_headers)
                self.assertEqual(200, revoked.status_code)
                self.assertFalse(revoked.json()["active"])
                self.assertIsNotNone(revoked.json()["revoked_at"])

                revoked_public_view = client.get(rotated_backend_route)
                self.assertEqual(404, revoked_public_view.status_code)

                revoked_again = client.delete("/inventories/personal/share-link", headers=owner_headers)
                self.assertEqual(200, revoked_again.status_code)
                self.assertFalse(revoked_again.json()["active"])

    def test_inventory_share_links_public_route_groups_rows_by_visible_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            owner_headers = {"X-Authenticated-User": "owner-user"}

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description="Cards I want to share",
                actor_id="owner-user",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    quantity=2,
                    finish="normal",
                    location="Private Binder A",
                    acquisition_price="1.25",
                    acquisition_currency="USD",
                    notes="private owner note a",
                    tags_json='["trade-a"]',
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    quantity=3,
                    finish="normal",
                    location="Private Binder B",
                    acquisition_price="2.50",
                    acquisition_currency="USD",
                    notes="private owner note b",
                    tags_json='["trade-b"]',
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                    quantity=1,
                    finish="foil",
                    location="Private Binder C",
                    acquisition_price="4.00",
                    acquisition_currency="USD",
                    notes="private foil note",
                    tags_json='["trade-c"]',
                )

                created = client.post("/inventories/personal/share-link", headers=owner_headers)
                self.assertEqual(201, created.status_code)

                public_view = client.get(f"/shared/inventories/{created.json()['token']}")
                self.assertEqual(200, public_view.status_code)
                public_payload = public_view.json()

                self.assertEqual(
                    {
                        "display_name": "Personal Collection",
                        "description": "Cards I want to share",
                        "item_rows": 2,
                        "total_cards": 6,
                    },
                    public_payload["inventory"],
                )
                self.assertEqual(2, len(public_payload["items"]))

                items_by_finish = {
                    item["finish"]: item for item in public_payload["items"]
                }
                self.assertEqual({"normal", "foil"}, set(items_by_finish))
                self.assertEqual(5, items_by_finish["normal"]["quantity"])
                self.assertEqual(1, items_by_finish["foil"]["quantity"])
                for public_item in items_by_finish.values():
                    self.assertNotIn("notes", public_item)
                    self.assertNotIn("acquisition_price", public_item)
                    self.assertNotIn("acquisition_currency", public_item)
                    self.assertNotIn("location", public_item)
                    self.assertNotIn("tags", public_item)
                    self.assertNotIn("item_id", public_item)
                    self.assertNotIn("currency", public_item)
                    self.assertNotIn("unit_price", public_item)
                    self.assertNotIn("est_value", public_item)

    def test_inventory_share_links_allow_global_admin_management(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            admin_headers = {
                "X-Authenticated-User": "admin-user",
                "X-Authenticated-Roles": "admin",
            }
            create_inventory(
                db_path,
                slug="admin-only",
                display_name="Admin Only",
                description=None,
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                created = client.post("/inventories/admin-only/share-link", headers=admin_headers)
                self.assertEqual(201, created.status_code)
                self.assertEqual("admin-only", created.json()["inventory"])

    def test_inventory_memberships_are_owner_managed_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            owner_headers = {"X-Authenticated-User": "owner-user"}
            viewer_headers = {"X-Authenticated-User": "viewer-user"}
            editor_headers = {"X-Authenticated-User": "editor-user"}
            outsider_headers = {"X-Authenticated-User": "outsider-user"}

            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer-user",
                role="viewer",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="editor-user",
                role="editor",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                anonymous_list = client.get("/inventories/personal/members")
                self.assertEqual(401, anonymous_list.status_code)

                viewer_list = client.get("/inventories/personal/members", headers=viewer_headers)
                self.assertEqual(403, viewer_list.status_code)

                editor_grant = client.post(
                    "/inventories/personal/members",
                    headers=editor_headers,
                    json={"actor_id": "new-user", "role": "viewer"},
                )
                self.assertEqual(403, editor_grant.status_code)

                outsider_list = client.get("/inventories/personal/members", headers=outsider_headers)
                self.assertEqual(403, outsider_list.status_code)

                listed = client.get("/inventories/personal/members", headers=owner_headers)
                self.assertEqual(200, listed.status_code)
                self.assertEqual(
                    [
                        ("editor-user", "editor"),
                        ("owner-user", "owner"),
                        ("viewer-user", "viewer"),
                    ],
                    [(row["actor_id"], row["role"]) for row in listed.json()],
                )

                invalid_role = client.post(
                    "/inventories/personal/members",
                    headers=owner_headers,
                    json={"actor_id": "bad-user", "role": "manager"},
                )
                self.assertEqual(400, invalid_role.status_code)
                self.assertEqual("validation_error", invalid_role.json()["error"]["code"])

                granted = client.post(
                    "/inventories/personal/members",
                    headers={**owner_headers, "X-Request-Id": "req-grant-member"},
                    json={"actor_id": "new-user", "role": "viewer"},
                )
                self.assertEqual(201, granted.status_code)
                self.assertEqual("personal", granted.json()["inventory"])
                self.assertEqual("new-user", granted.json()["actor_id"])
                self.assertEqual("viewer", granted.json()["role"])
                self.assertTrue(granted.json()["created_at"])
                self.assertTrue(granted.json()["updated_at"])

                duplicate_grant = client.post(
                    "/inventories/personal/members",
                    headers=owner_headers,
                    json={"actor_id": "new-user", "role": "viewer"},
                )
                self.assertEqual(201, duplicate_grant.status_code)

                updated = client.patch(
                    "/inventories/personal/members/new-user",
                    headers={**owner_headers, "X-Request-Id": "req-update-member"},
                    json={"role": "editor"},
                )
                self.assertEqual(200, updated.status_code)
                self.assertEqual("editor", updated.json()["role"])

                missing_update = client.patch(
                    "/inventories/personal/members/missing-user",
                    headers=owner_headers,
                    json={"role": "viewer"},
                )
                self.assertEqual(404, missing_update.status_code)

                last_owner_demote = client.patch(
                    "/inventories/personal/members/owner-user",
                    headers=owner_headers,
                    json={"role": "editor"},
                )
                self.assertEqual(409, last_owner_demote.status_code)
                self.assertEqual("conflict", last_owner_demote.json()["error"]["code"])

                last_owner_delete = client.delete(
                    "/inventories/personal/members/owner-user",
                    headers=owner_headers,
                )
                self.assertEqual(409, last_owner_delete.status_code)

                removed = client.delete(
                    "/inventories/personal/members/new-user",
                    headers={**owner_headers, "X-Request-Id": "req-remove-member"},
                )
                self.assertEqual(200, removed.status_code)
                self.assertEqual(
                    {
                        "inventory": "personal",
                        "actor_id": "new-user",
                        "role": "editor",
                    },
                    removed.json(),
                )

                final_list = client.get("/inventories/personal/members", headers=owner_headers)
                self.assertEqual(200, final_list.status_code)
                self.assertEqual(
                    [
                        ("editor-user", "editor"),
                        ("owner-user", "owner"),
                        ("viewer-user", "viewer"),
                    ],
                    [(row["actor_id"], row["role"]) for row in final_list.json()],
                )

            audit_rows = list_inventory_audit_events(db_path, inventory_slug="personal", limit=10)
            self.assertEqual(
                [
                    "revoke_inventory_membership",
                    "update_inventory_membership",
                    "grant_inventory_membership",
                ],
                [row.action for row in audit_rows],
            )
            self.assertEqual(["req-remove-member", "req-update-member", "req-grant-member"], [row.request_id for row in audit_rows])
            self.assertTrue(all(row.actor_type == "api" for row in audit_rows))
            self.assertTrue(all(row.actor_id == "owner-user" for row in audit_rows))

    def test_inventory_memberships_allow_global_admin_management(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            admin_headers = {
                "X-Authenticated-User": "admin-user",
                "X-Authenticated-Roles": "admin",
            }
            create_inventory(
                db_path,
                slug="admin-only",
                display_name="Admin Only",
                description=None,
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                listed = client.get("/inventories/admin-only/members", headers=admin_headers)
                self.assertEqual(200, listed.status_code)
                self.assertEqual([], listed.json())

                granted = client.post(
                    "/inventories/admin-only/members",
                    headers=admin_headers,
                    json={"actor_id": "owner-user", "role": "owner"},
                )
                self.assertEqual(201, granted.status_code)
                self.assertEqual("admin-only", granted.json()["inventory"])
                self.assertEqual("owner-user", granted.json()["actor_id"])
                self.assertEqual("owner", granted.json()["role"])

    def test_shared_service_mutating_requests_require_authenticated_actor_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)

                access_summary_without_auth = client.get("/me/access-summary")
                self.assertEqual(401, access_summary_without_auth.status_code)
                self.assertEqual("authentication_required", access_summary_without_auth.json()["error"]["code"])

                bootstrap_without_auth = client.post("/me/bootstrap")
                self.assertEqual(401, bootstrap_without_auth.status_code)
                self.assertEqual("authentication_required", bootstrap_without_auth.json()["error"]["code"])

                create_without_auth = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(401, create_without_auth.status_code)
                self.assertEqual("authentication_required", create_without_auth.json()["error"]["code"])
                self.assertIn("X-Authenticated-User", create_without_auth.json()["error"]["message"])

                create_with_wrong_header = client.post(
                    "/inventories",
                    headers={"X-Actor-Id": "untrusted-user"},
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(401, create_with_wrong_header.status_code)
                self.assertEqual("authentication_required", create_with_wrong_header.json()["error"]["code"])

                bootstrap_with_non_global_role = client.post(
                    "/me/bootstrap",
                    headers={
                        "X-Authenticated-User": "shared-viewer",
                        "X-Authenticated-Roles": "viewer",
                    },
                )
                self.assertEqual(200, bootstrap_with_non_global_role.status_code)
                self.assertEqual("shared-viewer-collection", bootstrap_with_non_global_role.json()["inventory"]["slug"])

                created_inventory = client.post(
                    "/inventories",
                    headers={"X-Authenticated-User": "shared-user"},
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)
                self.assertEqual(
                    "owner",
                    actor_inventory_role(
                        db_path,
                        inventory_slug="personal",
                        actor_id="shared-user",
                    ),
                )

                import_without_auth = client.post(
                    "/imports/csv",
                    files={
                        "file": (
                            "inventory_import.csv",
                            (
                                "Inventory,Scryfall ID,Qty,Cond\n"
                                "personal,api-card-1,1,NM\n"
                            ).encode("utf-8"),
                            "text/csv",
                        )
                    },
                )
                self.assertEqual(401, import_without_auth.status_code)
                self.assertEqual("authentication_required", import_without_auth.json()["error"]["code"])

                decklist_without_auth = client.post(
                    "/imports/decklist",
                    json={
                        "deck_text": "1 API Test Card",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(401, decklist_without_auth.status_code)
                self.assertEqual("authentication_required", decklist_without_auth.json()["error"]["code"])

                deck_url_without_auth = client.post(
                    "/imports/deck-url",
                    json={
                        "source_url": "https://archidekt.com/decks/123/test",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(401, deck_url_without_auth.status_code)
                self.assertEqual("authentication_required", deck_url_without_auth.json()["error"]["code"])

                add_without_auth = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(401, add_without_auth.status_code)
                self.assertEqual("authentication_required", add_without_auth.json()["error"]["code"])

                self._insert_inventory_item(
                    db_path,
                    inventory_slug="personal",
                    scryfall_id="api-card-1",
                )
                with connect(db_path) as connection:
                    item_id = int(connection.execute("SELECT id FROM inventory_items").fetchone()["id"])

                bulk_without_auth = client.post(
                    "/inventories/personal/items/bulk",
                    json={
                        "operation": "add_tags",
                        "item_ids": [item_id],
                        "tags": ["trade"],
                    },
                )
                self.assertEqual(401, bulk_without_auth.status_code)
                self.assertEqual("authentication_required", bulk_without_auth.json()["error"]["code"])

    def test_shared_service_access_summary_distinguishes_bootstrap_and_readable_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)

            create_inventory(
                db_path,
                slug="team",
                display_name="Team Collection",
                description=None,
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="team",
                actor_id="viewer-user@example.com",
                role="viewer",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                eligible_headers = {"X-Authenticated-User": "new-editor@example.com"}
                eligible_summary = client.get("/me/access-summary", headers=eligible_headers)
                self.assertEqual(200, eligible_summary.status_code)
                self.assertEqual(
                    {
                        "can_bootstrap": True,
                        "has_readable_inventory": False,
                        "visible_inventory_count": 0,
                        "default_inventory_slug": None,
                    },
                    eligible_summary.json(),
                )

                viewer_headers = {
                    "X-Authenticated-User": "viewer-user@example.com",
                    "X-Authenticated-Roles": "viewer",
                }
                viewer_summary = client.get("/me/access-summary", headers=viewer_headers)
                self.assertEqual(200, viewer_summary.status_code)
                self.assertEqual(
                    {
                        "can_bootstrap": True,
                        "has_readable_inventory": True,
                        "visible_inventory_count": 1,
                        "default_inventory_slug": None,
                    },
                    viewer_summary.json(),
                )

                outsider_headers = {
                    "X-Authenticated-User": "outsider-user@example.com",
                    "X-Authenticated-Roles": "viewer",
                }
                outsider_summary = client.get("/me/access-summary", headers=outsider_headers)
                self.assertEqual(200, outsider_summary.status_code)
                self.assertEqual(
                    {
                        "can_bootstrap": True,
                        "has_readable_inventory": False,
                        "visible_inventory_count": 0,
                        "default_inventory_slug": None,
                    },
                    outsider_summary.json(),
                )

    def test_shared_service_access_summary_reports_default_inventory_after_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            user_headers = {"X-Authenticated-User": "shared-user@example.com"}

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                pre_bootstrap = client.get("/me/access-summary", headers=user_headers)
                self.assertEqual(200, pre_bootstrap.status_code)
                self.assertEqual(
                    {
                        "can_bootstrap": True,
                        "has_readable_inventory": False,
                        "visible_inventory_count": 0,
                        "default_inventory_slug": None,
                    },
                    pre_bootstrap.json(),
                )

                created = client.post("/me/bootstrap", headers=user_headers)
                self.assertEqual(200, created.status_code)

                post_bootstrap = client.get("/me/access-summary", headers=user_headers)
                self.assertEqual(200, post_bootstrap.status_code)
                self.assertEqual(
                    {
                        "can_bootstrap": True,
                        "has_readable_inventory": True,
                        "visible_inventory_count": 1,
                        "default_inventory_slug": "shared-user-collection",
                    },
                    post_bootstrap.json(),
                )

    def test_shared_service_bootstrap_creates_one_default_inventory_and_unlocks_search(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            user_headers = {"X-Authenticated-User": "shared-user@example.com"}

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)

                pre_bootstrap_search = client.get("/cards/search", headers=user_headers, params={"query": "API Test"})
                self.assertEqual(403, pre_bootstrap_search.status_code)
                self.assertEqual("forbidden", pre_bootstrap_search.json()["error"]["code"])

                created = client.post("/me/bootstrap", headers=user_headers)
                self.assertEqual(200, created.status_code)
                self.assertTrue(created.json()["created"])
                self.assertEqual("Collection", created.json()["inventory"]["display_name"])
                self.assertEqual("shared-user-collection", created.json()["inventory"]["slug"])
                self.assertIsNone(created.json()["inventory"]["default_location"])
                self.assertIsNone(created.json()["inventory"]["default_tags"])
                self.assertIsNone(created.json()["inventory"]["notes"])
                self.assertIsNone(created.json()["inventory"]["acquisition_price"])
                self.assertIsNone(created.json()["inventory"]["acquisition_currency"])

                inventories = client.get("/inventories", headers=user_headers)
                self.assertEqual(200, inventories.status_code)
                self.assertEqual(["shared-user-collection"], [row["slug"] for row in inventories.json()])
                self.assertIsNone(inventories.json()[0]["default_location"])
                self.assertIsNone(inventories.json()[0]["default_tags"])
                self.assertIsNone(inventories.json()[0]["notes"])
                self.assertIsNone(inventories.json()[0]["acquisition_price"])
                self.assertIsNone(inventories.json()[0]["acquisition_currency"])

                repeated = client.post("/me/bootstrap", headers=user_headers)
                self.assertEqual(200, repeated.status_code)
                self.assertFalse(repeated.json()["created"])
                self.assertEqual(created.json()["inventory"], repeated.json()["inventory"])

                post_bootstrap_search = client.get("/cards/search", headers=user_headers, params={"query": "API Test"})
                self.assertEqual(200, post_bootstrap_search.status_code)

    def test_shared_service_bootstrap_creates_personal_default_even_when_user_has_shared_membership(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            user_headers = {"X-Authenticated-User": "viewer-user@example.com"}

            create_inventory(
                db_path,
                slug="team",
                display_name="Team Collection",
                description=None,
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="team",
                actor_id="viewer-user@example.com",
                role="viewer",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                created = client.post("/me/bootstrap", headers=user_headers)
                self.assertEqual(200, created.status_code)
                self.assertTrue(created.json()["created"])
                self.assertEqual("viewer-user-collection", created.json()["inventory"]["slug"])

                inventories = client.get("/inventories", headers=user_headers)
                self.assertEqual(200, inventories.status_code)
                self.assertEqual(
                    ["team", "viewer-user-collection"],
                    [row["slug"] for row in inventories.json()],
                )

    def test_shared_service_inventory_write_routes_allow_editors_and_owners_but_reject_viewers_and_non_members(self) -> None:
        from mtg_source_stack.inventory.deck_url_import import RemoteDeckCard, RemoteDeckSource

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            owner_headers = {"X-Authenticated-User": "owner-user"}
            viewer_headers = {
                "X-Authenticated-User": "viewer-user",
                "X-Authenticated-Roles": "viewer",
            }
            editor_headers = {
                "X-Authenticated-User": "editor-user",
                "X-Authenticated-Roles": "viewer",
            }
            outsider_headers = {"X-Authenticated-User": "outsider-user"}
            admin_headers = {
                "X-Authenticated-User": "admin-user",
                "X-Authenticated-Roles": "admin",
            }

            create_inventory(
                db_path,
                slug="admin-only",
                display_name="Admin Only",
                description=None,
            )
            create_inventory(
                db_path,
                slug="personal",
                display_name="Personal Collection",
                description=None,
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="viewer-user",
                role="viewer",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="personal",
                actor_id="editor-user",
                role="editor",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path, finishes_json='["normal","foil"]')

                viewer_add = client.post(
                    "/inventories/personal/items",
                    headers=viewer_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(403, viewer_add.status_code)
                self.assertEqual("forbidden", viewer_add.json()["error"]["code"])

                outsider_add = client.post(
                    "/inventories/personal/items",
                    headers=outsider_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(403, outsider_add.status_code)
                self.assertEqual("forbidden", outsider_add.json()["error"]["code"])

                editor_add = client.post(
                    "/inventories/personal/items",
                    headers=editor_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, editor_add.status_code)
                editor_item_id = editor_add.json()["item_id"]

                import_csv_body = (
                    "Inventory,Scryfall ID,Qty,Cond,Finish\n"
                    "personal,api-card-1,1,NM,normal\n"
                ).encode("utf-8")

                viewer_import = client.post(
                    "/imports/csv",
                    headers=viewer_headers,
                    files={"file": ("inventory_import.csv", import_csv_body, "text/csv")},
                )
                self.assertEqual(403, viewer_import.status_code)
                self.assertEqual("forbidden", viewer_import.json()["error"]["code"])

                outsider_import = client.post(
                    "/imports/csv",
                    headers=outsider_headers,
                    files={"file": ("inventory_import.csv", import_csv_body, "text/csv")},
                )
                self.assertEqual(403, outsider_import.status_code)
                self.assertEqual("forbidden", outsider_import.json()["error"]["code"])

                editor_import = client.post(
                    "/imports/csv",
                    headers=editor_headers,
                    files={"file": ("inventory_import.csv", import_csv_body, "text/csv")},
                )
                self.assertEqual(200, editor_import.status_code)
                self.assertEqual(1, editor_import.json()["rows_written"])

                viewer_decklist = client.post(
                    "/imports/decklist",
                    headers=viewer_headers,
                    json={
                        "deck_text": "1 API Test Card",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(403, viewer_decklist.status_code)
                self.assertEqual("forbidden", viewer_decklist.json()["error"]["code"])

                outsider_decklist = client.post(
                    "/imports/decklist",
                    headers=outsider_headers,
                    json={
                        "deck_text": "1 API Test Card",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(403, outsider_decklist.status_code)
                self.assertEqual("forbidden", outsider_decklist.json()["error"]["code"])

                editor_decklist = client.post(
                    "/imports/decklist",
                    headers=editor_headers,
                    json={
                        "deck_text": "1 API Test Card",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(200, editor_decklist.status_code)
                self.assertEqual(1, editor_decklist.json()["rows_written"])

                viewer_deck_url = client.post(
                    "/imports/deck-url",
                    headers=viewer_headers,
                    json={
                        "source_url": "https://archidekt.com/decks/123/test",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(403, viewer_deck_url.status_code)
                self.assertEqual("forbidden", viewer_deck_url.json()["error"]["code"])

                outsider_deck_url = client.post(
                    "/imports/deck-url",
                    headers=outsider_headers,
                    json={
                        "source_url": "https://archidekt.com/decks/123/test",
                        "default_inventory": "personal",
                    },
                )
                self.assertEqual(403, outsider_deck_url.status_code)
                self.assertEqual("forbidden", outsider_deck_url.json()["error"]["code"])

                with patch(
                    "mtg_source_stack.inventory.deck_url_import.fetch_remote_deck_source",
                    return_value=RemoteDeckSource(
                        provider="archidekt",
                        source_url="https://archidekt.com/decks/123/test",
                        deck_name="Shared Deck",
                        cards=[RemoteDeckCard(1, 1, "mainboard", "api-card-1", "normal")],
                    ),
                ):
                    editor_deck_url = client.post(
                        "/imports/deck-url",
                        headers=editor_headers,
                        json={
                            "source_url": "https://archidekt.com/decks/123/test",
                            "default_inventory": "personal",
                        },
                    )
                self.assertEqual(200, editor_deck_url.status_code)
                self.assertEqual(1, editor_deck_url.json()["rows_written"])

                viewer_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers=viewer_headers,
                    json={
                        "operation": "add_tags",
                        "item_ids": [editor_item_id],
                        "tags": ["trade"],
                    },
                )
                self.assertEqual(403, viewer_bulk.status_code)
                self.assertEqual("forbidden", viewer_bulk.json()["error"]["code"])

                outsider_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers=outsider_headers,
                    json={
                        "operation": "add_tags",
                        "item_ids": [editor_item_id],
                        "tags": ["trade"],
                    },
                )
                self.assertEqual(403, outsider_bulk.status_code)
                self.assertEqual("forbidden", outsider_bulk.json()["error"]["code"])

                editor_bulk = client.post(
                    "/inventories/personal/items/bulk",
                    headers=editor_headers,
                    json={
                        "operation": "add_tags",
                        "item_ids": [editor_item_id],
                        "tags": ["trade"],
                    },
                )
                self.assertEqual(200, editor_bulk.status_code)

                owner_patch = client.patch(
                    f"/inventories/personal/items/{editor_item_id}",
                    headers=owner_headers,
                    json={"notes": "owner note"},
                )
                self.assertEqual(200, owner_patch.status_code)

                viewer_patch = client.patch(
                    f"/inventories/personal/items/{editor_item_id}",
                    headers=viewer_headers,
                    json={"notes": "viewer note"},
                )
                self.assertEqual(403, viewer_patch.status_code)
                self.assertEqual("forbidden", viewer_patch.json()["error"]["code"])

                owner_delete = client.delete(
                    f"/inventories/personal/items/{editor_item_id}",
                    headers=owner_headers,
                )
                self.assertEqual(200, owner_delete.status_code)

                admin_add = client.post(
                    "/inventories/admin-only/items",
                    headers=admin_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, admin_add.status_code)

                admin_bulk = client.post(
                    "/inventories/admin-only/items/bulk",
                    headers=admin_headers,
                    json={
                        "operation": "add_tags",
                        "item_ids": [admin_add.json()["item_id"]],
                        "tags": ["admin"],
                    },
                )
                self.assertEqual(200, admin_bulk.status_code)

                editor_admin_only_add = client.post(
                    "/inventories/admin-only/items",
                    headers=editor_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(403, editor_admin_only_add.status_code)
                self.assertEqual("forbidden", editor_admin_only_add.json()["error"]["code"])

    def test_shared_service_transfer_requires_write_access_to_both_source_and_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            editor_headers = {
                "X-Authenticated-User": "editor-user",
                "X-Authenticated-Roles": "viewer",
            }
            admin_headers = {
                "X-Authenticated-User": "admin-user",
                "X-Authenticated-Roles": "admin",
            }

            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description=None,
                actor_id="owner-user",
            )
            create_inventory(
                db_path,
                slug="target",
                display_name="Target Collection",
                description=None,
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="source",
                actor_id="editor-user",
                role="editor",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
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

                denied = client.post(
                    "/inventories/source/transfer",
                    headers=editor_headers,
                    json={
                        "target_inventory_slug": "target",
                        "mode": "move",
                        "item_ids": [source_item_id],
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(403, denied.status_code)
                self.assertEqual("forbidden", denied.json()["error"]["code"])
                self.assertIn("Write access to inventory 'target'", denied.json()["error"]["message"])

                allowed = client.post(
                    "/inventories/source/transfer",
                    headers=admin_headers,
                    json={
                        "target_inventory_slug": " target ",
                        "mode": "move",
                        "item_ids": [source_item_id],
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(200, allowed.status_code)
                self.assertEqual("moved", allowed.json()["results"][0]["status"])
                self.assertEqual("target", allowed.json()["target_inventory"])

    def test_shared_service_transfer_allows_viewer_copy_out_to_writable_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            viewer_headers = {"X-Authenticated-User": "viewer-user"}

            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description=None,
                actor_id="owner-user",
            )
            create_inventory(
                db_path,
                slug="target-selected",
                display_name="Selected Copy Target",
                description=None,
                actor_id="viewer-user",
            )
            create_inventory(
                db_path,
                slug="target-all",
                display_name="All Rows Copy Target",
                description=None,
                actor_id="viewer-user",
            )
            create_inventory(
                db_path,
                slug="target-move",
                display_name="Move Target",
                description=None,
                actor_id="viewer-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="source",
                actor_id="viewer-user",
                role="viewer",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)
                self._insert_catalog_card(
                    db_path,
                    scryfall_id="api-card-2",
                    oracle_id="api-oracle-2",
                    name="API Test Card Two",
                    collector_number="11",
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
                    quantity=2,
                    tags_json='["copy"]',
                )
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-2",
                    quantity=1,
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

                selected_copy = client.post(
                    "/inventories/source/transfer",
                    headers=viewer_headers,
                    json={
                        "target_inventory_slug": "target-selected",
                        "mode": "copy",
                        "item_ids": [source_item_ids[0]],
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(200, selected_copy.status_code)
                self.assertEqual("copied", selected_copy.json()["results"][0]["status"])
                self.assertFalse(selected_copy.json()["results"][0]["source_removed"])

                all_copy = client.post(
                    "/inventories/source/transfer",
                    headers=viewer_headers,
                    json={
                        "target_inventory_slug": "target-all",
                        "mode": "copy",
                        "all_items": True,
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(200, all_copy.status_code)
                self.assertEqual("all_items", all_copy.json()["selection_kind"])
                self.assertEqual(2, all_copy.json()["copied_count"])

                denied_move = client.post(
                    "/inventories/source/transfer",
                    headers=viewer_headers,
                    json={
                        "target_inventory_slug": "target-move",
                        "mode": "move",
                        "item_ids": [source_item_ids[0]],
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(403, denied_move.status_code)
                self.assertEqual("forbidden", denied_move.json()["error"]["code"])

                source_rows = client.get("/inventories/source/items", headers=viewer_headers)
                selected_target_rows = client.get("/inventories/target-selected/items", headers=viewer_headers)
                all_target_rows = client.get("/inventories/target-all/items", headers=viewer_headers)
                self.assertEqual(200, source_rows.status_code)
                self.assertEqual(200, selected_target_rows.status_code)
                self.assertEqual(200, all_target_rows.status_code)
                self.assertEqual(2, len(source_rows.json()))
                self.assertEqual(1, len(selected_target_rows.json()))
                self.assertEqual(2, len(all_target_rows.json()))

    def test_shared_service_transfer_rejects_no_access_copy_from_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            outsider_headers = {"X-Authenticated-User": "outsider-user"}

            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description=None,
                actor_id="owner-user",
            )
            create_inventory(
                db_path,
                slug="target",
                display_name="Outsider Target",
                description=None,
                actor_id="outsider-user",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
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

                denied = client.post(
                    "/inventories/source/transfer",
                    headers=outsider_headers,
                    json={
                        "target_inventory_slug": "target",
                        "mode": "copy",
                        "item_ids": [source_item_id],
                        "on_conflict": "fail",
                    },
                )
                self.assertEqual(403, denied.status_code)
                self.assertEqual("forbidden", denied.json()["error"]["code"])

    def test_shared_service_duplicate_requires_source_write_access_and_grants_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            read_only_headers = {
                "X-Authenticated-User": "read-only-user",
                "X-Authenticated-Roles": "viewer",
            }
            writer_headers = {"X-Authenticated-User": "writer-user"}

            create_inventory(
                db_path,
                slug="source",
                display_name="Source Collection",
                description="Original description",
                actor_id="owner-user",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="source",
                actor_id="read-only-user",
                role="viewer",
            )
            grant_inventory_membership(
                db_path,
                inventory_slug="source",
                actor_id="writer-user",
                role="editor",
            )

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)
                self._insert_inventory_item(
                    db_path,
                    inventory_slug="source",
                    scryfall_id="api-card-1",
                    quantity=1,
                )

                denied = client.post(
                    "/inventories/source/duplicate",
                    headers=read_only_headers,
                    json={
                        "target_slug": "source-copy",
                        "target_display_name": "Source Copy",
                    },
                )
                self.assertEqual(403, denied.status_code)
                self.assertEqual("forbidden", denied.json()["error"]["code"])
                self.assertIn("Write access to inventory 'source' is required", denied.json()["error"]["message"])

                allowed = client.post(
                    "/inventories/source/duplicate",
                    headers=writer_headers,
                    json={
                        "target_slug": " source-copy ",
                        "target_display_name": "Source Copy",
                    },
                )
                self.assertEqual(201, allowed.status_code)
                self.assertEqual("source-copy", allowed.json()["inventory"]["slug"])
                self.assertEqual("source-copy", allowed.json()["transfer"]["target_inventory"])
                self.assertEqual(1, allowed.json()["transfer"]["copied_count"])
                self.assertEqual(
                    "owner",
                    actor_inventory_role(
                        db_path,
                        inventory_slug="source-copy",
                        actor_id="writer-user",
                    ),
                )

    def test_shared_service_uses_authenticated_actor_header_for_audit_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            auth_headers = {"X-Authenticated-User": "shared-user", "X-Request-Id": "req-shared-add"}

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    headers={"X-Authenticated-User": "shared-user"},
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    headers=auth_headers,
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)

                patched = client.patch(
                    f"/inventories/personal/items/{added.json()['item_id']}",
                    headers={"X-Authenticated-User": "shared-user", "X-Request-Id": "req-shared-finish"},
                    json={"finish": "foil"},
                )
                self.assertEqual(200, patched.status_code)

                audit = client.get(
                    "/inventories/personal/audit",
                    headers={"X-Authenticated-User": "shared-user"},
                )
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_finish", audit.json()[0]["action"])
                self.assertEqual("api", audit.json()[0]["actor_type"])
                self.assertEqual("shared-user", audit.json()[0]["actor_id"])
                self.assertEqual("req-shared-finish", audit.json()[0]["request_id"])

    def test_demo_api_can_optionally_trust_actor_headers_in_dev_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path, trust_actor_headers=True) as client:
                self._seed_card(db_path)

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = client.post(
                    "/inventories/personal/items",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-dev-mode"},
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("add_card", audit.json()[0]["action"])
                self.assertEqual("api", audit.json()[0]["actor_type"])
                self.assertEqual("web-user", audit.json()[0]["actor_id"])
                self.assertEqual("req-dev-mode", audit.json()[0]["request_id"])

                health = client.get("/health")
                self.assertEqual(200, health.status_code)
                self.assertTrue(health.json()["trusted_actor_headers"])

    def test_demo_api_returns_contract_error_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                missing_inventory = client.get("/inventories/missing/items")
                self.assertEqual(404, missing_inventory.status_code)
                self.assertEqual("not_found", missing_inventory.json()["error"]["code"])

                invalid_patch = client.patch(
                    "/inventories/missing/items/1",
                    json={"quantity": 1, "finish": "foil"},
                )
                self.assertEqual(400, invalid_patch.status_code)
                self.assertEqual("validation_error", invalid_patch.json()["error"]["code"])

    def test_demo_api_rejects_unsupported_finishes_for_a_printing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                self._seed_card(db_path, finishes_json='["normal"]')

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                invalid_add = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "foil",
                    },
                )
                self.assertEqual(400, invalid_add.status_code)
                self.assertEqual("validation_error", invalid_add.json()["error"]["code"])
                self.assertIn("Available finishes: normal", invalid_add.json()["error"]["message"])

                added = client.post(
                    "/inventories/personal/items",
                    json={
                        "scryfall_id": "api-card-1",
                        "quantity": 1,
                        "condition_code": "NM",
                        "finish": "normal",
                    },
                )
                self.assertEqual(201, added.status_code)

                invalid_finish_patch = client.patch(
                    f"/inventories/personal/items/{added.json()['item_id']}",
                    json={"finish": "foil"},
                )
                self.assertEqual(400, invalid_finish_patch.status_code)
                self.assertEqual("validation_error", invalid_finish_patch.json()["error"]["code"])
                self.assertIn(
                    "Available finishes: normal",
                    invalid_finish_patch.json()["error"]["message"],
                )

    def test_demo_api_rejects_blank_search_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                blank = client.get("/cards/search", params={"query": ""})
                self.assertEqual(400, blank.status_code)
                self.assertEqual("validation_error", blank.json()["error"]["code"])
                self.assertIn("query is required", blank.json()["error"]["message"])

                whitespace = client.get("/cards/search", params={"query": "   "})
                self.assertEqual(400, whitespace.status_code)
                self.assertEqual("validation_error", whitespace.json()["error"]["code"])
                self.assertIn("query is required", whitespace.json()["error"]["message"])

                grouped_blank = client.get("/cards/search/names", params={"query": ""})
                self.assertEqual(400, grouped_blank.status_code)
                self.assertEqual("validation_error", grouped_blank.json()["error"]["code"])
                self.assertIn("query is required", grouped_blank.json()["error"]["message"])

    def test_demo_api_rejects_invalid_limit_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                responses = [
                    client.get("/cards/search", params={"query": "API", "limit": -1}),
                    client.get("/cards/search", params={"query": "API", "limit": 0}),
                    client.get("/inventories/personal/items", params={"limit": -1}),
                    client.get("/inventories/personal/audit", params={"limit": -1}),
                ]

                for response in responses:
                    self.assertEqual(400, response.status_code)
                    self.assertEqual("validation_error", response.json()["error"]["code"])

    def test_demo_api_rejects_invalid_catalog_scope_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            with self._client(db_path) as client:
                responses = [
                    client.get("/cards/search", params={"query": "API", "scope": "weird"}),
                    client.get("/cards/search/names", params={"query": "API", "scope": "weird"}),
                    client.get("/cards/oracle/missing-oracle/printings", params={"scope": "weird"}),
                ]

                for response in responses:
                    self.assertEqual(400, response.status_code)
                    self.assertEqual("validation_error", response.json()["error"]["code"])
                    self.assertIn("scope must be one of: default, all.", response.json()["error"]["message"])
