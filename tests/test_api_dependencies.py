"""Focused tests for API settings and request-context configuration."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from mtg_source_stack.api.dependencies import settings_from_env


class ApiDependenciesTest(unittest.TestCase):
    def test_settings_from_env_defaults_trust_actor_headers_to_false(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = settings_from_env()

        self.assertFalse(settings.trust_actor_headers)

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
