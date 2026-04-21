"""Regression coverage for the shared-service proxy validation harness."""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import sys
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen

from tests.common import REPO_ROOT


HARNESS_PATH = REPO_ROOT / "scripts" / "shared_service_proxy_harness.py"
SPEC = importlib.util.spec_from_file_location("shared_service_proxy_harness", HARNESS_PATH)
assert SPEC is not None
shared_service_proxy_harness = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = shared_service_proxy_harness
SPEC.loader.exec_module(shared_service_proxy_harness)


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
def _running_server(server: ThreadingHTTPServer):
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}", server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class RecordingBackendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server method naming
        self.server.records.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "headers": dict(self.headers.items()),
            }
        )
        payload = {
            "path": self.path,
            "user": self.headers.get("X-Authenticated-User"),
            "roles": self.headers.get("X-Authenticated-Roles"),
            "actor_id": self.headers.get("X-Actor-Id"),
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        return


class SharedServiceProxyHarnessTest(unittest.TestCase):
    def test_rewrite_api_url_strips_api_prefix_and_preserves_query(self) -> None:
        url = shared_service_proxy_harness.rewrite_api_url(
            "http://127.0.0.1:8000/",
            "/api/inventories?limit=10",
        )

        self.assertEqual("http://127.0.0.1:8000/inventories?limit=10", url)

    def test_build_forward_headers_strips_spoofed_auth_and_injects_fixture_identity(self) -> None:
        config = shared_service_proxy_harness.ProxyHarnessConfig(
            backend_url="http://127.0.0.1:8000",
            frontend_dist=Path("frontend/dist"),
            actor="viewer@example.com",
            roles=None,
        )

        headers = shared_service_proxy_harness.build_forward_headers(
            [
                ("X-Authenticated-User", "admin@example.com"),
                ("X-Authenticated-Roles", "admin"),
                ("X-Actor-Id", "local-demo"),
                ("Accept", "application/json"),
                ("Connection", "keep-alive"),
                ("Host", "app.example.test"),
            ],
            config=config,
            client_host="127.0.0.1",
            original_host="app.example.test",
        )

        self.assertEqual("viewer@example.com", headers["X-Authenticated-User"])
        self.assertNotIn("X-Authenticated-Roles", headers)
        self.assertNotIn("X-Actor-Id", headers)
        self.assertEqual("application/json", headers["Accept"])
        self.assertNotIn("Connection", headers)
        self.assertEqual("127.0.0.1", headers["X-Forwarded-For"])
        self.assertEqual("app.example.test", headers["X-Forwarded-Host"])

    def test_parse_content_length_rejects_negative_values(self) -> None:
        with self.assertRaisesRegex(
            shared_service_proxy_harness.HarnessError,
            "Invalid Content-Length header",
        ):
            shared_service_proxy_harness.parse_content_length("-1")

    def test_parse_content_length_accepts_zero_and_missing_values(self) -> None:
        self.assertEqual(0, shared_service_proxy_harness.parse_content_length(None))
        self.assertEqual(0, shared_service_proxy_harness.parse_content_length(""))
        self.assertEqual(0, shared_service_proxy_harness.parse_content_length("0"))

    @unittest.skipUnless(
        LOCALHOST_SERVER_TESTING_AVAILABLE,
        "localhost socket access is unavailable; live proxy harness test is skipped.",
    )
    def test_proxy_rewrites_api_requests_and_neutralizes_spoofed_admin_headers(self) -> None:
        backend_server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingBackendHandler)
        backend_server.records = []  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as tmp_dir:
            frontend_dist = Path(tmp_dir)
            (frontend_dist / "index.html").write_text("<html>demo</html>", encoding="utf-8")
            with _running_server(backend_server) as (backend_url, _backend):
                config = shared_service_proxy_harness.ProxyHarnessConfig(
                    backend_url=backend_url,
                    frontend_dist=frontend_dist,
                    actor="viewer@example.com",
                    roles=None,
                )
                proxy_server = shared_service_proxy_harness.build_server(config, port=0)
                with _running_server(proxy_server) as (proxy_url, _proxy):
                    request = Request(
                        f"{proxy_url}/api/inventories?limit=1",
                        headers={
                            "X-Authenticated-User": "admin@example.com",
                            "X-Authenticated-Roles": "admin",
                            "X-Actor-Id": "local-demo",
                        },
                    )
                    with urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual("/inventories?limit=1", payload["path"])
        self.assertEqual("viewer@example.com", payload["user"])
        self.assertIsNone(payload["roles"])
        self.assertIsNone(payload["actor_id"])
        self.assertEqual("/inventories?limit=1", backend_server.records[0]["path"])  # type: ignore[index, attr-defined]

    @unittest.skipUnless(
        LOCALHOST_SERVER_TESTING_AVAILABLE,
        "localhost socket access is unavailable; live proxy harness test is skipped.",
    )
    def test_proxy_returns_400_for_negative_content_length(self) -> None:
        backend_server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingBackendHandler)
        backend_server.records = []  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as tmp_dir:
            frontend_dist = Path(tmp_dir)
            (frontend_dist / "index.html").write_text("<html>demo</html>", encoding="utf-8")
            with _running_server(backend_server) as (backend_url, _backend):
                config = shared_service_proxy_harness.ProxyHarnessConfig(
                    backend_url=backend_url,
                    frontend_dist=frontend_dist,
                    actor="viewer@example.com",
                    roles=None,
                )
                proxy_server = shared_service_proxy_harness.build_server(config, port=0)
                with _running_server(proxy_server) as (_proxy_url, proxy):
                    host, port = proxy.server_address
                    with socket.create_connection((host, port), timeout=5) as sock:
                        sock.sendall(
                            b"POST /api/inventories HTTP/1.1\r\n"
                            + f"Host: {host}:{port}\r\n".encode("ascii")
                            + b"Content-Length: -1\r\n"
                            + b"\r\n"
                        )
                        response = sock.recv(1024)

        self.assertIn(b"400 Proxy Harness Error", response)
        self.assertEqual([], backend_server.records)  # type: ignore[attr-defined]

    @unittest.skipUnless(
        LOCALHOST_SERVER_TESTING_AVAILABLE,
        "localhost socket access is unavailable; live proxy harness test is skipped.",
    )
    def test_proxy_without_identity_strips_client_supplied_auth_headers(self) -> None:
        backend_server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingBackendHandler)
        backend_server.records = []  # type: ignore[attr-defined]
        with tempfile.TemporaryDirectory() as tmp_dir:
            frontend_dist = Path(tmp_dir)
            (frontend_dist / "index.html").write_text("<html>demo</html>", encoding="utf-8")
            with _running_server(backend_server) as (backend_url, _backend):
                config = shared_service_proxy_harness.ProxyHarnessConfig(
                    backend_url=backend_url,
                    frontend_dist=frontend_dist,
                    actor=None,
                    roles=None,
                )
                proxy_server = shared_service_proxy_harness.build_server(config, port=0)
                with _running_server(proxy_server) as (proxy_url, _proxy):
                    request = Request(
                        f"{proxy_url}/api/inventories",
                        headers={
                            "X-Authenticated-User": "admin@example.com",
                            "X-Authenticated-Roles": "admin",
                        },
                    )
                    with urlopen(request, timeout=5) as response:
                        payload = json.loads(response.read().decode("utf-8"))

        self.assertIsNone(payload["user"])
        self.assertIsNone(payload["roles"])
        self.assertIsNone(payload["actor_id"])

    @unittest.skipUnless(
        LOCALHOST_SERVER_TESTING_AVAILABLE,
        "localhost socket access is unavailable; live proxy harness test is skipped.",
    )
    def test_proxy_serves_frontend_index_and_spa_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            frontend_dist = Path(tmp_dir)
            (frontend_dist / "index.html").write_text("<html>demo app</html>", encoding="utf-8")
            config = shared_service_proxy_harness.ProxyHarnessConfig(
                backend_url="http://127.0.0.1:9",
                frontend_dist=frontend_dist,
                actor=None,
                roles=None,
            )
            proxy_server = shared_service_proxy_harness.build_server(config, port=0)
            with _running_server(proxy_server) as (proxy_url, _proxy):
                with urlopen(f"{proxy_url}/", timeout=5) as index_response:
                    index_body = index_response.read().decode("utf-8")
                with urlopen(f"{proxy_url}/collections/personal", timeout=5) as route_response:
                    route_body = route_response.read().decode("utf-8")

        self.assertEqual("<html>demo app</html>", index_body)
        self.assertEqual("<html>demo app</html>", route_body)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
