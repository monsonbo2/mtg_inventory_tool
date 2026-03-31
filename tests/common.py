"""Shared helpers for the CLI-oriented integration tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
IMPORTER_MODULE = "mtg_source_stack.mvp_importer"
CLI_MODULE = "mtg_source_stack.personal_inventory_cli"

if str(SRC_DIR) not in sys.path:
    # Allow the tests and subprocess-launched modules to import the local
    # checkout without requiring an editable install first.
    sys.path.insert(0, str(SRC_DIR))

MODULE_ENV = os.environ.copy()
existing_pythonpath = MODULE_ENV.get("PYTHONPATH")
# Mirror that import path setup for `python -m ...` subprocess calls.
MODULE_ENV["PYTHONPATH"] = (
    f"{SRC_DIR}{os.pathsep}{existing_pythonpath}" if existing_pythonpath else str(SRC_DIR)
)


def fixture_path(*parts: str) -> Path:
    return FIXTURES_DIR.joinpath(*parts)


def load_fixture_json(*parts: str):
    return json.loads(fixture_path(*parts).read_text(encoding="utf-8"))


def load_fixture_text(*parts: str) -> str:
    return fixture_path(*parts).read_text(encoding="utf-8")


def copy_fixture(destination: Path, *parts: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture_path(*parts), destination)
    return destination


def materialize_fixture_bundle(
    destination_dir: Path,
    fixture_name: str,
    *filenames: str,
) -> dict[str, Path]:
    return {
        filename: copy_fixture(destination_dir / filename, fixture_name, filename)
        for filename in filenames
    }


class RepoSmokeTestCase(unittest.TestCase):
    """Base case for tests that exercise the real command-line entry points."""

    def run_module_process(
        self,
        module: str,
        *args: str,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        # Running through `python -m` keeps the tests close to how a user would
        # invoke the tools while still using the current source tree.
        return subprocess.run(
            [sys.executable, "-m", module, *args],
            cwd=REPO_ROOT,
            env=MODULE_ENV,
            capture_output=True,
            text=True,
            check=check,
        )

    def run_module(self, module: str, *args: str) -> str:
        result = self.run_module_process(module, *args, check=True)
        return result.stdout.strip()

    def run_importer(self, *args: str) -> str:
        return self.run_module(IMPORTER_MODULE, *args)

    def run_cli(self, *args: str) -> str:
        return self.run_module(CLI_MODULE, *args)

    def run_failing_importer(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_module_process(IMPORTER_MODULE, *args, check=False)

    def run_failing_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_module_process(CLI_MODULE, *args, check=False)
