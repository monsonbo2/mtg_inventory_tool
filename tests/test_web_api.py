"""Integration-oriented smoke tests for the FastAPI demo shell."""

from __future__ import annotations

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
    from fastapi.testclient import TestClient

    from mtg_source_stack.api.app import create_app
    from mtg_source_stack.api.dependencies import ApiSettings


@unittest.skipUnless(
    FASTAPI_TESTING_AVAILABLE,
    "fastapi/httpx are not installed in this environment; API shell tests are skipped.",
)
class WebApiTest(unittest.TestCase):
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
                    finishes_json
                )
                VALUES (?, ?, ?, 'tst', 'Test Set', '10', '["normal","foil"]')
                """,
                ("api-card-1", "api-oracle-1", "API Test Card"),
            )
            connection.commit()

    def test_demo_api_exposes_inventory_item_and_audit_routes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            app = create_app(ApiSettings(db_path=db_path, auto_migrate=True, host="127.0.0.1", port=8000))

            with TestClient(app) as client:
                self._seed_card(db_path)

                health = client.get("/health")
                self.assertEqual(200, health.status_code)
                self.assertEqual("ok", health.json()["status"])

                created_inventory = client.post(
                    "/inventories",
                    json={"slug": "personal", "display_name": "Personal Collection"},
                )
                self.assertEqual(201, created_inventory.status_code)
                self.assertEqual("personal", created_inventory.json()["slug"])

                search = client.get("/cards/search", params={"query": "API Test"})
                self.assertEqual(200, search.status_code)
                self.assertEqual("api-card-1", search.json()[0]["scryfall_id"])

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

                patched = client.patch(
                    f"/inventories/personal/items/{added_payload['item_id']}",
                    headers={"X-Actor-Id": "web-user", "X-Request-Id": "req-finish"},
                    json={"finish": "foil"},
                )
                self.assertEqual(200, patched.status_code)
                self.assertEqual("foil", patched.json()["finish"])

                audit = client.get("/inventories/personal/audit")
                self.assertEqual(200, audit.status_code)
                self.assertEqual("set_finish", audit.json()[0]["action"])
                self.assertEqual("api", audit.json()[0]["actor_type"])
                self.assertEqual("web-user", audit.json()[0]["actor_id"])
                self.assertEqual("req-finish", audit.json()[0]["request_id"])

    def test_demo_api_returns_contract_error_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            app = create_app(ApiSettings(db_path=db_path, auto_migrate=True, host="127.0.0.1", port=8000))

            with TestClient(app) as client:
                missing_inventory = client.get("/inventories/missing/items")
                self.assertEqual(404, missing_inventory.status_code)
                self.assertEqual("not_found", missing_inventory.json()["error"]["code"])

                invalid_patch = client.patch(
                    "/inventories/missing/items/1",
                    json={"quantity": 1, "finish": "foil"},
                )
                self.assertEqual(400, invalid_patch.status_code)
                self.assertEqual("validation_error", invalid_patch.json()["error"]["code"])
