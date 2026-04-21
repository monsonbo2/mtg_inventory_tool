#!/usr/bin/env python3
"""Local reverse-proxy harness for shared-service rollout validation.

This is a development and smoke-test tool. It intentionally models the
shared-service proxy contract, but it is not production infrastructure.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
DEFAULT_FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
DEFAULT_PROXY_HOST = "127.0.0.1"
DEFAULT_PROXY_PORT = 5174
AUTHENTICATED_USER_HEADER = "X-Authenticated-User"
AUTHENTICATED_ROLES_HEADER = "X-Authenticated-Roles"
ACTOR_ID_HEADER = "X-Actor-Id"
STRIPPED_AUTH_HEADERS = frozenset(
    {
        AUTHENTICATED_USER_HEADER.casefold(),
        AUTHENTICATED_ROLES_HEADER.casefold(),
        ACTOR_ID_HEADER.casefold(),
    }
)
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


@dataclass(frozen=True, slots=True)
class FixtureIdentity:
    actor: str | None
    roles: str | None = None


FIXTURE_PRESETS: dict[str, FixtureIdentity] = {
    "none": FixtureIdentity(actor=None, roles=None),
    "new-user": FixtureIdentity(actor="new-user@example.com", roles=None),
    "bootstrapped": FixtureIdentity(actor="bootstrapped@example.com", roles=None),
    "viewer": FixtureIdentity(actor="viewer@example.com", roles=None),
    "writer": FixtureIdentity(actor="writer@example.com", roles=None),
    "no-access": FixtureIdentity(actor="no-access@example.com", roles=None),
    "admin": FixtureIdentity(actor="admin@example.com", roles="admin"),
}


@dataclass(frozen=True, slots=True)
class ProxyHarnessConfig:
    backend_url: str
    frontend_dist: Path
    actor: str | None
    roles: str | None = None
    timeout_seconds: float = 10.0


class HarnessError(ValueError):
    """Raised when proxy harness configuration is invalid."""


class _ReusableThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def normalize_backend_url(raw_backend_url: str) -> str:
    normalized = raw_backend_url.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HarnessError(f"Backend URL must be absolute HTTP(S), got: {raw_backend_url!r}")
    return normalized


def resolve_fixture_identity(
    preset: str,
    *,
    actor: str | None = None,
    roles: str | None = None,
) -> FixtureIdentity:
    try:
        preset_identity = FIXTURE_PRESETS[preset]
    except KeyError as exc:
        choices = ", ".join(sorted(FIXTURE_PRESETS))
        raise HarnessError(f"Unknown fixture preset {preset!r}. Choose one of: {choices}.") from exc
    return FixtureIdentity(
        actor=actor if actor is not None else preset_identity.actor,
        roles=roles if roles is not None else preset_identity.roles,
    )


def rewrite_api_url(backend_url: str, request_target: str) -> str:
    parsed_target = urlsplit(request_target)
    if parsed_target.path == "/api":
        upstream_path = "/"
    elif parsed_target.path.startswith("/api/"):
        upstream_path = parsed_target.path.removeprefix("/api")
    else:
        raise HarnessError(f"Request target is not under /api: {request_target!r}")

    parsed_backend = urlsplit(normalize_backend_url(backend_url))
    return urlunsplit(
        (
            parsed_backend.scheme,
            parsed_backend.netloc,
            upstream_path or "/",
            parsed_target.query,
            "",
        )
    )


def build_forward_headers(
    incoming_headers: Iterable[tuple[str, str]],
    *,
    config: ProxyHarnessConfig,
    client_host: str,
    original_host: str | None,
) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for header_name, header_value in incoming_headers:
        normalized_name = header_name.casefold()
        if normalized_name in HOP_BY_HOP_HEADERS:
            continue
        if normalized_name in STRIPPED_AUTH_HEADERS:
            continue
        if normalized_name in {"host", "content-length"}:
            continue
        forwarded[header_name] = header_value

    if config.actor:
        forwarded[AUTHENTICATED_USER_HEADER] = config.actor
    if config.roles:
        forwarded[AUTHENTICATED_ROLES_HEADER] = config.roles

    forwarded["X-Forwarded-For"] = client_host
    forwarded["X-Forwarded-Proto"] = "http"
    if original_host:
        forwarded["X-Forwarded-Host"] = original_host
    return forwarded


def parse_content_length(raw_content_length: str | None) -> int:
    if raw_content_length in {None, ""}:
        return 0
    try:
        content_length = int(raw_content_length)
    except ValueError as exc:
        raise HarnessError("Invalid Content-Length header.") from exc
    if content_length < 0:
        raise HarnessError("Invalid Content-Length header.")
    return content_length


def _json_error(message: str) -> bytes:
    return json.dumps(
        {"error": {"code": "proxy_harness_error", "message": message}},
        separators=(",", ":"),
    ).encode("utf-8")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_static_path(frontend_dist: Path, request_target: str) -> Path | None:
    root = frontend_dist.resolve()
    parsed_target = urlsplit(request_target)
    raw_path = unquote(parsed_target.path).lstrip("/")
    if raw_path in {"", "."}:
        return root / "index.html"

    candidate = (root / raw_path).resolve()
    if not _is_relative_to(candidate, root):
        return None
    if candidate.is_dir():
        return candidate / "index.html"
    if candidate.is_file():
        return candidate
    if "." not in Path(raw_path).name:
        return root / "index.html"
    return None


def make_proxy_handler(config: ProxyHarnessConfig) -> type[BaseHTTPRequestHandler]:
    normalized_config = ProxyHarnessConfig(
        backend_url=normalize_backend_url(config.backend_url),
        frontend_dist=config.frontend_dist,
        actor=config.actor,
        roles=config.roles,
        timeout_seconds=config.timeout_seconds,
    )

    class SharedServiceProxyHandler(BaseHTTPRequestHandler):
        server_version = "MtgSharedServiceProxyHarness/0.1"

        def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
            return

        def do_DELETE(self) -> None:  # noqa: N802 - http.server method naming
            self._handle_request()

        def do_GET(self) -> None:  # noqa: N802 - http.server method naming
            self._handle_request()

        def do_HEAD(self) -> None:  # noqa: N802 - http.server method naming
            self._handle_request(head_only=True)

        def do_OPTIONS(self) -> None:  # noqa: N802 - http.server method naming
            self._handle_request()

        def do_PATCH(self) -> None:  # noqa: N802 - http.server method naming
            self._handle_request()

        def do_POST(self) -> None:  # noqa: N802 - http.server method naming
            self._handle_request()

        def do_PUT(self) -> None:  # noqa: N802 - http.server method naming
            self._handle_request()

        def _handle_request(self, *, head_only: bool = False) -> None:
            parsed_target = urlsplit(self.path)
            if parsed_target.path == "/api" or parsed_target.path.startswith("/api/"):
                self._proxy_api_request(head_only=head_only)
                return
            self._serve_static(head_only=head_only)

        def _read_request_body(self) -> tuple[bytes | None, bool]:
            try:
                length = parse_content_length(self.headers.get("Content-Length"))
            except HarnessError as exc:
                self._send_error_json(400, str(exc))
                return None, False
            if length == 0:
                return None, True
            return self.rfile.read(length), True

        def _proxy_api_request(self, *, head_only: bool = False) -> None:
            body, body_ok = self._read_request_body()
            if not body_ok:
                return
            upstream_url = rewrite_api_url(normalized_config.backend_url, self.path)
            headers = build_forward_headers(
                self.headers.items(),
                config=normalized_config,
                client_host=self.client_address[0],
                original_host=self.headers.get("Host"),
            )
            request = Request(
                upstream_url,
                data=body,
                headers=headers,
                method=self.command,
            )
            try:
                with urlopen(request, timeout=normalized_config.timeout_seconds) as response:
                    response_body = response.read()
                    self._send_response(
                        response.status,
                        response.reason,
                        response.headers.items(),
                        b"" if head_only else response_body,
                    )
            except HTTPError as exc:
                response_body = exc.read()
                self._send_response(
                    exc.code,
                    exc.reason,
                    exc.headers.items(),
                    b"" if head_only else response_body,
                )
            except URLError as exc:
                self._send_error_json(502, f"Backend request failed: {exc.reason}")

        def _serve_static(self, *, head_only: bool = False) -> None:
            if self.command not in {"GET", "HEAD"}:
                self._send_error_json(405, "Static frontend assets only support GET and HEAD.")
                return
            index_path = normalized_config.frontend_dist / "index.html"
            if not index_path.is_file():
                self._send_error_json(
                    503,
                    "Frontend build output is missing. Run `npm run build` in frontend/ first.",
                )
                return
            static_path = _resolve_static_path(normalized_config.frontend_dist, self.path)
            if static_path is None:
                self._send_error_json(403, "Requested static path is outside the frontend build directory.")
                return
            if not static_path.is_file():
                self._send_error_json(404, "Static asset not found.")
                return
            content_type = mimetypes.guess_type(static_path.name)[0] or "application/octet-stream"
            body = b"" if head_only else static_path.read_bytes()
            self._send_response(
                200,
                "OK",
                [("Content-Type", content_type)],
                body,
            )

        def _send_error_json(self, status_code: int, message: str) -> None:
            self._send_response(
                status_code,
                "Proxy Harness Error",
                [("Content-Type", "application/json")],
                _json_error(message),
            )

        def _send_response(
            self,
            status_code: int,
            reason: str,
            response_headers: Iterable[tuple[str, str]],
            body: bytes,
        ) -> None:
            self.send_response(status_code, reason)
            for header_name, header_value in response_headers:
                normalized_name = header_name.casefold()
                if normalized_name in HOP_BY_HOP_HEADERS or normalized_name == "content-length":
                    continue
                self.send_header(header_name, header_value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body:
                self.wfile.write(body)

    return SharedServiceProxyHandler


def build_server(
    config: ProxyHarnessConfig,
    *,
    host: str = DEFAULT_PROXY_HOST,
    port: int = DEFAULT_PROXY_PORT,
) -> ThreadingHTTPServer:
    return _ReusableThreadingHTTPServer((host, port), make_proxy_handler(config))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the local shared-service reverse-proxy validation harness."
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--frontend-dist", type=Path, default=DEFAULT_FRONTEND_DIST)
    parser.add_argument("--host", default=DEFAULT_PROXY_HOST)
    parser.add_argument("--port", default=DEFAULT_PROXY_PORT, type=int)
    parser.add_argument(
        "--fixture-preset",
        choices=sorted(FIXTURE_PRESETS),
        default="viewer",
        help="Fixture identity to inject into proxied API requests.",
    )
    parser.add_argument("--actor", default=None, help="Override the injected authenticated actor.")
    parser.add_argument(
        "--roles",
        default=None,
        help="Override the injected authenticated roles. Use an empty string to omit the header.",
    )
    parser.add_argument("--timeout", default=10.0, type=float, help="Backend request timeout in seconds.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    identity = resolve_fixture_identity(
        args.fixture_preset,
        actor=args.actor,
        roles=args.roles,
    )
    config = ProxyHarnessConfig(
        backend_url=args.backend_url,
        frontend_dist=args.frontend_dist,
        actor=identity.actor,
        roles=identity.roles or None,
        timeout_seconds=args.timeout,
    )
    try:
        server = build_server(config, host=args.host, port=args.port)
    except OSError as exc:
        parser.error(str(exc))

    host, port = server.server_address
    print(
        "Shared-service proxy harness listening at "
        f"http://{host}:{port} -> {normalize_backend_url(args.backend_url)}"
    )
    if identity.actor:
        role_summary = identity.roles or "<omitted>"
        print(f"Injecting {AUTHENTICATED_USER_HEADER}: {identity.actor}")
        print(f"Injecting {AUTHENTICATED_ROLES_HEADER}: {role_summary}")
    else:
        print("No authenticated user header will be injected.")
    print(f"Serving frontend build from {args.frontend_dist}")
    print("This harness is for local validation only; do not use it for real users.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping shared-service proxy harness.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
