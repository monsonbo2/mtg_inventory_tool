"""Shared settings and request-context helpers for the web API."""

from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from ..db.connection import DEFAULT_DB_PATH
from ..errors import AuthenticationError

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    from fastapi import Request
else:  # pragma: no cover - optional runtime dependency for API-only paths
    try:
        from fastapi import Request
    except ModuleNotFoundError:  # keeps parser/help imports working without web deps
        Request = Any


RuntimeMode = Literal["local_demo", "shared_service"]
DEFAULT_RUNTIME_MODE: RuntimeMode = "local_demo"
DEFAULT_AUTHENTICATED_ACTOR_HEADER = "X-Authenticated-User"


@dataclass(frozen=True, slots=True)
class ApiSettings:
    db_path: Path
    runtime_mode: RuntimeMode
    auto_migrate: bool
    host: str
    port: int
    trust_actor_headers: bool = False
    authenticated_actor_header: str = DEFAULT_AUTHENTICATED_ACTOR_HEADER


@dataclass(frozen=True, slots=True)
class RequestContext:
    actor_type: str
    actor_id: str | None
    request_id: str


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _env_optional_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def auto_migrate_override_from_env() -> bool | None:
    return _env_optional_bool("MTG_API_AUTO_MIGRATE")


def resolve_runtime_mode(raw: str | None) -> RuntimeMode:
    if raw is None:
        return DEFAULT_RUNTIME_MODE
    normalized = raw.strip().lower()
    if normalized not in {"local_demo", "shared_service"}:
        raise ValueError("runtime_mode must be one of: local_demo, shared_service.")
    return normalized


def default_auto_migrate_for_mode(runtime_mode: RuntimeMode) -> bool:
    if runtime_mode == "shared_service":
        return False
    return True


def resolve_auto_migrate(
    *,
    runtime_mode: RuntimeMode,
    env_override: bool | None,
    cli_override: bool | None,
) -> bool:
    if env_override is not None:
        return env_override
    if cli_override is not None:
        return cli_override
    return default_auto_migrate_for_mode(runtime_mode)


def settings_from_env() -> ApiSettings:
    runtime_mode = resolve_runtime_mode(os.getenv("MTG_API_RUNTIME_MODE"))
    return ApiSettings(
        db_path=Path(os.getenv("MTG_API_DB", str(DEFAULT_DB_PATH))),
        runtime_mode=runtime_mode,
        auto_migrate=resolve_auto_migrate(
            runtime_mode=runtime_mode,
            env_override=_env_optional_bool("MTG_API_AUTO_MIGRATE"),
            cli_override=None,
        ),
        host=os.getenv("MTG_API_HOST", "127.0.0.1"),
        port=int(os.getenv("MTG_API_PORT", "8000")),
        trust_actor_headers=_env_bool("MTG_API_TRUST_ACTOR_HEADERS", False),
        authenticated_actor_header=(
            os.getenv("MTG_API_AUTHENTICATED_ACTOR_HEADER", DEFAULT_AUTHENTICATED_ACTOR_HEADER).strip()
            or DEFAULT_AUTHENTICATED_ACTOR_HEADER
        ),
    )


def get_settings(request: "Request") -> ApiSettings:
    return request.app.state.settings


def _resolve_local_demo_actor_id(request: "Request", settings: ApiSettings) -> str:
    if not settings.trust_actor_headers:
        return "local-demo"
    actor_id = request.headers.get("X-Actor-Id", "").strip()
    return actor_id or "local-demo"


def _resolve_shared_service_actor_id(request: "Request", settings: ApiSettings) -> str | None:
    actor_id = request.headers.get(settings.authenticated_actor_header, "").strip()
    return actor_id or None


def _build_request_context(request: "Request", *, require_authenticated_actor: bool) -> RequestContext:
    settings = request.app.state.settings
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    request.state.request_id = request_id

    if settings.runtime_mode == "shared_service":
        actor_id = _resolve_shared_service_actor_id(request, settings)
        if require_authenticated_actor and not actor_id:
            raise AuthenticationError(
                f"Authenticated user header '{settings.authenticated_actor_header}' is required for shared_service writes."
            )
    else:
        actor_id = _resolve_local_demo_actor_id(request, settings)

    return RequestContext(
        actor_type="api",
        actor_id=actor_id,
        request_id=request_id,
    )


def get_request_context(request: "Request") -> RequestContext:
    return _build_request_context(request, require_authenticated_actor=False)


def get_mutating_request_context(request: "Request") -> RequestContext:
    return _build_request_context(request, require_authenticated_actor=True)
