"""Tests for the fresh-install relocation hazard guard.

``_relocate_sb_os_clone`` copies the running sb-os clone into the new vault's
canonical path, then ``rmtree``s the original. That removal is SAFE only for a
throwaway bootstrap clone. The hazard: a user runs the installer from the LIVE
sb-os repo of their working vault (``.../3-resources/tools/sb-os``) while
targeting a SEPARATE external vault. Without a guard the copy succeeds and then
``rmtree`` silently DELETES the live repo, breaking the working vault. Cold
verifiers historically dodged this only by running from a throwaway copy.

Contract under test:

* live-install src (an ``sb-os.json`` above it resolves back to it) is COPIED
  into the target but the original is PRESERVED — never deleted;
* a throwaway clone (no manifest above it) is still removed after the copy, so
  the normal relocation cleanup is unregressed.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


def _bootstrap() -> None:
    # <repo>/install/tests/<this-file>
    tests_dir = Path(__file__).resolve().parent
    repo_root = tests_dir.parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_bootstrap()

from install import fresh  # noqa: E402


def _make_repo(root: Path) -> Path:
    """Create a minimal stand-in sb-os clone with a marker file."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "install.py").write_text("# marker\n", encoding="utf-8")
    (root / "para").mkdir(exist_ok=True)
    (root / "para" / "marker.txt").write_text("payload\n", encoding="utf-8")
    return root


class TestLiveInstallPreserved(unittest.TestCase):
    """A live installed repo is copied but never deleted."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name).resolve()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_live_install_is_detected(self) -> None:
        vault = self.base / "working-vault"
        src = _make_repo(vault / "3-resources" / "tools" / "sb-os")
        (vault / "sb-os.json").write_text(
            json.dumps({"sb_os_path": "3-resources/tools/sb-os/"}),
            encoding="utf-8",
        )
        self.assertTrue(fresh._is_live_install(src))

    def test_throwaway_clone_not_detected(self) -> None:
        src = _make_repo(self.base / "throwaway" / "sb-os")
        self.assertFalse(fresh._is_live_install(src))

    def test_relocate_preserves_live_repo(self) -> None:
        vault = self.base / "working-vault"
        src = _make_repo(vault / "3-resources" / "tools" / "sb-os")
        (vault / "sb-os.json").write_text(
            json.dumps({"sb_os_path": "3-resources/tools/sb-os/"}),
            encoding="utf-8",
        )
        target = self.base / "external-target"
        target.mkdir()

        fresh._relocate_sb_os_clone(src, target)

        # Original live repo MUST survive intact.
        self.assertTrue(src.is_dir(), "live source repo was deleted")
        self.assertTrue((src / "para" / "marker.txt").is_file())
        # Clone WAS copied into the new target so the install still works.
        canonical = target / "3-resources" / "tools" / "sb-os"
        self.assertTrue((canonical / "para" / "marker.txt").is_file())

    def test_relocate_removes_throwaway_clone(self) -> None:
        src = _make_repo(self.base / "throwaway" / "sb-os")
        target = self.base / "external-target"
        target.mkdir()

        fresh._relocate_sb_os_clone(src, target)

        # Throwaway original is cleaned up (no regression).
        self.assertFalse(src.exists(), "throwaway clone was not removed")
        canonical = target / "3-resources" / "tools" / "sb-os"
        self.assertTrue((canonical / "para" / "marker.txt").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
