"""Regression test for the --prune-log + --report canonical-path guard.

Guard spec (D10 ruling, p4-7):
- `--prune-log --report <canonical state path>` MUST exit non-zero (exit 1)
  with a clear error message on stderr.
- `--prune-log` WITHOUT `--report` must NOT be blocked by this guard.
- `--prune-log --report <scratch path>` (any path != canonical) must NOT be
  blocked by this guard.

The canonical state path is `{wiki_root}/lint-deterministic-report.json`
where `wiki_root` is resolved from `sb-os.json`.

Run from the sb-os repo root or vault root:
    python -m pytest wiki/scripts/tests/test_prune_report_guard.py -v
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).parent.parent / "sb-wiki-lint-deterministic.py"


def make_minimal_vault(tmp: Path) -> Path:
    """Create a minimal vault skeleton with sb-os.json and a stub wiki_root.

    Returns the vault root path.
    """
    wiki_root = tmp / "kb"
    (wiki_root / "raw").mkdir(parents=True)
    (wiki_root / "wiki" / "concepts").mkdir(parents=True)
    (wiki_root / "wiki" / "entities").mkdir(parents=True)
    (wiki_root / "wiki" / "topics").mkdir(parents=True)
    (wiki_root / "wiki" / "sources").mkdir(parents=True)
    (wiki_root / "logs").mkdir(parents=True)

    sb_os_json = {
        "wiki_root": "kb",
        "user_context_root": ".user/context/",
        "sb_os_path": str(SCRIPT.parent.parent),
    }
    (tmp / "sb-os.json").write_text(json.dumps(sb_os_json), encoding="utf-8")

    # Minimal stub state file so load_state succeeds without full-fallback noise
    canonical = wiki_root / "lint-deterministic-report.json"
    stub_state = {
        "state_schema_version": "1.0",
        "mode": "apply",
        "runs_completed": 3,
        "stamps": {},
        "dirty_set": [],
        "writes": [],
        "judgment_needed": [],
        "detected": {},
        "full_mode": False,
        "state_fallback_reason": None,
        "stamp_commit_policy": "test",
    }
    canonical.write_text(json.dumps(stub_state), encoding="utf-8")
    return tmp


def run_helper(vault_root: Path, extra_args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--vault-root", str(vault_root)] + extra_args,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_prune_log_with_canonical_report_exits_nonzero():
    """--prune-log --report <canonical path> must exit 1 with a clear error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_minimal_vault(Path(tmpdir))
        canonical = vault / "kb" / "lint-deterministic-report.json"
        result = run_helper(vault, ["--prune-log", "--report", str(canonical)])
        assert result.returncode == 1, (
            f"Expected exit 1, got {result.returncode}. "
            f"stderr={result.stderr!r}"
        )
        assert "ERROR" in result.stderr, (
            f"Expected 'ERROR' in stderr. stderr={result.stderr!r}"
        )
        assert "prune-log" in result.stderr.lower(), (
            f"Expected 'prune-log' mention in stderr. stderr={result.stderr!r}"
        )


def test_prune_log_without_report_is_not_blocked():
    """--prune-log without --report must NOT be blocked by the guard (exit 0)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_minimal_vault(Path(tmpdir))
        result = run_helper(vault, ["--prune-log"])
        assert result.returncode == 0, (
            f"Expected exit 0 (guard must not fire without --report). "
            f"returncode={result.returncode}, stderr={result.stderr!r}"
        )


def test_prune_log_with_scratch_report_is_not_blocked():
    """--prune-log --report <scratch path> (not canonical) must NOT be blocked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_minimal_vault(Path(tmpdir))
        scratch = Path(tmpdir) / "scratch-report.json"
        result = run_helper(vault, ["--prune-log", "--report", str(scratch)])
        assert result.returncode == 0, (
            f"Expected exit 0 for scratch-path --report. "
            f"returncode={result.returncode}, stderr={result.stderr!r}"
        )


def test_canonical_state_not_modified_on_guard_trigger():
    """The canonical state file must remain unchanged when the guard fires."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_minimal_vault(Path(tmpdir))
        canonical = vault / "kb" / "lint-deterministic-report.json"
        original_content = canonical.read_text(encoding="utf-8")

        result = run_helper(vault, ["--prune-log", "--report", str(canonical)])
        assert result.returncode == 1, "Guard must fire"

        after_content = canonical.read_text(encoding="utf-8")
        assert after_content == original_content, (
            "Canonical state file was modified despite guard firing — data corruption!"
        )


def test_runs_completed_does_not_double_bump_with_guard():
    """runs_completed in canonical state must not change when guard fires."""
    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_minimal_vault(Path(tmpdir))
        canonical = vault / "kb" / "lint-deterministic-report.json"
        before_state = json.loads(canonical.read_text(encoding="utf-8"))
        before_runs = before_state["runs_completed"]

        # Guard should fire and not write anything
        result = run_helper(vault, ["--prune-log", "--report", str(canonical)])
        assert result.returncode == 1

        after_state = json.loads(canonical.read_text(encoding="utf-8"))
        assert after_state["runs_completed"] == before_runs, (
            f"runs_completed changed from {before_runs} to {after_state['runs_completed']} "
            "despite guard firing — double-bump regression!"
        )


def test_prune_log_with_path_variant_of_canonical_is_blocked():
    """Guard must catch path-variant spellings of the canonical path.

    Path.resolve() normalises: relative paths, redundant segments (./), and
    on Windows case differences.  This test exercises a relative-path variant
    rooted at the vault dir (equivalent to the canonical absolute path once
    resolved), confirming the guard fires regardless of how the path was typed.
    """
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        vault = make_minimal_vault(Path(tmpdir))
        # Relative-path variant: kb/lint-deterministic-report.json
        # (resolves to the same absolute path as the canonical state file when
        #  the helper is invoked with --vault-root pointing at `vault`)
        relative_variant = Path("kb") / "lint-deterministic-report.json"

        # Run the helper with the variant path — helper resolves both sides via
        # Path.resolve(), so the guard must fire.
        original_cwd = os.getcwd()
        try:
            os.chdir(str(vault))
            result = run_helper(vault, ["--prune-log", "--report", str(relative_variant)])
        finally:
            os.chdir(original_cwd)

        assert result.returncode == 1, (
            f"Guard must fire on a relative-path variant of the canonical path. "
            f"returncode={result.returncode}, stderr={result.stderr!r}"
        )
        assert "ERROR" in result.stderr, (
            f"Expected 'ERROR' in stderr for path-variant. stderr={result.stderr!r}"
        )
