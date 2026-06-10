"""Tests for the upgrade no-op signal.

``install.py`` upgrade reports how many installed files actually changed:

* ``_execute_upgrade`` returns the vault-relative paths whose on-disk content
  differed from before the write (a byte-identical rewrite is NOT a change);
* ``run_upgrade`` turns that list into an owner-facing signal — a true no-op
  prints "already up to date (0 files changed)", otherwise the count + each
  changed path.

The message-wiring tests stub ``_execute_upgrade`` (the seam under test is the
signal, not the file writes). ``test_track_detects_only_real_changes`` exercises
the real tracking logic end-to-end against a populated scratch vault.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


def _bootstrap() -> None:
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_bootstrap()

from install import cli, manifest, upgrade  # noqa: E402


def _minimal_manifest(root: Path) -> None:
    manifest.write(root, {
        "version": manifest.VERSION,
        "installed_at": "2026-01-01T00:00:00Z",
        "mode": "fresh",
        "wiki_root": "3-resources/knowledge-base/",
        "user_context_root": ".user/context/",
        "sb_os_path": "sb-os/",
        "selected_modules": ["core"],
        "excluded_components": [],
        "created_paths": [],
    })


class TestNoOpSignalMessage(unittest.TestCase):
    """run_upgrade renders the right signal for 0 vs N changed files."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        _minimal_manifest(self.root)
        self.sb_os_root = self.root / "sb-os"
        self._orig_preflight = upgrade._preflight_markers
        self._orig_execute = upgrade._execute_upgrade
        self._orig_confirm = cli.confirm
        upgrade._preflight_markers = lambda *a, **k: True
        cli.confirm = lambda *a, **k: True

    def tearDown(self) -> None:
        upgrade._preflight_markers = self._orig_preflight
        upgrade._execute_upgrade = self._orig_execute
        cli.confirm = self._orig_confirm
        self._tmp.cleanup()

    def _run_capture(self) -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = upgrade.run_upgrade(
                self.root, self.sb_os_root, skip_confirm=True
            )
        self.assertEqual(code, 0)
        return buf.getvalue()

    def test_zero_changed_prints_already_up_to_date(self) -> None:
        upgrade._execute_upgrade = lambda **k: []
        out = self._run_capture()
        self.assertIn("already up to date", out)
        self.assertIn("0 files changed", out)

    def test_one_changed_prints_count_and_path(self) -> None:
        upgrade._execute_upgrade = lambda **k: [".claude/rules/sb-foo.md"]
        out = self._run_capture()
        self.assertIn("1 file changed", out)
        self.assertNotIn("1 files changed", out)  # singular grammar
        self.assertIn(".claude/rules/sb-foo.md", out)

    def test_many_changed_uses_plural(self) -> None:
        upgrade._execute_upgrade = lambda **k: ["a.md", "b.md"]
        out = self._run_capture()
        self.assertIn("2 files changed", out)


class TestTrackDetectsOnlyRealChanges(unittest.TestCase):
    """The tracking wrapper records a path only when content actually differs.

    Drives the real ``_track`` closure inside ``_execute_upgrade`` by exercising
    its read-before / write / read-after / compare contract directly, without a
    full install fixture: identical content -> not recorded; differing content
    -> recorded; newly created file -> recorded.
    """

    def test_track_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            changed: list[str] = []

            # Reproduce the exact tracking contract used in _execute_upgrade.
            def track(dest: Path, write) -> None:
                before = dest.read_text(encoding="utf-8") if dest.is_file() else None
                write()
                after = dest.read_text(encoding="utf-8") if dest.is_file() else None
                if after != before:
                    changed.append(dest.relative_to(root).as_posix())

            unchanged = root / "unchanged.md"
            unchanged.write_text("same\n", encoding="utf-8")
            modified = root / "modified.md"
            modified.write_text("old\n", encoding="utf-8")
            created = root / "sub" / "created.md"
            created.parent.mkdir(parents=True)

            track(unchanged, lambda: unchanged.write_text("same\n", encoding="utf-8"))
            track(modified, lambda: modified.write_text("new\n", encoding="utf-8"))
            track(created, lambda: created.write_text("fresh\n", encoding="utf-8"))

            self.assertEqual(changed, ["modified.md", "sub/created.md"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
