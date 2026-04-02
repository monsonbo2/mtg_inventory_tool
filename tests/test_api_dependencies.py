"""Focused tests for API settings and request-context configuration."""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mtg_source_stack.api.dependencies import (
    ApiSettings,
    get_admin_request_context,
    get_authenticated_request_context,
    get_editor_request_context,
    get_mutating_request_context,
    get_request_context,
    settings_from_env,
)
from mtg_source_stack.errors import AuthenticationError, AuthorizationError


class ApiDependenciesTest(unittest.TestCase):
    def test_settings_from_env_defaults_to_local_demo_and_auto_migrate_true(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = settings_from_env()

        self.assertEqual("local_demo", settings.runtime_mode)
        self.assertTrue(settings.auto_migrate)
        self.assertFalse(settings.trust_actor_headers)

    def test_settings_from_env_uses_shared_service_default_auto_migrate_false(self) -> None:
        with patch.dict(os.environ, {"MTG_API_RUNTIME_MODE": "shared_service"}, clear=True):
            settings = settings_from_env()

        self.assertEqual("shared_service", settings.runtime_mode)
        self.assertFalse(settings.auto_migrate)

    def test_settings_from_env_explicit_auto_migrate_override_wins(self) -> None:
        scenarios = (
            ({"MTG_API_RUNTIME_MODE": "shared_service", "MTG_API_AUTO_MIGRATE": "true"}, True),
            ({"MTG_API_RUNTIME_MODE": "local_demo", "MTG_API_AUTO_MIGRATE": "false"}, False),
        )
        for env, expected in scenarios:
            with self.subTest(env=env):
                with patch.dict(os.environ, env, clear=True):
                    settings = settings_from_env()
                self.assertEqual(expected, settings.auto_migrate)

    def test_settings_from_env_rejects_invalid_runtime_mode(self) -> None:
        with patch.dict(os.environ, {"MTG_API_RUNTIME_MODE": "not-a-mode"}, clear=True):
            with self.assertRaises(ValueError):
                settings_from_env()

    def test_settings_from_env_reads_true_for_trusted_actor_headers(self) -> None:
        with patch.dict(os.environ, {"MTG_API_TRUST_ACTOR_HEADERS": "true"}, clear=True):
            settings = settings_from_env()

        self.assertTrue(settings.trust_actor_headers)

    def test_settings_from_env_treats_common_falsey_values_as_false(self) -> None:
        for raw in ("false", "0", "no", "off"):
            with self.subTest(raw=raw):
                with patch.dict(os.environ, {"MTG_API_TRUST_ACTOR_HEADERS": raw}, clear=True):
                    settings = settings_from_env()
                self.assertFalse(settings.trust_actor_headers)

    def test_settings_from_env_uses_default_authenticated_actor_header(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = settings_from_env()

        self.assertEqual("X-Authenticated-User", settings.authenticated_actor_header)

    def test_settings_from_env_reads_authenticated_actor_header_override(self) -> None:
        with patch.dict(os.environ, {"MTG_API_AUTHENTICATED_ACTOR_HEADER": "X-Forwarded-User"}, clear=True):
            settings = settings_from_env()

        self.assertEqual("X-Forwarded-User", settings.authenticated_actor_header)

    def test_settings_from_env_uses_default_authenticated_roles_header(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = settings_from_env()

        self.assertEqual("X-Authenticated-Roles", settings.authenticated_roles_header)

    def test_settings_from_env_reads_authenticated_roles_header_override(self) -> None:
        with patch.dict(os.environ, {"MTG_API_AUTHENTICATED_ROLES_HEADER": "X-Forwarded-Roles"}, clear=True):
            settings = settings_from_env()

        self.assertEqual("X-Forwarded-Roles", settings.authenticated_roles_header)

    def test_get_request_context_defaults_to_local_demo_actor(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="local_demo",
            auto_migrate=True,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={},
        )

        context = get_request_context(request)

        self.assertEqual("api", context.actor_type)
        self.assertEqual("local-demo", context.actor_id)
        self.assertTrue(context.request_id)
        self.assertEqual(frozenset({"editor", "admin"}), context.roles)

    def test_get_request_context_can_trust_actor_headers_in_local_demo_mode(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="local_demo",
            auto_migrate=True,
            host="127.0.0.1",
            port=8000,
            trust_actor_headers=True,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={"X-Actor-Id": "dev-user"},
        )

        context = get_request_context(request)

        self.assertEqual("dev-user", context.actor_id)
        self.assertEqual(frozenset({"editor", "admin"}), context.roles)

    def test_shared_service_authenticated_context_uses_authenticated_actor_header(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={"X-Authenticated-User": "shared-user"},
        )

        context = get_authenticated_request_context(request)

        self.assertEqual("shared-user", context.actor_id)
        self.assertEqual(frozenset({"editor"}), context.roles)

    def test_shared_service_authenticated_context_can_parse_admin_role_header(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={
                "X-Authenticated-User": "shared-admin",
                "X-Authenticated-Roles": "admin",
            },
        )

        context = get_authenticated_request_context(request)

        self.assertEqual("shared-admin", context.actor_id)
        self.assertEqual(frozenset({"editor", "admin"}), context.roles)

    def test_shared_service_authenticated_context_ignores_unknown_roles(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={
                "X-Authenticated-User": "shared-user",
                "X-Authenticated-Roles": "viewer,unknown",
            },
        )

        context = get_authenticated_request_context(request)

        self.assertEqual(frozenset(), context.roles)

    def test_shared_service_mutating_context_requires_authenticated_actor_header(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={"X-Actor-Id": "untrusted-user"},
        )

        with self.assertRaises(AuthenticationError):
            get_mutating_request_context(request)

    def test_shared_service_editor_context_allows_default_editor_role(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={"X-Authenticated-User": "shared-user"},
        )

        context = get_editor_request_context(request)

        self.assertEqual("shared-user", context.actor_id)
        self.assertEqual(frozenset({"editor"}), context.roles)

    def test_shared_service_editor_context_allows_admin_role(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={
                "X-Authenticated-User": "shared-admin",
                "X-Authenticated-Roles": "admin",
            },
        )

        context = get_editor_request_context(request)

        self.assertEqual(frozenset({"editor", "admin"}), context.roles)

    def test_shared_service_admin_context_rejects_editor_only_user(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={"X-Authenticated-User": "shared-user"},
        )

        with self.assertRaises(AuthorizationError):
            get_admin_request_context(request)

    def test_shared_service_admin_context_allows_admin_user(self) -> None:
        settings = ApiSettings(
            db_path="test.db",
            runtime_mode="shared_service",
            auto_migrate=False,
            host="127.0.0.1",
            port=8000,
        )
        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
            state=SimpleNamespace(),
            headers={
                "X-Authenticated-User": "shared-admin",
                "X-Authenticated-Roles": "editor,admin",
            },
        )

        context = get_admin_request_context(request)

        self.assertEqual(frozenset({"editor", "admin"}), context.roles)
