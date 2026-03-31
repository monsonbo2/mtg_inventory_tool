"""Small smoke checks for the public module entrypoints."""

from __future__ import annotations

from tests.common import CLI_MODULE, IMPORTER_MODULE, RepoSmokeTestCase


class EntryPointSmokeTest(RepoSmokeTestCase):
    def test_personal_inventory_module_help_still_works(self) -> None:
        # A clean help path is enough to prove the shim still imports and hands
        # off to the real parser without exercising the whole CLI again.
        result = self.run_module_process(CLI_MODULE, "--help", check=False)

        self.assertEqual(0, result.returncode)
        self.assertIn("usage:", result.stdout)
        self.assertIn("create-inventory", result.stdout)
        self.assertIn("list-owned", result.stdout)
        self.assertEqual("", result.stderr)

    def test_importer_module_help_still_works(self) -> None:
        # Keep one equally small check for the importer wrapper so the public
        # `python -m ...` entrypoint stays part of the tested surface.
        result = self.run_module_process(IMPORTER_MODULE, "--help", check=False)

        self.assertEqual(0, result.returncode)
        self.assertIn("usage:", result.stdout)
        self.assertIn("init-db", result.stdout)
        self.assertIn("import-all", result.stdout)
        self.assertEqual("", result.stderr)
