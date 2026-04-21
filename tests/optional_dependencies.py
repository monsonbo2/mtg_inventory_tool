"""Helpers for tests that depend on optional dependency groups."""

from __future__ import annotations

import importlib.util


WEB_TEST_DEPENDENCIES = ("fastapi", "httpx", "pydantic", "uvicorn", "multipart")
WEB_TEST_SKIP_REASON = (
    "optional web/API test dependencies are not installed; run `pip install -e '.[web]'` "
    "before running API contract or web shell tests."
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
