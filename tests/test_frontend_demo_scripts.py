"""Regression coverage for frontend demo shell launchers."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.common import REPO_ROOT


def _write_fake_python(path: Path, *, fail_fastapi_check: bool = False) -> None:
    script = """#!/usr/bin/env bash
set -euo pipefail
if [ "${FAIL_FASTAPI_CHECK:-0}" = "1" ] && [ "${1:-}" = "-c" ] && [[ "${2:-}" == *"import fastapi, uvicorn, pydantic"* ]]; then
  exit 1
fi
printf '%s\n' "$@" > "${FAKE_PYTHON_ARGS_FILE}"
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class FrontendDemoScriptsTest(unittest.TestCase):
    def test_run_demo_backend_uses_override_python_and_injects_default_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_python = tmp / "fake-python.sh"
            args_file = tmp / "args.txt"
            _write_fake_python(fake_python)

            env = os.environ.copy()
            env["MTG_FRONTEND_PYTHON"] = str(fake_python)
            env["FAKE_PYTHON_ARGS_FILE"] = str(args_file)

            subprocess.run(
                ["bash", "frontend/scripts/run_demo_backend.sh", "--host", "127.0.0.1"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            argv = args_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual("-c", argv[0])
            self.assertIn("from mtg_source_stack.api.app import main", argv[1])
            self.assertIn("--db", argv)
            self.assertIn(str(REPO_ROOT / "var/db/frontend_demo.db"), argv)
            self.assertEqual("127.0.0.1", argv[-1])

    def test_run_demo_backend_preserves_explicit_db_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_python = tmp / "fake-python.sh"
            args_file = tmp / "args.txt"
            custom_db = tmp / "custom.db"
            _write_fake_python(fake_python)

            env = os.environ.copy()
            env["MTG_FRONTEND_PYTHON"] = str(fake_python)
            env["FAKE_PYTHON_ARGS_FILE"] = str(args_file)

            subprocess.run(
                ["bash", "frontend/scripts/run_demo_backend.sh", "--db", str(custom_db), "--port", "8001"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            argv = args_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(1, argv.count("--db"))
            self.assertIn(str(custom_db), argv)
            self.assertIn("8001", argv)

    def test_run_demo_backend_surfaces_helpful_dependency_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_python = tmp / "fake-python.sh"
            args_file = tmp / "args.txt"
            _write_fake_python(fake_python, fail_fastapi_check=True)

            env = os.environ.copy()
            env["MTG_FRONTEND_PYTHON"] = str(fake_python)
            env["FAKE_PYTHON_ARGS_FILE"] = str(args_file)
            env["FAIL_FASTAPI_CHECK"] = "1"

            result = subprocess.run(
                ["bash", "frontend/scripts/run_demo_backend.sh"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(1, result.returncode)
            self.assertIn("missing the FastAPI web dependencies", result.stderr)
            self.assertIn("MTG_FRONTEND_PYTHON", result.stderr)

    def test_bootstrap_demo_db_uses_override_python_and_injects_default_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            fake_python = tmp / "fake-python.sh"
            args_file = tmp / "args.txt"
            _write_fake_python(fake_python)

            env = os.environ.copy()
            env["MTG_FRONTEND_PYTHON"] = str(fake_python)
            env["FAKE_PYTHON_ARGS_FILE"] = str(args_file)

            subprocess.run(
                ["bash", "frontend/scripts/bootstrap_demo_db.sh", "--force"],
                cwd=REPO_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )

            argv = args_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(str(REPO_ROOT / "scripts/bootstrap_frontend_demo.py"), argv[0])
            self.assertIn("--db", argv)
            self.assertIn(str(REPO_ROOT / "var/db/frontend_demo.db"), argv)
            self.assertIn("--force", argv)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
