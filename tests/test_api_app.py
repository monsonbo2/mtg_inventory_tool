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

from mtg_source_stack.api.app import build_arg_parser, main, settings_from_cli_args


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
    def _client(
        self,
        db_path: Path,
        *,
        runtime_mode: str = "local_demo",
        auto_migrate: bool = True,
        **setting_overrides,
    ):
        settings_kwargs = {
            "db_path": db_path,
            "runtime_mode": runtime_mode,
            "auto_migrate": auto_migrate,
            "host": "127.0.0.1",
            "port": 8000,
            "proxy_headers": runtime_mode == "shared_service",
        }
        if runtime_mode == "shared_service":
            settings_kwargs["snapshot_signing_secret"] = "test-shared-snapshot-secret"
        settings_kwargs.update(setting_overrides)
        app = create_app(
            ApiSettings(**settings_kwargs)
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
        from mtg_source_stack.db.connection import SQLITE_BUSY_TIMEOUT_MS, SQLITE_JOURNAL_MODE, SQLITE_SYNCHRONOUS_MODE
        from mtg_source_stack.db.schema import initialize_database

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            initialize_database(db_path)

            with patch("mtg_source_stack.api.app.logger") as mock_logger:
                with self._client(
                    db_path,
                    runtime_mode="shared_service",
                    auto_migrate=False,
                    authenticated_actor_header="X-Verified-User",
                    authenticated_roles_header="X-Verified-Roles",
                    proxy_headers=True,
                    forwarded_allow_ips="127.0.0.1",
                ):
                    pass

            mock_logger.info.assert_any_call(
                "Starting API runtime_mode=%s db_path=%s auto_migrate=%s trust_actor_headers=%s proxy_headers=%s forwarded_allow_ips=%s",
                "shared_service",
                db_path,
                False,
                False,
                True,
                "127.0.0.1",
            )
            mock_logger.info.assert_any_call(
                "Shared-service auth posture authenticated_actor_header=%s authenticated_roles_header=%s",
                "X-Verified-User",
                "X-Verified-Roles",
            )
            mock_logger.info.assert_any_call(
                "SQLite runtime posture db_path=%s journal_mode=%s synchronous=%s busy_timeout_ms=%s foreign_keys=%s",
                db_path,
                SQLITE_JOURNAL_MODE,
                SQLITE_SYNCHRONOUS_MODE,
                SQLITE_BUSY_TIMEOUT_MS,
                True,
            )

    def test_shared_service_rejects_trusted_actor_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"

            with self.assertRaisesRegex(ValueError, "trust_actor_headers"):
                create_app(
                    ApiSettings(
                        db_path=db_path,
                        runtime_mode="shared_service",
                        auto_migrate=False,
                        host="127.0.0.1",
                        port=8000,
                        snapshot_signing_secret="test-shared-snapshot-secret",
                        trust_actor_headers=True,
                    )
                )

    def test_shared_service_requires_snapshot_signing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"

            with self.assertRaisesRegex(ValueError, "snapshot_signing_secret"):
                create_app(
                    ApiSettings(
                        db_path=db_path,
                        runtime_mode="shared_service",
                        auto_migrate=False,
                        host="127.0.0.1",
                        port=8000,
                    )
                )

    def test_shared_service_rejects_colliding_or_blank_verified_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "api.db"
            scenarios = (
                {"authenticated_actor_header": "", "authenticated_roles_header": "X-Authenticated-Roles"},
                {"authenticated_actor_header": "X-Authenticated-User", "authenticated_roles_header": ""},
                {"authenticated_actor_header": "X-Authenticated-User", "authenticated_roles_header": "X-Authenticated-User"},
                {"authenticated_actor_header": "X-Actor-Id", "authenticated_roles_header": "X-Authenticated-Roles"},
            )
            for overrides in scenarios:
                with self.subTest(overrides=overrides):
                    with self.assertRaises(ValueError):
                        create_app(
                            ApiSettings(
                                db_path=db_path,
                                runtime_mode="shared_service",
                                auto_migrate=False,
                                host="127.0.0.1",
                                port=8000,
                                snapshot_signing_secret="test-shared-snapshot-secret",
                                **overrides,
                            )
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

    def test_cli_settings_default_shared_service_proxy_headers_on(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--runtime-mode", "shared_service"])

        with patch.dict("os.environ", {}, clear=True):
            settings = settings_from_cli_args(args)

        self.assertTrue(settings.proxy_headers)
        self.assertEqual("127.0.0.1", settings.forwarded_allow_ips)

    def test_cli_settings_can_disable_proxy_headers(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--runtime-mode", "shared_service", "--no-proxy-headers"])

        with patch.dict("os.environ", {}, clear=True):
            settings = settings_from_cli_args(args)

        self.assertFalse(settings.proxy_headers)

    def test_cli_settings_preserve_verified_header_names_from_env(self) -> None:
        parser = build_arg_parser()
        args = parser.parse_args(["--runtime-mode", "shared_service"])

        with patch.dict(
            "os.environ",
            {
                "MTG_API_AUTHENTICATED_ACTOR_HEADER": "X-Verified-User",
                "MTG_API_AUTHENTICATED_ROLES_HEADER": "X-Verified-Roles",
                "MTG_API_PROXY_HEADERS": "false",
                "MTG_API_FORWARDED_ALLOW_IPS": "10.0.0.1",
            },
            clear=True,
        ):
            settings = settings_from_cli_args(args)

        self.assertEqual("X-Verified-User", settings.authenticated_actor_header)
        self.assertEqual("X-Verified-Roles", settings.authenticated_roles_header)
        self.assertFalse(settings.proxy_headers)
        self.assertEqual("10.0.0.1", settings.forwarded_allow_ips)

    def test_main_passes_explicit_proxy_settings_to_uvicorn(self) -> None:
        with patch("mtg_source_stack.api.app.create_app", return_value=object()) as mock_create_app:
            with patch("uvicorn.run") as mock_run:
                main(
                    [
                        "--runtime-mode",
                        "shared_service",
                        "--proxy-headers",
                        "--forwarded-allow-ips",
                        "127.0.0.1",
                    ]
                )

        settings = mock_create_app.call_args.args[0]
        self.assertTrue(settings.proxy_headers)
        self.assertEqual("127.0.0.1", settings.forwarded_allow_ips)
        mock_run.assert_called_once_with(
            mock_create_app.return_value,
            host=settings.host,
            port=settings.port,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )
