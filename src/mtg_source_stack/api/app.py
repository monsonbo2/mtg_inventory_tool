"""FastAPI application factory for the local-demo web backend.

This shell currently wraps the existing synchronous inventory service layer and
SQLite-backed runtime. It is suitable for local/demo HTTP work, but it should
not yet be described as a concurrency-hardened shared deployment surface.
"""

from __future__ import annotations

import argparse
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ..api_contract import api_error_payload, api_error_status
from ..db.migrator import migrate_database
from ..db.schema import require_current_schema
from ..errors import MtgStackError
from .dependencies import ApiSettings, settings_from_env

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from fastapi import FastAPI


logger = logging.getLogger(__name__)


def _spec_contains_ref(node: Any, target_ref: str) -> bool:
    if isinstance(node, dict):
        if node.get("$ref") == target_ref:
            return True
        return any(_spec_contains_ref(value, target_ref) for value in node.values())
    if isinstance(node, list):
        return any(_spec_contains_ref(value, target_ref) for value in node)
    return False


def _strip_generated_validation_responses(openapi_schema: dict[str, Any]) -> None:
    for path_item in openapi_schema.get("paths", {}).values():
        if not isinstance(path_item, dict):
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict):
                continue
            responses = operation.get("responses")
            if not isinstance(responses, dict):
                continue
            response_422 = responses.get("422")
            if not isinstance(response_422, dict):
                continue
            schema_ref = (
                response_422.get("content", {})
                .get("application/json", {})
                .get("schema", {})
                .get("$ref")
            )
            if response_422.get("description") == "Validation Error" or schema_ref == "#/components/schemas/HTTPValidationError":
                responses.pop("422", None)

    schemas = openapi_schema.get("components", {}).get("schemas", {})
    if not isinstance(schemas, dict):
        return
    for schema_name in ("HTTPValidationError", "ValidationError"):
        ref = f"#/components/schemas/{schema_name}"
        if schema_name in schemas and not _spec_contains_ref(openapi_schema.get("paths", {}), ref):
            schemas.pop(schema_name, None)


def build_arg_parser() -> argparse.ArgumentParser:
    defaults = settings_from_env()
    parser = argparse.ArgumentParser(
        description="Run the MTG Inventory Tool local-demo web API."
    )
    parser.add_argument("--db", default=str(defaults.db_path), help="SQLite database path.")
    parser.add_argument("--host", default=defaults.host, help="Host interface to bind.")
    parser.add_argument("--port", default=defaults.port, type=int, help="TCP port to listen on.")
    parser.add_argument(
        "--no-auto-migrate",
        action="store_true",
        help="Require a current schema at startup instead of applying pending migrations.",
    )
    return parser


@asynccontextmanager
async def lifespan(app):
    settings: ApiSettings = app.state.settings
    logger.info(
        "Starting local-demo API with db_path=%s auto_migrate=%s trust_actor_headers=%s",
        settings.db_path,
        settings.auto_migrate,
        settings.trust_actor_headers,
    )
    if settings.auto_migrate:
        logger.info("Applying pending migrations at startup")
        migrate_database(settings.db_path)
    else:
        logger.info("Requiring current schema at startup without migration")
        require_current_schema(settings.db_path)
    yield


def create_app(settings: ApiSettings | None = None):
    from fastapi import FastAPI, Request
    from fastapi.exceptions import RequestValidationError
    from fastapi.openapi.utils import get_openapi
    from fastapi.responses import JSONResponse

    from .routes import router

    effective_settings = settings or settings_from_env()
    app = FastAPI(
        title="MTG Inventory Tool API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = effective_settings

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(MtgStackError)
    async def handle_domain_error(request: Request, exc: MtgStackError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-Id": request_id} if request_id else None
        return JSONResponse(
            status_code=api_error_status(exc),
            content=api_error_payload(exc),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-Id": request_id} if request_id else None
        details = exc.errors()
        if details:
            first_error = details[0]
            location = " -> ".join(str(part) for part in first_error.get("loc", ()))
            message = first_error.get("msg", "Invalid request.")
            if location:
                message = f"{location}: {message}"
        else:
            message = "Invalid request."
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "validation_error", "message": message}},
            headers=headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        headers = {"X-Request-Id": request_id} if request_id else None
        logger.exception(
            "Unhandled API error request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        return JSONResponse(
            status_code=api_error_status(exc),
            content=api_error_payload(exc),
            headers=headers,
        )

    app.include_router(router)

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        openapi_schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        _strip_generated_validation_responses(openapi_schema)
        app.openapi_schema = openapi_schema
        return openapi_schema

    app.openapi = custom_openapi
    return app


def main(argv: list[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    defaults = settings_from_env()
    settings = ApiSettings(
        db_path=Path(args.db),
        auto_migrate=not args.no_auto_migrate,
        host=args.host,
        port=int(args.port),
        trust_actor_headers=defaults.trust_actor_headers,
    )

    try:
        import uvicorn
        app = create_app(settings)
    except ModuleNotFoundError as exc:  # pragma: no cover - environment-dependent operator path
        raise SystemExit(
            "FastAPI web dependencies are not installed. Run `pip install -e .[web]` first."
        ) from exc

    uvicorn.run(app, host=settings.host, port=settings.port)
