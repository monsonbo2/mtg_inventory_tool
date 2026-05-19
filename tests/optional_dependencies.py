"""Helpers for tests that depend on optional dependency groups."""

from __future__ import annotations

import importlib.util


WEB_TEST_DEPENDENCIES = ("fastapi", "httpx", "pydantic", "uvicorn", "multipart")
WEB_TEST_SKIP_REASON = (
    "optional web/API test dependencies are not installed for the selected Python "
    "interpreter; run `python -m pip install -e '.[web]'` before running API "
    "contract or web shell tests."
)
LOCALHOST_SOCKET_SKIP_REASON = (
    "localhost socket access is unavailable; live API/proxy tests need to bind "
    "127.0.0.1. In Codex/sandboxed runs, rerun the test command with elevated "
    "permissions."
)


def has_module(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def web_test_dependencies_available() -> bool:
    return all(has_module(module_name) for module_name in WEB_TEST_DEPENDENCIES)


def missing_web_test_dependencies() -> tuple[str, ...]:
    return tuple(
        module_name
        for module_name in WEB_TEST_DEPENDENCIES
        if not has_module(module_name)
    )


def web_or_localhost_skip_reason(
    *,
    localhost_available: bool,
    web_available: bool,
) -> str:
    if not web_available:
        return WEB_TEST_SKIP_REASON
    if not localhost_available:
        return LOCALHOST_SOCKET_SKIP_REASON
    return "web/API and localhost socket prerequisites are available."
