"""Shared settings and request-context helpers for the web API."""

from __future__ import annotations
from dataclasses import dataclass
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..db.connection import DEFAULT_DB_PATH

if TYPE_CHECKING:  # pragma: no cover - typing-only import
    from fastapi import Request
else:  # pragma: no cover - optional runtime dependency for API-only paths
    try:
        from fastapi import Request
    except ModuleNotFoundError:  # keeps parser/help imports working without web deps
        Request = Any


@dataclass(frozen=True, slots=True)
class ApiSettings:
    db_path: Path
    auto_migrate: bool
    host: str
    port: int


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


def settings_from_env() -> ApiSettings:
    return ApiSettings(
        db_path=Path(os.getenv("MTG_API_DB", str(DEFAULT_DB_PATH))),
        auto_migrate=_env_bool("MTG_API_AUTO_MIGRATE", True),
        host=os.getenv("MTG_API_HOST", "127.0.0.1"),
        port=int(os.getenv("MTG_API_PORT", "8000")),
    )


async def get_settings(request: "Request") -> ApiSettings:
    return request.app.state.settings


async def get_request_context(request: "Request") -> RequestContext:
    request_id = getattr(request.state, "request_id", None) or str(uuid4())
    request.state.request_id = request_id
    return RequestContext(
        actor_type="api",
        actor_id=request.headers.get("X-Actor-Id"),
        request_id=request_id,
    )
