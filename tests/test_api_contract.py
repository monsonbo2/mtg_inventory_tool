"""Contract-focused tests for API-facing serialization and error mapping."""

from __future__ import annotations

from decimal import Decimal
import sqlite3
import tempfile
from pathlib import Path

from tests.common import RepoSmokeTestCase
from mtg_source_stack.api_contract import api_error_payload, api_error_status
from mtg_source_stack.db.schema import initialize_database, require_current_schema
from mtg_source_stack.errors import ConflictError, NotFoundError, SchemaNotReadyError, ValidationError
from mtg_source_stack.inventory.response_models import serialize_response
from mtg_source_stack.inventory.service import create_inventory, reconcile_prices


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

    def test_require_current_schema_raises_schema_not_ready_for_unmigrated_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "unmigrated.db"
            sqlite3.connect(db_path).close()

            with self.assertRaises(SchemaNotReadyError):
                require_current_schema(db_path)
