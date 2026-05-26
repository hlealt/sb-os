"""Regression tests for p1-11: categorize.py freeze gate.

Verifies that categorize.py:
  1. Refuses to overwrite an existing transactions.csv without --force
  2. Allows overwrite when --force is passed
  3. Writes normally when no existing file is present
"""
from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
_FIXTURES = _TESTS_DIR / "fixtures"
_MONTH_FIXTURE = _FIXTURES / "month-2026-04"


@pytest.fixture
def month_folder(tmp_path: Path) -> Path:
    target = tmp_path / "month-2026-04"
    shutil.copytree(_MONTH_FIXTURE, target)
    return target


@pytest.fixture
def config_folder(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    target.mkdir()
    shutil.copy(_FIXTURES / "categories.json", target / "categories.json")
    shutil.copy(_FIXTURES / "suppliers.json", target / "suppliers.json")
    return target


def _run(month: Path, config: Path, output: Path, force: bool = False) -> subprocess.CompletedProcess:
    cmd = [
        sys.executable,
        str(_SCRIPTS_DIR / "categorize.py"),
        str(month / "processed"),
        str(config),
        str(output),
    ]
    if force:
        cmd.append("--force")
    return subprocess.run(cmd, capture_output=True, text=True)


def test_first_run_succeeds(month_folder: Path, config_folder: Path, tmp_path: Path):
    """categorize.py writes normally when no output file exists."""
    output = tmp_path / "out"
    result = _run(month_folder, config_folder, output)
    assert result.returncode == 0, f"First run failed: {result.stderr}"
    assert (output / "transactions.csv").exists()


def test_second_run_blocked_without_force(month_folder: Path, config_folder: Path, tmp_path: Path):
    """Second run on same output dir is rejected without --force."""
    output = tmp_path / "out"
    # First run — creates the file.
    result = _run(month_folder, config_folder, output)
    assert result.returncode == 0

    # Second run — must be blocked.
    result2 = _run(month_folder, config_folder, output)
    assert result2.returncode != 0, "Expected non-zero exit when overwriting without --force"
    assert "FREEZE GATE" in result2.stdout or "FREEZE GATE" in result2.stderr


def test_second_run_allowed_with_force(month_folder: Path, config_folder: Path, tmp_path: Path):
    """Second run succeeds when --force is passed."""
    output = tmp_path / "out"
    result = _run(month_folder, config_folder, output)
    assert result.returncode == 0

    result2 = _run(month_folder, config_folder, output, force=True)
    assert result2.returncode == 0, f"--force run failed: {result2.stderr}"
    assert (output / "transactions.csv").exists()
