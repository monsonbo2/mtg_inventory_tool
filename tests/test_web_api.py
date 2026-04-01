"""Integration-oriented smoke tests for the FastAPI demo shell."""

from __future__ import annotations

from contextlib import asynccontextmanager
import importlib.util
import tempfile
import unittest
from pathlib import Path

from mtg_source_stack.db.connection import connect


FASTAPI_TESTING_AVAILABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)

if FASTAPI_TESTING_AVAILABLE:
    import httpx

    from mtg_source_stack.api.app import create_app
    from mtg_source_stack.api.dependencies import ApiSettings


@unittest.skipUnless(
    FASTAPI_TESTING_AVAILABLE,
    "fastapi/httpx are not installed in this environment; API shell tests are skipped.",
)
class WebApiTest(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _client(self, db_path: Path, *, trust_actor_headers: bool = False):
        app = create_app(
            ApiSettings(
                db_path=db_path,
                auto_migrate=True,
                host="127.0.0.1",
                port=8000,
                trust_actor_headers=trust_actor_headers,
            )
        )
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield client
        finally:
            await lifespan.__aexit__(None, None, None)

    def _seed_card(self, db_path: Path) -> None:
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
                    '["normal","foil"]',
                    '{"small":"https://example.test/cards/api-card-1-small.jpg","normal":"https://example.test/cards/api-card-1-normal.jpg"}'
                )
                """,
                ("api-card-1", "api-oracle-1", "API Test Card"),
            )
            connection.commit()

    def _schema_name_from_ref(self, ref: str) -> str:
        return ref.rsplit("/", 1)[-1]

    def test_demo_api_openapi_exposes_typed_response_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            app = create_app(
                ApiSettings(
                    db_path=db_path,
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

            patch_schema = spec["paths"]["/inventories/{inventory_slug}/items/{item_id}"]["patch"]["responses"]["200"][
                "content"
            ]["application/json"]["schema"]
            self.assertIn("anyOf", patch_schema)
            self.assertGreaterEqual(len(patch_schema["anyOf"]), 2)

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

    async def test_demo_api_exposes_inventory_item_and_audit_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            async with self._client(db_path) as client:
                self._seed_card(db_path)

                health = await client.get("/health")
                self.assertEqual(200, health.status_code)
                self.assertEqual("ok", health.json()["status"])
                self.assertTrue(health.json()["auto_migrate"])
                self.assertFalse(health.json()["trusted_actor_headers"])
                self.assertNotIn("db_path", health.json())

                created_inventory = await client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)
                self.assertEqual("personal", created_inventory.json()["slug"])

                search = await client.get("/cards/search", params={"query": "API Test"})
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

                added = await client.post(
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

                listed = await client.get("/inventories/personal/items")
                self.assertEqual(200, listed.status_code)
                self.assertEqual(1, len(listed.json()))
                self.assertEqual(2, listed.json()[0]["quantity"])
                self.assertEqual(
                    "https://example.test/cards/api-card-1-small.jpg",
                    listed.json()[0]["image_uri_small"],
                )
                self.assertEqual(
                    "https://example.test/cards/api-card-1-normal.jpg",
                    listed.json()[0]["image_uri_normal"],
                )

                patched = await client.patch(
                    f"/inventories/personal/items/{added_payload['item_id']}",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-finish"},
                    json={"finish": "foil"},
                )
                self.assertEqual(200, patched.status_code)
                self.assertEqual("foil", patched.json()["finish"])

                audit = await client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_finish", audit.json()[0]["action"])
                self.assertEqual("api", audit.json()[0]["actor_type"])
                self.assertEqual("local-demo", audit.json()[0]["actor_id"])
                self.assertEqual("req-finish", audit.json()[0]["request_id"])

    async def test_demo_api_can_optionally_trust_actor_headers_in_dev_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            async with self._client(db_path, trust_actor_headers=True) as client:
                self._seed_card(db_path)

                created_inventory = await client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)

                added = await client.post(
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

                audit = await client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("add_card", audit.json()[0]["action"])
                self.assertEqual("api", audit.json()[0]["actor_type"])
                self.assertEqual("web-user", audit.json()[0]["actor_id"])
                self.assertEqual("req-dev-mode", audit.json()[0]["request_id"])

                health = await client.get("/health")
                self.assertEqual(200, health.status_code)
                self.assertTrue(health.json()["trusted_actor_headers"])

    async def test_demo_api_returns_contract_error_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            async with self._client(db_path) as client:
                missing_inventory = await client.get("/inventories/missing/items")
                self.assertEqual(404, missing_inventory.status_code)
                self.assertEqual("not_found", missing_inventory.json()["error"]["code"])

                invalid_patch = await client.patch(
                    "/inventories/missing/items/1",
                    json={"quantity": 1, "finish": "foil"},
                )
                self.assertEqual(400, invalid_patch.status_code)
                self.assertEqual("validation_error", invalid_patch.json()["error"]["code"])

    async def test_demo_api_rejects_invalid_limit_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            async with self._client(db_path) as client:
                responses = [
                    await client.get("/cards/search", params={"query": "API", "limit": -1}),
                    await client.get("/cards/search", params={"query": "API", "limit": 0}),
                    await client.get("/inventories/personal/items", params={"limit": -1}),
                    await client.get("/inventories/personal/audit", params={"limit": -1}),
                ]

                for response in responses:
                    self.assertEqual(400, response.status_code)
                    self.assertEqual("validation_error", response.json()["error"]["code"])
