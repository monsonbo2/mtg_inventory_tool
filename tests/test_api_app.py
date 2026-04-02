"""Focused tests for API app operational behavior."""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from mtg_source_stack.api.app import build_arg_parser, settings_from_cli_args


FASTAPI_TESTING_AVAILABLE = (
    importlib.util.find_spec("fastapi") is not None
    and importlib.util.find_spec("httpx") is not None
    and importlib.util.find_spec("uvicorn") is not None
)

if FASTAPI_TESTING_AVAILABLE:
    import httpx
    from fastapi import status
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
    FASTAPI_TESTING_AVAILABLE and LOCALHOST_SERVER_TESTING_AVAILABLE,
    "fastapi/httpx/uvicorn or localhost socket access are unavailable; live API app tests are skipped.",
)
class ApiAppTest(unittest.TestCase):
    @contextmanager
    def _client(self, db_path: Path, *, runtime_mode: str = "local_demo", auto_migrate: bool = True):
        app = create_app(
            ApiSettings(
                db_path=db_path,
                runtime_mode=runtime_mode,
                auto_migrate=auto_migrate,
                host="127.0.0.1",
                port=8000,
            )
        )
        with _live_test_server(app) as base_url:
            with httpx.Client(base_url=base_url, timeout=5.0) as client:
                yield client, app

    def test_unexpected_exceptions_are_logged_and_return_generic_500(self) -> None:
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

            @app.get("/boom")
            async def boom() -> None:
                raise RuntimeError("kaboom")

            with _live_test_server(app) as base_url:
                client = httpx.Client(base_url=base_url, timeout=5.0)
                with patch("mtg_source_stack.api.app.logger") as mock_logger:
                    try:
                        response = client.get("/boom", headers={"X-Request-Id": "req-boom"})
                    finally:
                        client.close()

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

    def test_shared_service_mode_starts_against_prepared_db_without_auto_migrate(self) -> None:
        from mtg_source_stack.db.schema import initialize_database

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)

            with self._client(db_path, runtime_mode="shared_service", auto_migrate=False) as (client, _app):
                response = client.get("/health")

            self.assertEqual(status.HTTP_200_OK, response.status_code)
            self.assertFalse(response.json()["auto_migrate"])

    def test_startup_logging_includes_runtime_mode_and_effective_auto_migrate(self) -> None:
        from mtg_source_stack.db.schema import initialize_database

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)

            with patch("mtg_source_stack.api.app.logger") as mock_logger:
                with self._client(db_path, runtime_mode="shared_service", auto_migrate=False):
                    pass

            mock_logger.info.assert_any_call(
                "Starting API runtime_mode=%s db_path=%s auto_migrate=%s trust_actor_headers=%s",
                "shared_service",
                db_path,
                False,
                False,
            )


class ApiCliSettingsTest(unittest.TestCase):
    def test_cli_settings_can_enable_auto_migrate_in_shared_service_mode(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--runtime-mode", "shared_service", "--auto-migrate"])

        with patch.dict("os.environ", {}, clear=True):
            settings = settings_from_cli_args(args)

        self.assertEqual("shared_service", settings.runtime_mode)
        self.assertTrue(settings.auto_migrate)

    def test_cli_settings_can_disable_auto_migrate_in_local_demo_mode(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--runtime-mode", "local_demo", "--no-auto-migrate"])

        with patch.dict("os.environ", {}, clear=True):
            settings = settings_from_cli_args(args)

        self.assertEqual("local_demo", settings.runtime_mode)
        self.assertFalse(settings.auto_migrate)

    def test_env_auto_migrate_override_wins_over_cli_flag(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--runtime-mode", "shared_service", "--auto-migrate"])

        with patch.dict("os.environ", {"MTG_API_AUTO_MIGRATE": "false"}, clear=True):
            settings = settings_from_cli_args(args)

        self.assertEqual("shared_service", settings.runtime_mode)
        self.assertFalse(settings.auto_migrate)
