#!/usr/bin/env python3
"""Smoke-test the local shared-service proxy harness."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from typing import Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from shared_service_proxy_harness import (
    DEFAULT_BACKEND_URL,
    DEFAULT_FRONTEND_DIST,
    DEFAULT_PROXY_HOST,
    ACTOR_ID_HEADER,
    AUTHENTICATED_ROLES_HEADER,
    AUTHENTICATED_USER_HEADER,
    ProxyHarnessConfig,
    build_server,
    resolve_fixture_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = REPO_ROOT / "var" / "db" / "frontend_demo.db"
DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_STARTUP_TIMEOUT = 15.0
DEFAULT_REQUEST_TIMEOUT = 10.0


class SmokeFailure(AssertionError):
    """Raised when the proxy smoke workflow observes unexpected behavior."""


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    body: bytes
    headers: dict[str, str]

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        return self.body.decode("utf-8")


def _free_port(host: str = DEFAULT_BACKEND_HOST) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    expected_status: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> HttpResult:
    request = Request(url, headers=headers or {})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = HttpResult(
                status=response.status,
                body=response.read(),
                headers=dict(response.headers.items()),
            )
    except HTTPError as exc:
        result = HttpResult(
            status=exc.code,
            body=exc.read(),
            headers=dict(exc.headers.items()),
        )
    except URLError as exc:
        raise SmokeFailure(f"Request failed for {url}: {exc.reason}") from exc

    if expected_status is not None and result.status != expected_status:
        body = result.text()[:500]
        raise SmokeFailure(f"Expected {expected_status} from {url}, got {result.status}: {body}")
    return result


def _wait_for_backend(base_url: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = _request(f"{base_url}/health", expected_status=200, timeout=2.0)
            if health.json().get("status") == "ok":
                return
        except Exception as exc:  # pragma: no cover - exercised by timeout path
            last_error = exc
        time.sleep(0.1)
    detail = f" Last error: {last_error}" if last_error else ""
    raise SmokeFailure(f"Timed out waiting for backend at {base_url}.{detail}")


@contextmanager
def _started_backend(args: argparse.Namespace) -> Iterator[str]:
    if not args.start_backend:
        yield args.backend_url.rstrip("/")
        return

    backend_port = args.backend_port or _free_port()
    backend_url = f"http://{DEFAULT_BACKEND_HOST}:{backend_port}"
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    src_path = str(REPO_ROOT / "src")
    env["PYTHONPATH"] = f"{src_path}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else src_path
    env.setdefault("MTG_API_SNAPSHOT_SIGNING_SECRET", "local-shared-service-smoke-secret")
    command = [
        sys.executable,
        "-c",
        "from mtg_source_stack.api.app import main; import sys; main(sys.argv[1:])",
        "--db",
        str(args.db),
        "--runtime-mode",
        "shared_service",
        "--host",
        DEFAULT_BACKEND_HOST,
        "--port",
        str(backend_port),
        "--forwarded-allow-ips",
        DEFAULT_BACKEND_HOST,
    ]
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_backend(backend_url, timeout_seconds=args.backend_startup_timeout)
        yield backend_url
    except Exception:
        if process.poll() is not None:
            output, _ = process.communicate(timeout=2)
            if output:
                print(output, file=sys.stderr)
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def _proxy_for_preset(
    preset: str,
    *,
    backend_url: str,
    frontend_dist: Path,
    proxy_host: str,
    proxy_port: int,
    timeout_seconds: float,
) -> Iterator[str]:
    identity = resolve_fixture_identity(preset)
    config = ProxyHarnessConfig(
        backend_url=backend_url,
        frontend_dist=frontend_dist,
        actor=identity.actor,
        roles=identity.roles,
        timeout_seconds=timeout_seconds,
    )
    server = build_server(config, host=proxy_host, port=proxy_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _proxy_request(
    base_url: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    expected_status: int | None = None,
    timeout: float = DEFAULT_REQUEST_TIMEOUT,
) -> HttpResult:
    return _request(
        f"{base_url}{path}",
        headers=headers,
        expected_status=expected_status,
        timeout=timeout,
    )


def _inventory_slugs(base_url: str, *, expected_status: int = 200) -> list[str]:
    response = _proxy_request(base_url, "/api/inventories", expected_status=expected_status)
    if expected_status != 200:
        return []
    return [row["slug"] for row in response.json()]


def _search_path(query: str) -> str:
    return f"/api/cards/search?{urlencode({'query': query})}"


def run_smoke(args: argparse.Namespace) -> None:
    frontend_dist = args.frontend_dist
    if not args.skip_static and not (frontend_dist / "index.html").is_file():
        raise SmokeFailure(
            f"Missing frontend build at {frontend_dist}. Run `npm run build` in frontend/ or pass --skip-static."
        )

    with _started_backend(args) as backend_url:
        print(f"Backend target: {backend_url}")

        with _proxy_for_preset(
            "none",
            backend_url=backend_url,
            frontend_dist=frontend_dist,
            proxy_host=args.proxy_host,
            proxy_port=args.proxy_port,
            timeout_seconds=args.timeout,
        ) as proxy_url:
            health = _proxy_request(proxy_url, "/api/health", expected_status=200)
            if health.json().get("status") != "ok":
                raise SmokeFailure("/api/health did not return status=ok through the proxy.")
            print("PASS /api path rewriting via /api/health")

            spoofed_headers = {
                AUTHENTICATED_USER_HEADER: "admin@example.com",
                AUTHENTICATED_ROLES_HEADER: "admin",
                ACTOR_ID_HEADER: "local-demo",
            }
            _proxy_request(
                proxy_url,
                "/api/inventories",
                headers=spoofed_headers,
                expected_status=401,
            )
            print("PASS spoofed auth headers are stripped when no identity is injected")

            if not args.skip_static:
                index = _proxy_request(proxy_url, "/", expected_status=200)
                if "<html" not in index.text().lower():
                    raise SmokeFailure("Frontend index did not look like HTML.")
                print("PASS frontend assets are served from the same origin")

        with _proxy_for_preset(
            "viewer",
            backend_url=backend_url,
            frontend_dist=frontend_dist,
            proxy_host=args.proxy_host,
            proxy_port=args.proxy_port,
            timeout_seconds=args.timeout,
        ) as proxy_url:
            viewer_slugs = _inventory_slugs(proxy_url)
            if viewer_slugs != ["personal"]:
                raise SmokeFailure(f"Expected viewer to see ['personal'], got {viewer_slugs!r}.")
            print("PASS viewer fixture sees only personal")

            spoofed_admin_response = _proxy_request(
                proxy_url,
                "/api/inventories",
                headers={
                    AUTHENTICATED_USER_HEADER: "admin@example.com",
                    AUTHENTICATED_ROLES_HEADER: "admin",
                    ACTOR_ID_HEADER: "local-demo",
                },
                expected_status=200,
            )
            spoofed_admin_slugs = [row["slug"] for row in spoofed_admin_response.json()]
            if spoofed_admin_slugs != ["personal"]:
                raise SmokeFailure(
                    "Spoofed client admin headers were not neutralized; "
                    f"viewer proxy saw {spoofed_admin_slugs!r}."
                )
            print("PASS spoofed client admin headers do not override proxy identity")

            _proxy_request(proxy_url, _search_path("Lightning"), expected_status=200)
            print("PASS readable fixture can use catalog search")

        with _proxy_for_preset(
            "writer",
            backend_url=backend_url,
            frontend_dist=frontend_dist,
            proxy_host=args.proxy_host,
            proxy_port=args.proxy_port,
            timeout_seconds=args.timeout,
        ) as proxy_url:
            writer_slugs = _inventory_slugs(proxy_url)
            if writer_slugs != ["trade-binder"]:
                raise SmokeFailure(f"Expected writer to see ['trade-binder'], got {writer_slugs!r}.")
            print("PASS writer fixture sees only trade-binder")

        with _proxy_for_preset(
            "no-access",
            backend_url=backend_url,
            frontend_dist=frontend_dist,
            proxy_host=args.proxy_host,
            proxy_port=args.proxy_port,
            timeout_seconds=args.timeout,
        ) as proxy_url:
            no_access_slugs = _inventory_slugs(proxy_url)
            if no_access_slugs != []:
                raise SmokeFailure(f"Expected no-access fixture to see no inventories, got {no_access_slugs!r}.")
            _proxy_request(proxy_url, _search_path("Lightning"), expected_status=403)
            print("PASS no-access fixture is denied catalog search")

        with _proxy_for_preset(
            "admin",
            backend_url=backend_url,
            frontend_dist=frontend_dist,
            proxy_host=args.proxy_host,
            proxy_port=args.proxy_port,
            timeout_seconds=args.timeout,
        ) as proxy_url:
            admin_slugs = set(_inventory_slugs(proxy_url))
            expected_admin_slugs = {"bootstrapped-collection", "personal", "trade-binder"}
            if admin_slugs != expected_admin_slugs:
                raise SmokeFailure(
                    f"Expected admin to see {sorted(expected_admin_slugs)!r}, got {sorted(admin_slugs)!r}."
                )
            print("PASS admin fixture sees all shared-service demo inventories")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test the shared-service proxy harness.")
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument(
        "--start-backend",
        action="store_true",
        help="Launch mtg-web-api in shared_service mode for the duration of the smoke run.",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--backend-port", type=int, default=0)
    parser.add_argument("--backend-startup-timeout", type=float, default=DEFAULT_BACKEND_STARTUP_TIMEOUT)
    parser.add_argument("--frontend-dist", type=Path, default=DEFAULT_FRONTEND_DIST)
    parser.add_argument("--proxy-host", default=DEFAULT_PROXY_HOST)
    parser.add_argument("--proxy-port", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT)
    parser.add_argument(
        "--skip-static",
        action="store_true",
        help="Skip the frontend index check and validate only the proxied API surface.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        run_smoke(args)
    except SmokeFailure as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    print("Shared-service proxy smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
