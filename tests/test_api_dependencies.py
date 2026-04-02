"""Focused tests for API settings and request-context configuration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mtg_source_stack.api.dependencies import settings_from_env


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
