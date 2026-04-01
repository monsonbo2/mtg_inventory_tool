"""Focused tests for API app operational behavior."""

from __future__ import annotations

from contextlib import asynccontextmanager
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


FASTAPI_TESTING_AVAILABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
)

if FASTAPI_TESTING_AVAILABLE:
    import httpx
    from fastapi import status

    from mtg_source_stack.api.app import create_app
    from mtg_source_stack.api.dependencies import ApiSettings


@unittest.skipUnless(
    FASTAPI_TESTING_AVAILABLE,
    "fastapi/httpx are not installed in this environment; API app tests are skipped.",
)
class ApiAppTest(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def _client(self, db_path: Path):
        app = create_app(
            ApiSettings(
                db_path=db_path,
                auto_migrate=True,
                host="127.0.0.1",
                port=8000,
            )
        )
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        try:
            transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                yield client, app
        finally:
            await lifespan.__aexit__(None, None, None)

    async def test_unexpected_exceptions_are_logged_and_return_generic_500(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"

            async with self._client(db_path) as (client, app):

                @app.get("/boom")
                async def boom() -> None:
                    raise RuntimeError("kaboom")

                with patch("mtg_source_stack.api.app.logger") as mock_logger:
                    response = await client.get("/boom", headers={"X-Request-Id": "req-boom"})

                self.assertEqual(status.HTTP_500_INTERNAL_SERVER_ERROR, response.status_code)
                self.assertEqual(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "Internal server error.",
                        }
                    },
                    response.json(),
                )
                self.assertEqual("req-boom", response.headers["X-Request-Id"])
                mock_logger.exception.assert_called_once()
                log_args = mock_logger.exception.call_args[0]
                self.assertIn("Unhandled API error", log_args[0])
                self.assertEqual("req-boom", log_args[1])
                self.assertEqual("GET", log_args[2])
                self.assertEqual("/boom", log_args[3])
