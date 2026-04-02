"""Integration-oriented smoke tests for the FastAPI web shell."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import importlib.util
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database


FASTAPI_TESTING_AVAILABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
    and importlib.util.find_spec("uvicorn") is not None
)

if FASTAPI_TESTING_AVAILABLE:
    import httpx
    import uvicorn

    from mtg_source_stack.api.app import create_app
    from mtg_source_stack.api.dependencies import ApiSettings


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
    FASTAPI_TESTING_AVAILABLE,
    "fastapi/httpx/uvicorn are not installed in this environment; API shell tests are skipped.",
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
                ("/cards/search", "get"),
                ("/inventories", "post"),
                ("/inventories/{inventory_slug}/items", "get"),
                ("/inventories/{inventory_slug}/items", "post"),
                ("/inventories/{inventory_slug}/items/{item_id}", "patch"),
                ("/inventories/{inventory_slug}/items/{item_id}", "delete"),
                ("/inventories/{inventory_slug}/audit", "get"),
            ]:
                self.assertNotIn("422", spec["paths"][path][method]["responses"])

            for path, method in [
                ("/inventories", "post"),
                ("/inventories/{inventory_slug}/items", "post"),
                ("/inventories/{inventory_slug}/items/{item_id}", "patch"),
                ("/inventories/{inventory_slug}/items/{item_id}", "delete"),
            ]:
                self.assertIn("401", spec["paths"][path][method]["responses"])

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
    FASTAPI_TESTING_AVAILABLE and LOCALHOST_SERVER_TESTING_AVAILABLE,
    "fastapi/httpx/uvicorn or localhost socket access are unavailable; live API shell tests are skipped.",
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
    ):
        app = create_app(
            ApiSettings(
                db_path=db_path,
                runtime_mode=runtime_mode,
                auto_migrate=auto_migrate,
                host="127.0.0.1",
                port=8000,
                trust_actor_headers=trust_actor_headers,
            )
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
                self.assertEqual("req-add", added.headers["X-Request-Id"])

                listed = client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertEqual(1, len(listed.json()))
                self.assertEqual(2, listed.json()[0]["quantity"])
                self.assertEqual(["normal", "foil"], listed.json()[0]["allowed_finishes"])
                self.assertEqual(
                    "https://example.test/cards/api-card-1-small.jpg",
                    listed.json()[0]["image_uri_small"],
                )
                self.assertEqual(
                    "https://example.test/cards/api-card-1-normal.jpg",
                    listed.json()[0]["image_uri_normal"],
                )

                patched = client.patch(
                    f"/inventories/personal/items/{added_payload['item_id']}",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-finish"},
                    json={"finish": "foil"},
                )
                self.assertEqual(200, patched.status_code)
                self.assertEqual("set_finish", patched.json()["operation"])
                self.assertEqual("foil", patched.json()["finish"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_finish", audit.json()[0]["action"])
                self.assertEqual("api", audit.json()[0]["actor_type"])
                self.assertEqual("local-demo", audit.json()[0]["actor_id"])
                self.assertEqual("req-finish", audit.json()[0]["request_id"])
                self.assertRegex(audit.json()[0]["occurred_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_shared_service_mode_handles_a_small_concurrent_request_burst(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)
            auth_headers = {"X-Authenticated-User": "shared-user"}

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)

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
                    response = client.get("/inventories")
                    self.assertEqual(200, response.status_code)
                    return response.status_code

                def get_items():
                    response = client.get("/inventories/personal/items")
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
                    response = client.get("/inventories/personal/audit")
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

    def test_shared_service_mutating_requests_require_authenticated_actor_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as client:
                self._seed_card(db_path)

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

                created_inventory = client.post(
                    "/inventories",
                    headers={"X-Authenticated-User": "shared-user"},
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

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

                audit = client.get("/inventories/personal/audit")
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
