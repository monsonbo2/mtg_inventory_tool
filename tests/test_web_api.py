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
from unittest.mock import patch

from mtg_source_stack.db.connection import connect
from mtg_source_stack.db.schema import initialize_database
from mtg_source_stack.inventory.service import create_inventory, grant_inventory_membership


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
                ("/cards/search/names", "get"),
                ("/cards/oracle/{oracle_id}/printings", "get"),
                ("/inventories", "post"),
                ("/inventories/{inventory_slug}/items", "get"),
                ("/inventories/{inventory_slug}/items", "post"),
                ("/inventories/{inventory_slug}/items/bulk", "post"),
                ("/inventories/{inventory_slug}/items/{item_id}", "patch"),
                ("/inventories/{inventory_slug}/items/{item_id}", "delete"),
                ("/inventories/{inventory_slug}/audit", "get"),
            ]:
                self.assertNotIn("422", spec["paths"][path][method]["responses"])

            for path, method in [
                ("/inventories", "get"),
                ("/inventories", "post"),
                ("/cards/search", "get"),
                ("/cards/search/names", "get"),
                ("/cards/oracle/{oracle_id}/printings", "get"),
                ("/inventories/{inventory_slug}/items", "get"),
                ("/inventories/{inventory_slug}/items", "post"),
                ("/inventories/{inventory_slug}/items/bulk", "post"),
                ("/inventories/{inventory_slug}/items/{item_id}", "patch"),
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

            card_names_schema = spec["paths"]["/cards/search/names"]["get"]["responses"]["200"]["content"][
                "application/json"
            ]["schema"]
            self.assertEqual("array", card_names_schema["type"])
            card_name_schema_name = self._schema_name_from_ref(card_names_schema["items"]["$ref"])
            self.assertEqual("CatalogNameSearchRowResponse", card_name_schema_name)
            self.assertEqual(
                "array",
                components[card_name_schema_name]["properties"]["available_languages"]["type"],
            )
            self.assertEqual(
                "string",
                components[card_name_schema_name]["properties"]["available_languages"]["items"]["type"],
            )

            printings_schema = spec["paths"]["/cards/oracle/{oracle_id}/printings"]["get"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            self.assertEqual("array", printings_schema["type"])
            self.assertEqual(
                "CatalogSearchRowResponse",
                self._schema_name_from_ref(printings_schema["items"]["$ref"]),
            )
            printings_parameters = {
                parameter["name"]: parameter
                for parameter in spec["paths"]["/cards/oracle/{oracle_id}/printings"]["get"]["parameters"]
            }
            self.assertIn("Use `all` to include every available catalog language", printings_parameters["lang"]["description"])

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

            add_request_schema = components["AddInventoryItemRequest"]
            self.assertIn("oracle_id", add_request_schema["properties"])
            self.assertNotIn("default", add_request_schema["properties"]["language_code"])
            self.assertIn(
                "inherits the resolved printing language",
                add_request_schema["properties"]["language_code"]["description"],
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

            bulk_request_schema = components["BulkInventoryItemMutationRequest"]
            self.assertIn("supports only tag operations", bulk_request_schema["description"])
            self.assertEqual(
                ["add_tags", "remove_tags", "set_tags", "clear_tags"],
                bulk_request_schema["properties"]["operation"]["enum"],
            )
            self.assertEqual(1, bulk_request_schema["properties"]["item_ids"]["minItems"])
            self.assertEqual(100, bulk_request_schema["properties"]["item_ids"]["maxItems"])

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
        settings_kwargs = {
            "db_path": db_path,
            "runtime_mode": runtime_mode,
            "auto_migrate": auto_migrate,
            "host": "127.0.0.1",
            "port": 8000,
            "trust_actor_headers": trust_actor_headers,
            "proxy_headers": runtime_mode == "shared_service",
        }
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
                    tags_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, '[]')
                """,
                (
                    inventory["id"],
                    scryfall_id,
                    quantity,
                    condition_code,
                    finish,
                    language_code,
                    location,
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
                self.assertEqual(1, len(name_search.json()))
                self.assertEqual("api-oracle-lookup", name_search.json()[0]["oracle_id"])
                self.assertEqual(["en", "ja"], name_search.json()[0]["available_languages"])
                self.assertEqual(
                    "https://example.test/cards/api-printing-en-new-small.jpg",
                    name_search.json()[0]["image_uri_small"],
                )

                default_printings = client.get("/cards/oracle/api-oracle-lookup/printings")
                self.assertEqual(200, default_printings.status_code)
                self.assertEqual(
                    ["api-printing-en-new", "api-printing-en-old"],
                    [row["scryfall_id"] for row in default_printings.json()],
                )

                all_printings = client.get(
                    "/cards/oracle/api-oracle-lookup/printings",
                    params={"lang": "all"},
                )
                self.assertEqual(200, all_printings.status_code)
                self.assertEqual(
                    ["api-printing-ja", "api-printing-en-new", "api-printing-en-old"],
                    [row["scryfall_id"] for row in all_printings.json()],
                )

                japanese_printings = client.get(
                    "/cards/oracle/api-oracle-lookup/printings",
                    params={"lang": "ja"},
                )
                self.assertEqual(200, japanese_printings.status_code)
                self.assertEqual(["api-printing-ja"], [row["scryfall_id"] for row in japanese_printings.json()])

                missing = client.get("/cards/oracle/missing-oracle/printings")
                self.assertEqual(404, missing.status_code)
                self.assertEqual("not_found", missing.json()["error"]["code"])

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

                outsider_inventories = client.get("/inventories", headers=outsider_headers)
                self.assertEqual(200, outsider_inventories.status_code)
                self.assertEqual([], outsider_inventories.json())

                admin_inventories = client.get("/inventories", headers=admin_headers)
                self.assertEqual(200, admin_inventories.status_code)
                self.assertEqual(
                    ["admin-only", "personal"],
                    [row["slug"] for row in admin_inventories.json()],
                )

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

    def test_shared_service_inventory_write_routes_allow_editors_and_owners_but_reject_viewers_and_non_members(self) -> None:
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
            outsider_headers = {
                "X-Authenticated-User": "outsider-user",
                "X-Authenticated-Roles": "viewer",
            }
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
